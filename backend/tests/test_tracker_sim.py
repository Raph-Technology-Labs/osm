"""Pure IndexerSlotTracker unit tests for the per-station slot state
machine, sim seeding, and the reject/exit transitions -- no dispatcher, no
threading timers, just the tracker's own methods called directly.

Matches docs/reference/segment_slot_simulator.html's model: each inspection
station has its own independent unreached/pending/ok/nok state per slot
(mark_pending then apply_station_result), not a single collapsed whole-slot
verdict."""

from dataclasses import dataclass
from typing import Optional

from app.indexer.tracker import (
    BlankSlotEntryError,
    IndexerSlotTracker,
    SlotCollisionError,
    SlotStatus,
)


def make_tracker(n_slots=10, encoder_cpr=100, offsets=None, inspection_station_ids=("s1", "s2")):
    return IndexerSlotTracker(
        n_slots=n_slots,
        encoder_cpr=encoder_cpr,
        station_pulse_offsets=offsets or {},
        inspection_station_ids=inspection_station_ids,
    )


@dataclass
class FakeRejectStation:
    """transition_reject()/any_watched_station_nok() only ever read
    .enabled/.watches off whatever's passed in -- a real RejectStation
    config object works too, but tracker-only tests shouldn't need to
    construct one just for these two fields."""
    enabled: bool = True
    watches: Optional[list] = None


def test_seed_sim_marks_blank_and_forced_verdict_by_count():
    # Indices are chosen randomly (per explicit instruction 2026-09-07), so
    # this checks counts/properties rather than fixed positions.
    tracker = make_tracker(n_slots=10)
    tracker.seed_sim(blank=2, nok=3)

    blank_slots = [s for s in tracker.slots.values() if s.blank]
    nok_slots = [s for s in tracker.slots.values() if not s.blank and s.forced_verdict == "NOK"]
    ok_slots = [s for s in tracker.slots.values() if not s.blank and s.forced_verdict == "OK"]

    assert len(blank_slots) == 2
    assert all(s.status == SlotStatus.BLANK and s.forced_verdict is None for s in blank_slots)
    assert len(nok_slots) == 3
    assert len(ok_slots) == 5


def test_seed_sim_forces_no_verdict_when_nok_is_zero():
    # Production always calls with nok=0 (default) -- every non-blank slot
    # must be left forced_verdict=None so real inference decides, not "OK".
    tracker = make_tracker(n_slots=10)
    tracker.seed_sim(blank=2)

    non_blank = [s for s in tracker.slots.values() if not s.blank]
    assert len(non_blank) == 8
    assert all(s.forced_verdict is None for s in non_blank)


def test_seed_sim_raises_when_blank_plus_nok_exceeds_total():
    tracker = make_tracker(n_slots=10)
    try:
        tracker.seed_sim(blank=6, nok=6)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_on_part_entered_raises_for_blank_slot():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)  # pulses_per_slot=10
    tracker.seed_sim(blank=2)
    # Blank indices are chosen randomly -- find one rather than assuming slot 0.
    blank_slot_id = next(i for i, s in tracker.slots.items() if s.blank)
    entry_pulse = blank_slot_id * 10 + 5  # midpoint of that slot's pulse range
    try:
        tracker.on_part_entered(entry_pulse=entry_pulse, part_id=1)
        assert False, "expected BlankSlotEntryError"
    except BlankSlotEntryError:
        pass
    assert tracker.entered_count == 0


def test_on_part_entered_still_raises_collision_for_occupied_non_blank_slot():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    tracker.on_part_entered(entry_pulse=5, part_id=1)  # slot 0
    try:
        tracker.on_part_entered(entry_pulse=5, part_id=2)
        assert False, "expected SlotCollisionError"
    except SlotCollisionError:
        pass


def test_on_part_entered_initializes_every_inspection_station_unreached():
    tracker = make_tracker(n_slots=10, encoder_cpr=100, inspection_station_ids=("s1", "s2"))
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)

    assert tracker.slots[slot_id].station_states == {"s1": "unreached", "s2": "unreached"}
    assert tracker.slots[slot_id].status == SlotStatus.LOADED
    assert tracker.any_station_nok(slot_id) is False
    assert tracker.all_stations_ok(slot_id) is False  # unreached != ok


