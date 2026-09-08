"""Dispatcher-level tests for the reject station (r1) and the sim
verification harness -- extends test_dispatcher.py's fixtures (FakeStation/
FakeResolvedConfig) with a synchronous fake station_registry
that resolves s1/s2 verdicts immediately (no threads, no real inference),
so the per-revolution invariant checks below are exact and deterministic
rather than timing-dependent.

Ticks are driven manually (dispatcher._tick_sim() called directly in a loop,
with _schedule_tick() stubbed out) rather than via real threading.Timer +
time.sleep -- avoids both flakiness and the minutes it would otherwise take
to run enough real-time ticks for a multi-revolution invariant check.

ENTRY_INTERVAL_TICKS is monkeypatched to 1 for these tests specifically:
with the default of 2 and a fixed-parity entry cadence (entry is only ever
attempted every Nth tick, and the ring advances exactly one slot per tick),
entry attempts only ever land on slot indices of one parity -- a pre-existing
property of the dispatcher's entry gating, not something these tests
introduce. Patching it to 1 makes entry attempt every physical slot index
exactly once per revolution, which is what makes the invariant assertions
below ("every non-blank slot gets resolved exactly once per revolution")
exactly true rather than only true for half the ring.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import app.indexer.dispatcher as dispatcher_module
from app.indexer.tracker import IndexerSlotTracker

from test_dispatcher import FakeResolvedConfig, FakeStation


@dataclass
class SyncSimRegistry:
    """Synchronously resolves s1 (measurement, always passes -- s1 isn't
    part of this feature's sim-verdict harness, only s2 is) and s2 (defect,
    reads the slot's forced_verdict) the instant fire_station() is called --
    stands in for the real async station_registry + on_result callback
    chain (app/inspection_session.py), whose actual wiring is covered by
    the live smoke test, not this fast unit suite. mark_pending() is NOT
    called here -- the dispatcher itself already calls it right before
    fire_station() (see dispatcher.py's _tick_sim()), so by the time this runs
    the station is already "pending"; this only needs to resolve it."""
    tracker: IndexerSlotTracker
    measurement_station_ids: Set[str] = field(default_factory=set)
    defect_station_ids: Set[str] = field(default_factory=set)
    fired: List[str] = field(default_factory=list)

    def fire_station(self, station_id: str, slot_id: Optional[int] = None, part_id: Optional[object] = None) -> None:
        self.fired.append(station_id)
        if slot_id is None:
            return
        if station_id in self.measurement_station_ids:
            self.tracker.apply_station_result(slot_id, station_id, passed=True)
        elif station_id in self.defect_station_ids:
            forced = self.tracker.get_slot(slot_id).forced_verdict
            self.tracker.apply_station_result(slot_id, station_id, passed=(forced != "NOK"))


def make_sim_dispatcher(n_slots=20, encoder_cpr=200, r1_enabled=True, blank=5, nok=5, tick_ms=60):
    # pulses_per_slot = 10 -- offsets chosen as clean slot multiples so
    # station_offsets round exactly, matching machine_config.yaml's own
    # s1/s2/r1/exit1 relative spacing (2/4/6/8 out of 20 slots).
    pulse_offsets = {"s1": 20, "s2": 40, "r1": 60, "exit1": 80}
    fake_stations = [
        FakeStation(id="s1", type="inspection"),
        FakeStation(id="s2", type="inspection"),
        FakeStation(id="r1", type="reject", enabled=r1_enabled),
        FakeStation(id="exit1", type="exit"),
    ]
    config = FakeResolvedConfig(fake_stations, tick_interval_ms=tick_ms)
    tracker = IndexerSlotTracker(
        n_slots=n_slots, encoder_cpr=encoder_cpr, station_pulse_offsets=pulse_offsets,
        inspection_station_ids=["s1", "s2"],
    )
    tracker.seed_sim(blank=blank, nok=nok)
    registry = SyncSimRegistry(tracker, measurement_station_ids={"s1"}, defect_station_ids={"s2"})

    from app.indexer.dispatcher import StationDispatcher
    dispatcher = StationDispatcher(config, registry, tracker)
    return dispatcher, tracker, registry


def run_ticks_synchronously(dispatcher, n: int, monkeypatch) -> None:
    """Drives dispatcher._tick_sim() directly n times with no real timers/sleep
    -- stubs _schedule_tick() to a no-op (it would otherwise start a real
    threading.Timer for the next tick even when _tick_sim() is called directly)
    and forces ENTRY_INTERVAL_TICKS=1 for the reason in this module's
    docstring."""
    monkeypatch.setattr(dispatcher_module, "ENTRY_INTERVAL_TICKS", 1)
    monkeypatch.setattr(dispatcher, "_schedule_tick", lambda: None)
    dispatcher._stopped = False
    for _ in range(n):
        dispatcher._tick_sim()


def return_arc_slot_ids(tracker: IndexerSlotTracker, exit_offset_slots: int) -> List[int]:
    """Physical slot indices currently positioned strictly between Exit and
    Entry (the empty return path) -- offsets exit_offset..n_slots-1 from the
    current entry position, inclusive of exit's own offset (its
    transition_exit has already run by the time _tick_sim() returns)."""
    return [
        (tracker._entry_slot_id - offset) % tracker.n_slots
        for offset in range(exit_offset_slots, tracker.n_slots)
    ]


def test_per_revolution_invariant_ok_nok_deltas_match_resolved_counts(monkeypatch):
    dispatcher, tracker, _registry = make_sim_dispatcher(n_slots=20, blank=5, nok=5)
    resolved = tracker  # ok/nok/blank counts are directly on the tracker after seed_sim

    run_ticks_synchronously(dispatcher, 20, monkeypatch)  # warm-up: settle to steady state

    ok_before, nok_before = tracker.ok_total, tracker.nok_total
    run_ticks_synchronously(dispatcher, 20, monkeypatch)  # exactly one more revolution
    ok_after, nok_after = tracker.ok_total, tracker.nok_total

    resolved_ok = sum(1 for s in resolved.slots.values() if s.forced_verdict == "OK")
    resolved_nok = sum(1 for s in resolved.slots.values() if s.forced_verdict == "NOK")
    resolved_blank = sum(1 for s in resolved.slots.values() if s.blank)

    assert ok_after - ok_before == resolved_ok == 10
    assert nok_after - nok_before == resolved_nok == 5
    assert (ok_after - ok_before) + (nok_after - nok_before) == tracker.n_slots - resolved_blank == 15


def test_r1_disabled_routes_nok_to_exit_without_touching_reject_removed(monkeypatch):
    dispatcher, tracker, _registry = make_sim_dispatcher(n_slots=20, blank=5, nok=5, r1_enabled=False)

    run_ticks_synchronously(dispatcher, 20, monkeypatch)  # warm-up

    nok_before, r1_before = tracker.nok_total, tracker.reject_removed
    run_ticks_synchronously(dispatcher, 20, monkeypatch)  # one more revolution
    nok_after, r1_after = tracker.nok_total, tracker.reject_removed

    assert r1_after == r1_before == 0  # r1 disabled -- never actually removes anything
    assert nok_after - nok_before == 5  # but nok_total still climbs -- via exit's fallback path


def test_return_arc_never_shows_an_occupied_slot(monkeypatch):
    dispatcher, tracker, _registry = make_sim_dispatcher(n_slots=20, blank=5, nok=5)
    exit_offset_slots = 8  # matches pulse_offsets["exit1"]=80 / pulses_per_slot=10

    monkeypatch.setattr(dispatcher_module, "ENTRY_INTERVAL_TICKS", 1)
    monkeypatch.setattr(dispatcher, "_schedule_tick", lambda: None)
    dispatcher._stopped = False

    from app.indexer.tracker import SlotStatus

    for _ in range(60):  # three full revolutions
        dispatcher._tick_sim()
        for slot_id in return_arc_slot_ids(tracker, exit_offset_slots):
            record = tracker.get_slot(slot_id)
            assert record.status in (SlotStatus.EMPTY, SlotStatus.BLANK), (
                f"slot {slot_id} on the return arc has status {record.status} -- "
                f"a state-machine bug let a resolved/unresolved part linger past exit"
            )
            assert record.assign_part_id is None
