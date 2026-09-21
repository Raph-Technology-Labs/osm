"""spec11 Part 3 (continuous, no removal) dispatcher-level acceptance
tests -- extends test_reject_and_sim.py's SyncSimRegistry/FakeStation
fixtures with a virtual_exit-only station layout (no reject, no real
exit). Ticks driven manually via _tick_sim(), same pattern as
test_reject_and_sim.py uses for the per-revolution invariant check."""

import app.indexer.dispatcher as dispatcher_module
from app.indexer.tracker import IndexerSlotTracker

from test_dispatcher import FakeResolvedConfig, FakeStation
from test_reject_and_sim import SyncSimRegistry, run_ticks_synchronously


def make_virtual_exit_dispatcher(n_slots=20, encoder_cpr=200, blank=5, nok=5, tick_ms=60):
    # pulses_per_slot = 10 -- s1(20)/s2(40)/vexit1(60), matching
    # test_reject_and_sim.py's own s1/s2/r1/exit1 relative spacing.
    pulse_offsets = {"s1": 20, "s2": 40, "vexit1": 60}
    fake_stations = [
        FakeStation(id="s1", type="inspection"),
        FakeStation(id="s2", type="inspection"),
        FakeStation(id="vexit1", type="virtual_exit"),
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


def test_virtual_exit_never_frees_the_slot(monkeypatch):
    dispatcher, tracker, _registry = make_virtual_exit_dispatcher(n_slots=20, blank=5, nok=5)

    run_ticks_synchronously(dispatcher, 20, monkeypatch)  # one full revolution

    # Every non-blank slot has an occupant, permanently -- entered_count
    # only grows as slots fill for the first time, never again after.
    non_blank = [s for s in tracker.slots.values() if not s.blank]
    assert all(s.assign_part_id is not None for s in non_blank)
    assert tracker.entered_count == len(non_blank)  # exactly one entry per non-blank slot, ever

    entered_before = tracker.entered_count
    run_ticks_synchronously(dispatcher, 40, monkeypatch)  # two more revolutions
    assert tracker.entered_count == entered_before  # no slot was ever re-entered by the feeder
    assert tracker.exited_count == 0  # free_slot() is never called for this part at all


def test_virtual_exit_same_part_id_persists_across_revolutions(monkeypatch):
    dispatcher, tracker, _registry = make_virtual_exit_dispatcher(n_slots=20, blank=5, nok=5)

    run_ticks_synchronously(dispatcher, 20, monkeypatch)
    part_ids_after_lap_1 = {i: s.assign_part_id for i, s in tracker.slots.items() if s.assign_part_id is not None}

    run_ticks_synchronously(dispatcher, 20, monkeypatch)
    part_ids_after_lap_2 = {i: s.assign_part_id for i, s in tracker.slots.items() if s.assign_part_id is not None}

    assert part_ids_after_lap_1 == part_ids_after_lap_2  # same physical parts, same slots, every lap


def test_per_revolution_invariant_no_double_counting_for_continuous_part(monkeypatch):
    dispatcher, tracker, _registry = make_virtual_exit_dispatcher(n_slots=20, blank=5, nok=5)

    run_ticks_synchronously(dispatcher, 20, monkeypatch)  # warm-up: settle to steady state

    ok_before, nok_before = tracker.ok_total, tracker.nok_total
    run_ticks_synchronously(dispatcher, 20, monkeypatch)  # exactly one more revolution
    ok_after, nok_after = tracker.ok_total, tracker.nok_total

    resolved_ok = sum(1 for s in tracker.slots.values() if s.forced_verdict == "OK")
    resolved_nok = sum(1 for s in tracker.slots.values() if s.forced_verdict == "NOK")
    resolved_blank = sum(1 for s in tracker.slots.values() if s.blank)

    # Each non-blank slot's occupant gets tallied EXACTLY once per
    # revolution -- not zero (missed), not more than once (double-counted).
    assert ok_after - ok_before == resolved_ok == 10
    assert nok_after - nok_before == resolved_nok == 5
    assert (ok_after - ok_before) + (nok_after - nok_before) == tracker.n_slots - resolved_blank == 15