def test_get_slot_returns_a_snapshot_matching_live_state():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)

    snapshot = tracker.get_slot(slot_id)

    assert snapshot.assign_part_id == 1
    assert snapshot.station_states == {"s1": "unreached", "s2": "unreached"}


def test_get_slot_mutation_does_not_leak_into_live_state():
    # spec13 #10: get_slot() must return a copy, not the live SlotRecord --
    # mutating what it returns (including its dict fields) must never
    # affect the tracker's actual internal state.
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)

    snapshot = tracker.get_slot(slot_id)
    snapshot.assign_part_id = 999
    snapshot.blank = True
    snapshot.station_states["s1"] = "nok"
    snapshot.results["s1:defect"] = {"cam1": False}

    live = tracker.get_slot(slot_id)  # fresh snapshot, to check real internal state
    assert live.assign_part_id == 1
    assert live.blank is False
    assert live.station_states == {"s1": "unreached", "s2": "unreached"}
    assert live.results == {}


def test_mark_pending_transitions_unreached_to_pending():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)

    tracker.mark_pending(slot_id, "s1")

    assert tracker.slots[slot_id].station_states == {"s1": "pending", "s2": "unreached"}


def test_apply_station_result_transitions_pending_to_ok_or_nok():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")

    tracker.apply_station_result(slot_id, "s1", passed=True)
    assert tracker.slots[slot_id].station_states["s1"] == "ok"

    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=False)
    assert tracker.slots[slot_id].station_states["s2"] == "nok"


def test_mark_pending_drops_stale_call_for_a_different_part_id():
    # spec13 #1: a mark_pending call carrying the part_id it was fired for
    # must be dropped, not applied, if a DIFFERENT part now occupies that
    # slot (the original part already left -- rejected/exited -- and the
    # ring rotated a new part into the same physical index).
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)

    tracker.mark_pending(slot_id, "s1", part_id=999)  # stale -- slot holds part 1, not 999

    assert tracker.slots[slot_id].station_states == {"s1": "unreached", "s2": "unreached"}


def test_mark_pending_applies_when_part_id_matches():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)

    tracker.mark_pending(slot_id, "s1", part_id=1)

    assert tracker.slots[slot_id].station_states["s1"] == "pending"


def test_apply_station_result_drops_stale_call_for_a_different_part_id():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1", part_id=1)

    tracker.apply_station_result(slot_id, "s1", passed=True, part_id=999)  # stale

    assert tracker.slots[slot_id].station_states["s1"] == "pending"  # unchanged, not "ok"


def test_apply_station_result_applies_when_part_id_matches():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1", part_id=1)

    tracker.apply_station_result(slot_id, "s1", passed=True, part_id=1)

    assert tracker.slots[slot_id].station_states["s1"] == "ok"


def test_part_id_check_disabled_when_omitted_preserves_existing_behavior():
    # Callers that don't pass part_id (omitted -> None) get today's exact
    # behavior -- no identity check at all, matches every pre-spec13 caller.
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)

    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=True)

    assert tracker.slots[slot_id].station_states["s1"] == "ok"


def test_any_station_nok_is_true_even_while_another_station_still_pending():
    # The core "don't wait for the rest" rule -- r1 acts on this.
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=False)  # s1 -> nok
    tracker.mark_pending(slot_id, "s2")  # s2 still pending, not resolved

    assert tracker.any_station_nok(slot_id) is True
    assert tracker.all_stations_ok(slot_id) is False


def test_all_stations_ok_requires_every_station_resolved_ok():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=True)
    assert tracker.all_stations_ok(slot_id) is False  # s2 still unreached

    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=True)
    assert tracker.all_stations_ok(slot_id) is True
    assert tracker.any_station_nok(slot_id) is False


