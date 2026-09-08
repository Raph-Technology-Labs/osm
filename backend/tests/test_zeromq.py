"""publish_ring_state() unit tests -- covers spec13 #7: a serialization
failure must be caught and logged, not propagate into the threading.Timer
callback that calls it (StationDispatcher's tick), which would silently
kill all future ticks with no error surfaced anywhere else.

broadcast() itself is monkeypatched out -- these tests only care whether
publish_ring_state() raises and whether it attempts to send, not whether a
real ZMQ socket receives anything."""

from dataclasses import dataclass, field
from typing import Optional

import pytest

from app.utils import zeromq


@dataclass
class FakeStatus:
    value: str


@dataclass
class FakeRecord:
    status: FakeStatus
    assign_part_id: Optional[object] = None
    station_states: dict = field(default_factory=dict)


class FakeTracker:
    def __init__(self, slots):
        self.slots = slots
        self._entry_slot_id = 0
        self.ok_total = 0
        self.nok_total = 0
        self.r1_removed = 0


def test_publish_ring_state_broadcasts_valid_snapshot(monkeypatch):
    sent = []
    monkeypatch.setattr(zeromq, "broadcast", lambda topic, message: sent.append((topic, message)))
    tracker = FakeTracker({0: FakeRecord(status=FakeStatus("EMPTY"), station_states={"s1": "unreached"})})

    zeromq.publish_ring_state(tracker, revolutions=3)

    assert len(sent) == 1
    topic, message = sent[0]
    assert topic == "MessageType.RingState"
    assert '"revolutions": 3' in message


def test_publish_ring_state_swallows_serialization_error_instead_of_raising(monkeypatch):
    sent = []
    monkeypatch.setattr(zeromq, "broadcast", lambda topic, message: sent.append((topic, message)))
    # A set is not JSON-serializable -- json.dumps raises TypeError on it,
    # simulating any future non-serializable value ending up in station_states.
    tracker = FakeTracker({0: FakeRecord(status=FakeStatus("LOADED"), station_states={"s1", "not serializable"})})

    zeromq.publish_ring_state(tracker, revolutions=1)  # must not raise

    assert sent == []  # skipped this tick's publish, nothing sent


def test_publish_ring_state_recovers_on_the_next_good_tick(monkeypatch):
    # The failure must be isolated to the one bad tick -- a subsequent
    # call with valid data must still publish normally, proving nothing
    # about the dispatcher's tick chain (which this doesn't touch directly,
    # but calling this function repeatedly emulates it) gets stuck.
    sent = []
    monkeypatch.setattr(zeromq, "broadcast", lambda topic, message: sent.append((topic, message)))
    bad_tracker = FakeTracker({0: FakeRecord(status=FakeStatus("LOADED"), station_states={"s1", "bad"})})
    good_tracker = FakeTracker({0: FakeRecord(status=FakeStatus("EMPTY"), station_states={"s1": "unreached"})})

    zeromq.publish_ring_state(bad_tracker, revolutions=1)
    zeromq.publish_ring_state(good_tracker, revolutions=2)

    assert len(sent) == 1
    assert '"revolutions": 2' in sent[0][1]
