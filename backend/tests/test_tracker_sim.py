"""Pure IndexerSlotTracker unit tests for the per-station slot state
machine, sim seeding, and the reject/exit transitions -- no dispatcher, no
threading timers, just the tracker's own methods called directly.

Matches docs/reference/segment_slot_simulator.html's model: each inspection
station has its own independent unreached/pending/ok/nok state per slot
(mark_pending then apply_station_result), not a single collapsed whole-slot
verdict."""

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


def test_transition_r1_removes_the_instant_any_station_is_nok_even_if_others_pending():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=False)  # -> nok
    tracker.mark_pending(slot_id, "s2")  # s2 still pending -- r1 must not wait for it

    tracker.transition_r1(slot_id, enabled=True)

    assert tracker.slots[slot_id].status == SlotStatus.EMPTY
    assert tracker.slots[slot_id].assign_part_id is None
    assert tracker.nok_total == 1
    assert tracker.r1_removed == 1


def test_transition_r1_is_noop_when_disabled():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=False)  # -> nok

    tracker.transition_r1(slot_id, enabled=False)

    assert tracker.slots[slot_id].station_states["s1"] == "nok"  # untouched
    assert tracker.slots[slot_id].assign_part_id == 1  # still riding through
    assert tracker.nok_total == 0
    assert tracker.r1_removed == 0


def test_transition_r1_is_noop_while_nothing_nok_yet_even_when_enabled():
    tracker = make_tracker(n_slots=10, encoder_cpr=100)
    slot_id = tracker.on_part_entered(entry_pulse=5, part_id=1)
    tracker.mark_pending(slot_id, "s1")
    tracker.apply_station_result(slot_id, "s1", passed=True)
    tracker.mark_pending(slot_id, "s2")
    tracker.apply_station_result(slot_id, "s2", passed=True)

    tracker.transition_r1(slot_id, enabled=True)

    assert tracker.slots[slot_id].assign_part_id == 1  # untouched -- both stations ok
    assert tracker.r1_removed == 0


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