def test_station_states_reset_across_discharge_and_reentry():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=False)
    tracker.free_slot(slot_id)

    assert tracker.slots[slot_id].station_states == {}

    slot_id2 = tracker.on_part_entered(entry_pulse=5, part_id=2)  # same physical slot, new part
    assert slot_id2 == slot_id
    assert tracker.slots[slot_id2].station_states == {"s1": "unreached", "s2": "unreached"}


def test_transition_reject_removes_the_instant_any_station_is_nok_even_if_others_pending():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=False)  # -> nok
    tracker.mark_pending(slot_id, "s2")  # s2 still pending -- reject must not wait for it

    tracker.transition_reject(slot_id, FakeRejectStation(enabled=True))

    assert tracker.slots[slot_id].status == SlotStatus.EMPTY
    assert tracker.slots[slot_id].assign_part_id is None
    assert tracker.nok_total == 1
    assert tracker.reject_removed == 1


def test_transition_reject_is_noop_when_disabled():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=False)  # -> nok

    tracker.transition_reject(slot_id, FakeRejectStation(enabled=False))

    assert tracker.slots[slot_id].station_states["s1"] == "nok"  # untouched
    assert tracker.slots[slot_id].assign_part_id == 1  # still riding through
    assert tracker.nok_total == 0
    assert tracker.reject_removed == 0


def test_transition_reject_is_noop_while_nothing_nok_yet_even_when_enabled():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=True)
    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=True)

    tracker.transition_reject(slot_id, FakeRejectStation(enabled=True))

    assert tracker.slots[slot_id].assign_part_id == 1  # untouched -- both stations ok
    assert tracker.reject_removed == 0


def test_transition_reject_ignores_nok_at_a_station_not_in_watches():
    # spec11 Part 2: a reject station only acts on the inspection stations
    # it explicitly watches -- s1 failing must not trip a station that only
    # watches s2.
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=False)  # -> nok, but not watched below

    tracker.transition_reject(slot_id, FakeRejectStation(enabled=True, watches=["s2"]))

    assert tracker.slots[slot_id].assign_part_id == 1  # untouched
    assert tracker.reject_removed == 0


def test_transition_reject_fires_on_nok_at_a_watched_station():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=False)

    tracker.transition_reject(slot_id, FakeRejectStation(enabled=True, watches=["s1"]))

    assert tracker.slots[slot_id].assign_part_id is None
    assert tracker.reject_removed == 1


def test_any_watched_station_nok_none_delegates_to_any_station_nok():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=False)

    assert tracker.any_watched_station_nok(slot_id, None) is True
    assert tracker.any_watched_station_nok(slot_id, None) == tracker.any_station_nok(slot_id)


def test_any_watched_station_nok_scoped_to_given_stations_only():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=False)  # only s2 is nok

    assert tracker.any_watched_station_nok(slot_id, ["s1"]) is False
    assert tracker.any_watched_station_nok(slot_id, ["s2"]) is True
    assert tracker.any_watched_station_nok(slot_id, ["s1", "s2"]) is True


def test_transition_exit_ok_bumps_ok_total():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=True)
    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=True)

    tracker.transition_exit(slot_id)

    assert tracker.slots[slot_id].status == SlotStatus.EMPTY
    assert tracker.ok_total == 1
    assert tracker.nok_total == 0


def test_transition_exit_nok_bumps_nok_total_r1_disabled_fallback():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=True)
    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=False)  # r1 disabled, rides through as nok

    tracker.transition_exit(slot_id)

    assert tracker.slots[slot_id].status == SlotStatus.EMPTY
    assert tracker.ok_total == 0
    assert tracker.nok_total == 1


def test_transition_exit_on_unresolved_slot_fails_safe_to_nok():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    # both stations still unreached -- no inference ever landed before exit

    tracker.transition_exit(slot_id)

    assert tracker.slots[slot_id].status == SlotStatus.EMPTY
    assert tracker.nok_total == 1
    assert tracker.ok_total == 0


def test_transition_exit_requires_every_station_ok_not_just_no_nok():
    # A station still "pending" (not "nok") at exit must NOT be treated as
    # a pass -- exit only accepts once EVERY station has actually resolved ok.
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=True)
    tracker.mark_pending(slot_id, "s2")  # s2 never resolves before exit

    tracker.transition_exit(slot_id)

    assert tracker.ok_total == 0
    assert tracker.nok_total == 1


