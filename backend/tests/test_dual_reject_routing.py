"""spec11 Part 2 (dual reject routing) dispatcher-level acceptance tests --
proves a part failing s1 is pulled at r1 before ever reaching s2/s3, and a
part passing s1 but failing s2/s3 rides through r1 untouched and is pulled
at r2 instead (the med_3_station part's own topology: r1 after s1 watching
only s1, r2 after s3 watching s2+s3).

Ticks are driven manually (dispatcher._tick_sim()), station results applied
directly via tracker calls between ticks (not through a registry callback)
so the exact moment each result lands is fully controlled -- same style as
test_dispatcher_real_mode.py uses for the equivalent real-mode routing
logic. Extends test_dispatcher.py's FakeStation/FakeResolvedConfig
fixtures, same as test_reject_and_sim.py does for the single-reject-station
case.

A tracked part's own slot index never changes once assigned -- what
changes each tick is which slot index each station's *position* currently
corresponds to (station_slot_id rotates). With station offsets spaced
exactly one slot apart (10 pulses = 1 slot here) and ENTRY_INTERVAL_TICKS
forced to 1, one tick advances every station's position by exactly one
slot, so "N ticks after entry" deterministically lines up the tracked
part's fixed slot with the Nth station in ring order (s1, then r1, then
s2, then s3, then r2, then exit1) -- verified against a live trace before
writing these assertions, not hand-derived and hoped correct."""

import app.indexer.dispatcher as dispatcher_module
from app.indexer.dispatcher import StationDispatcher
from app.indexer.tracker import IndexerSlotTracker

from test_dispatcher import FakeResolvedConfig, FakeStation


class NullRegistry:
    """fire_station() is a no-op here -- station results are applied
    directly via tracker.apply_station_result() in these tests, not
    through a registry/inference callback."""

    def fire_station(self, station_id, slot_id=None, part_id=None):
        pass


def make_dual_reject_dispatcher():
    # pulses_per_slot = 10 -- stations spaced exactly one slot apart, in
    # ring order: entry(offset 0) s1(10) r1(20) s2(30) s3(40) r2(50)
    # exit1(60) -- leaves slots 7/8/9 spare so the ring isn't 100% packed.
    pulse_offsets = {"s1": 10, "r1": 20, "s2": 30, "s3": 40, "r2": 50, "exit1": 60}
    fake_stations = [
        FakeStation(id="s1", type="inspection"),
        FakeStation(id="r1", type="reject", enabled=True, watches=["s1"]),
        FakeStation(id="s2", type="inspection"),
        FakeStation(id="s3", type="inspection"),
        FakeStation(id="r2", type="reject", enabled=True, watches=["s2", "s3"]),
        FakeStation(id="exit1", type="exit"),
    ]
    config = FakeResolvedConfig(fake_stations, tick_interval_ms=60)
    tracker = IndexerSlotTracker(
        n_slots=10, encoder_cpr=100, station_pulse_offsets=pulse_offsets,
        inspection_station_ids=["s1", "s2", "s3"],
    )
    registry = NullRegistry()
    dispatcher = StationDispatcher(config, registry, tracker)
    return dispatcher, tracker


def run_ticks(dispatcher, n, monkeypatch):
    monkeypatch.setattr(dispatcher_module, "ENTRY_INTERVAL_TICKS", 1)
    monkeypatch.setattr(dispatcher, "_schedule_tick", lambda: None)
    dispatcher._stopped = False
    for _ in range(n):
        dispatcher._tick_sim()


def _first_occupied_slot(tracker) -> int:
    return next(i for i in range(tracker.n_slots) if tracker.get_slot(i).assign_part_id is not None)


def test_s1_failure_is_pulled_at_r1_before_reaching_s2_s3(monkeypatch):
    dispatcher, tracker = make_dual_reject_dispatcher()

    run_ticks(dispatcher, 1, monkeypatch)  # a part enters -- track its (fixed) slot from here on
    part_slot = _first_occupied_slot(tracker)

    run_ticks(dispatcher, 1, monkeypatch)  # s1's position now lines up with part_slot
    assert tracker.get_slot(part_slot).station_states["s1"] == "pending"
    tracker.apply_station_result(part_slot, "s1", passed=False)  # fail s1

    run_ticks(dispatcher, 1, monkeypatch)  # r1's position now lines up with part_slot
    # r1 (watches=[s1]) must pull it here -- never reaches s2/s3.
    assert tracker.get_slot(part_slot).assign_part_id is None
    assert tracker.reject_removed == 1
    assert tracker.nok_total == 1

    run_ticks(dispatcher, 3, monkeypatch)  # would-be s2/s3/r2 positions for this (now-freed) slot
    assert tracker.get_slot(part_slot).assign_part_id is None  # nothing re-entered it yet
    assert tracker.reject_removed == 1  # r2 never had anything to catch


def test_s1_pass_but_s2_or_s3_failure_rides_through_r1_and_is_pulled_at_r2(monkeypatch):
    dispatcher, tracker = make_dual_reject_dispatcher()

    run_ticks(dispatcher, 1, monkeypatch)  # a part enters
    part_slot = _first_occupied_slot(tracker)

    run_ticks(dispatcher, 1, monkeypatch)  # s1's position -> part_slot
    tracker.apply_station_result(part_slot, "s1", passed=True)  # s1 passes

    run_ticks(dispatcher, 1, monkeypatch)  # r1's position -> part_slot (watches=[s1], s1 is ok) -- must NOT pull it
    assert tracker.get_slot(part_slot).assign_part_id is not None
    assert tracker.reject_removed == 0

    run_ticks(dispatcher, 1, monkeypatch)  # s2's position -> part_slot
    tracker.apply_station_result(part_slot, "s2", passed=False)  # fail s2 -- s3 is never even resolved

    run_ticks(dispatcher, 1, monkeypatch)  # s3's position -> part_slot -- position only, r2 doesn't wait for it

    run_ticks(dispatcher, 1, monkeypatch)  # r2's position -> part_slot (watches=[s2, s3], s2 is nok) -- must pull it
    assert tracker.get_slot(part_slot).assign_part_id is None
    assert tracker.reject_removed == 1
    assert tracker.nok_total == 1
