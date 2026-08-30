"""Pure ring-math unit tests for IndexerSlotTracker. No hardware/PLC needed."""

import pytest

from app.indexer.tracker import IndexerSlotTracker, SlotCollisionError


def make_tracker(n_slots=20, encoder_cpr=3600, offsets=None):
    return IndexerSlotTracker(
        n_slots=n_slots,
        encoder_cpr=encoder_cpr,
        station_pulse_offsets=offsets or {"cam1": 540, "r1": 900},  # 3 and 5 slots out
    )


def test_rejects_non_divisible_cpr():
    with pytest.raises(ValueError):
        IndexerSlotTracker(n_slots=7, encoder_cpr=100, station_pulse_offsets={})


def test_station_offsets_computed_in_slot_units():
    t = make_tracker()
    assert t.pulses_per_slot == 180  # 3600 / 20
    assert t.station_offsets["cam1"] == 3  # 540 / 180
    assert t.station_offsets["r1"] == 5  # 900 / 180


def test_pulse_accumulator_no_wrap():
    t = make_tracker()
    t.on_pulse_update(100)
    t.on_pulse_update(300)
    assert t._accumulated_pulses == 300


def test_pulse_accumulator_wrap_correction():
    """PULSE_COUNT resets to 0 every revolution -- the accumulator must keep
    climbing across the wrap, never go backward."""
    t = make_tracker(encoder_cpr=3600)
    t.on_pulse_update(3550)
    assert t._accumulated_pulses == 3550
    t.on_pulse_update(3590)
    assert t._accumulated_pulses == 3590
    t.on_pulse_update(20)  # wrapped: PLC reset to 0 and counted up to 20
    # gap = (3600 - 3590) + 20 = 30 -> accumulator = 3590 + 30 = 3620
    assert t._accumulated_pulses == 3620
    t.on_pulse_update(60)
    assert t._accumulated_pulses == 3660


def test_station_slot_id_wraps_correctly_when_offset_exceeds_entry():
    """entry_slot_id - offset can go negative; must wrap via % (Python's
    modulo), never a manual sign check."""
    t = make_tracker(n_slots=20)
    t.on_pulse_update(180)  # exactly 1 slot in -> entry_slot_id = 1
    t.tick()
    assert t._entry_slot_id == 1
    # station "r1" has offset 5 slots; 1 - 5 = -4 -> should wrap to 16
    assert t.station_slot_id("r1") == 16


def test_tick_flags_unconditional_even_when_slot_empty():
    """Flags are returned for every station regardless of whether a part
    occupies that slot -- firing is a separate assign_part_id check made by
    the dispatcher, not folded into tick()."""
    t = make_tracker()
    t.on_pulse_update(360)  # 2 slots in
    flags = t.tick()
    assert set(flags.keys()) == {"cam1", "r1"}
    # no parts have been entered anywhere -- flags still present, just empty slots
    for station_id, slot_id in flags.items():
        assert t.get_slot(slot_id).assign_part_id is None


def test_on_part_entered_matches_tick_derived_slot_id():
    """A part captured at exactly the entry pulse the accumulator has also
    reached must land in the same slot tick() would compute -- the two must
    agree, since they're mathematically the same formula (see tracker.py's
    docstring on on_part_entered)."""
    t = make_tracker(n_slots=20, encoder_cpr=3600)
    t.on_pulse_update(900)  # 5 slots in
    t.tick()
    entry_slot_from_tick = t._entry_slot_id
    slot_id = t.on_part_entered(entry_pulse=900, part_id="P1")
    assert slot_id == entry_slot_from_tick
    assert t.get_slot(slot_id).assign_part_id == "P1"


def test_on_part_entered_slot_id_consistent_across_revolutions():
    """The same raw pulse value on a later revolution must land in the same
    physical slot -- slot_id is mod n_slots, independent of revolution."""
    t = make_tracker(n_slots=20, encoder_cpr=3600)
    slot_a = t.on_part_entered(entry_pulse=900, part_id="A")
    t.free_slot(slot_a)  # discharge A before B enters the same physical slot
    slot_b = t.on_part_entered(entry_pulse=900 + 3600, part_id="B")  # would be invalid
    # raw captured pulses are always 0..cpr-1 in practice; this just proves
    # the formula itself is mod-n_slots-safe if ever handed an out-of-range value
    assert slot_a == slot_b == 5


def test_conservation_invariant_across_entries_and_frees():
    """entered == exited + in_flight at every step -- no part silently
    appears or vanishes from the tracker's bookkeeping."""
    t = make_tracker(n_slots=20, encoder_cpr=3600)
    for i, pulse in enumerate([0, 180, 360, 540, 720]):
        t.on_part_entered(entry_pulse=pulse, part_id=f"P{i}")
        assert t.entered_count == t.exited_count + t.in_flight_count

    t.free_slot(0)
    t.free_slot(1)
    assert t.entered_count == t.exited_count + t.in_flight_count
    assert t.exited_count == 2
    assert t.in_flight_count == 3
    assert t.entered_count == 5


def test_on_part_entered_raises_on_occupied_slot_instead_of_silent_overwrite():
    """A part should never re-enter a slot that's still occupied -- that
    means a discharge was missed upstream. Must raise, not silently
    overwrite (which would corrupt the conservation invariant with no
    trace)."""
    t = make_tracker(n_slots=20, encoder_cpr=3600)
    t.on_part_entered(entry_pulse=900, part_id="A")  # slot 5
    with pytest.raises(SlotCollisionError):
        t.on_part_entered(entry_pulse=900, part_id="B")  # same slot 5, still occupied
    # original occupant must be untouched
    assert t.get_slot(5).assign_part_id == "A"
    assert t.entered_count == 1  # B's entry must not have been counted


def test_free_slot_on_already_empty_slot_does_not_double_count():
    t = make_tracker()
    t.on_part_entered(entry_pulse=0, part_id="A")
    t.free_slot(0)
    assert t.exited_count == 1
    t.free_slot(0)  # freeing an already-empty slot must not increment exited_count again
    assert t.exited_count == 1