def test_transition_virtual_exit_ok_bumps_ok_total_without_freeing_the_slot():
    # spec11 Part 3: same ok/nok decision as transition_exit, but the part
    # (and its slot) stay permanently -- no free_slot().
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=True)
    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=True)

    tracker.transition_virtual_exit(slot_id)

    assert tracker.ok_total == 1
    assert tracker.nok_total == 0
    assert tracker.slots[slot_id].assign_part_id == 1  # still here
    assert tracker.slots[slot_id].status == SlotStatus.LOADED  # never freed
    assert tracker.slots[slot_id].station_states == {"s1": "unreached", "s2": "unreached"}  # reset for next lap


def test_transition_virtual_exit_nok_bumps_nok_total_without_freeing_the_slot():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=False)
    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=True)

    tracker.transition_virtual_exit(slot_id)

    assert tracker.ok_total == 0
    assert tracker.nok_total == 1
    assert tracker.slots[slot_id].assign_part_id == 1  # still here, not discharged
    assert tracker.slots[slot_id].station_states == {"s1": "unreached", "s2": "unreached"}


def test_transition_virtual_exit_on_unresolved_slot_fails_safe_to_nok():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    # both stations still unreached -- no inference ever landed before virtual exit

    tracker.transition_virtual_exit(slot_id)

    assert tracker.nok_total == 1
    assert tracker.ok_total == 0
    assert tracker.slots[slot_id].assign_part_id == 1  # still here


def test_transition_virtual_exit_resets_for_a_fresh_sweep_next_revolution():
    # Same physical part, laps forever -- confirm a SECOND call (simulating
    # the next revolution's sweep) works from the reset unreached state,
    # not leftover ok/nok from the previous lap.
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=True)
    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=True)
    tracker.transition_virtual_exit(slot_id)  # lap 1: ok

    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=False)  # lap 2: fails this time
    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=True)
    tracker.transition_virtual_exit(slot_id)  # lap 2: nok

    assert tracker.ok_total == 1
    assert tracker.nok_total == 1
    assert tracker.slots[slot_id].assign_part_id == 1  # same part, both laps


def test_free_slot_preserves_blank_and_forced_verdict_across_discharge():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    tracker.seed_sim(blank=0, nok=3)  # slots 0-2 forced NOK, 3-9 forced OK
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)  # slot 0, forced NOK
    assert tracker.slots[slot_id].forced_verdict == "NOK"

    tracker.free_slot(slot_id)

    assert tracker.slots[slot_id].forced_verdict == "NOK"  # preserved
    assert tracker.slots[slot_id].status == SlotStatus.EMPTY
    assert tracker.slots[slot_id].assign_part_id is None


def test_record_camera_result_and_station_aggregate_all_cameras_pass():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)

    assert tracker.station_aggregate(slot_id, "s1:measurement", {"cam1", "cam1b"}, "all_cameras_pass") is None
    tracker.record_camera_result(slot_id, "s1:measurement", "cam1", True)
    assert tracker.station_aggregate(slot_id, "s1:measurement", {"cam1", "cam1b"}, "all_cameras_pass") is None
    tracker.record_camera_result(slot_id, "s1:measurement", "cam1b", True)
    assert tracker.station_aggregate(slot_id, "s1:measurement", {"cam1", "cam1b"}, "all_cameras_pass") is True

    tracker.record_camera_result(slot_id, "s1:measurement", "cam1b", False)
    assert tracker.station_aggregate(slot_id, "s1:measurement", {"cam1", "cam1b"}, "all_cameras_pass") is False


def test_station_aggregate_any_camera_pass():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.record_camera_result(slot_id, "s2:defect", "cam2", False)
    tracker.record_camera_result(slot_id, "s2:defect", "cam2b", True)
    assert tracker.station_aggregate(slot_id, "s2:defect", {"cam2", "cam2b"}, "any_camera_pass") is True
    assert tracker.station_aggregate(slot_id, "s2:defect", {"cam2", "cam2b"}, "all_cameras_pass") is False
