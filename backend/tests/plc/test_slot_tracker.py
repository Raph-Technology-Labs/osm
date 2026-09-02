"""Pure ring-math unit tests for SlotTracker. No I/O, no PLC needed."""

import pytest

from app.plc.poller import SlotTracker


def make_tracker(pulses_per_slot=100, encoder_cpr=6000):
    return SlotTracker(pulses_per_slot=pulses_per_slot, encoder_cpr=encoder_cpr)


def test_slot_tracker_no_wrap():
    tracker = make_tracker(pulses_per_slot=100, encoder_cpr=6000)

    assert tracker.update(0) == 0
    assert tracker.update(50) == 0
    assert tracker.update(100) == 1
    assert tracker.update(250) == 2
    assert tracker.update(999) == 9
    assert tracker.update(1000) == 10


def test_slot_tracker_handles_wrap():
    tracker = make_tracker(pulses_per_slot=100, encoder_cpr=6000)

    assert tracker.update(0) == 0  # establish baseline
    assert tracker.update(5990) == 59
    # wraps: gap should be (6000 - 5990) + 20 = 30, not a reset to slot 0
    slot = tracker.update(20)
    assert slot == 60
    # keep accumulating correctly after the wrap
    assert tracker.update(120) == 61
    assert tracker.update(220) == 62


def test_slot_tracker_handles_multiple_wraps():
    tracker = make_tracker(pulses_per_slot=100, encoder_cpr=1000)

    total_pulses = 0
    raw = 0
    assert tracker.update(raw) == 0  # establish baseline
    for _ in range(25):  # more than one full revolution (1000 pulses) worth
        prev_raw = raw
        raw = (raw + 137) % 1000
        if raw < prev_raw:
            gap = (1000 - prev_raw) + raw
        else:
            gap = raw - prev_raw
        total_pulses += gap
        slot = tracker.update(raw)
        assert slot == total_pulses // 100


def test_slot_boundary_detection():
    tracker = make_tracker(pulses_per_slot=100, encoder_cpr=6000)

    prev_slot = tracker.update(0)
    # several polls within the same slot -- boundary must not fire each tick
    for raw in (10, 30, 60, 90):
        new_slot = tracker.update(raw)
        assert SlotTracker.slot_boundary_crossed(prev_slot, new_slot) is False
        prev_slot = new_slot

    # crossing into the next slot fires exactly once
    new_slot = tracker.update(100)
    assert SlotTracker.slot_boundary_crossed(prev_slot, new_slot) is True
    prev_slot = new_slot

    # staying within the new slot doesn't re-fire
    new_slot = tracker.update(150)
    assert SlotTracker.slot_boundary_crossed(prev_slot, new_slot) is False


def test_rejects_non_positive_pulses_per_slot():
    with pytest.raises(ValueError):
        SlotTracker(pulses_per_slot=0, encoder_cpr=6000)
