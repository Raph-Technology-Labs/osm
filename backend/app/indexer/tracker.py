"""Pure ring-math slot tracker for the rotary indexer.

No hardware I/O here -- app/plc/plc_manager.py feeds on_pulse_update() from
polled PULSE_COUNT reads and on_part_entered() from the entry-queue ring
buffer (see plan.txt section 2); app/indexer/dispatcher.py reads tick() /
station_slot_id() to decide when to fire cameras and rejects. Formulas follow
the project's indexer-ring-math skill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


class SlotCollisionError(RuntimeError):
    """A part entered a slot that's still occupied by a previous part. Under
    correct operation a slot cannot come back around to Entry before its
    prior occupant is discharged (accepted/rejected) -- if this fires, a
    discharge was missed somewhere upstream. Callers (StationDispatcher)
    should treat this as FAULT_STATUS, not swallow it -- silently
    overwriting the slot would corrupt the entered == exited + in_flight
    conservation invariant with no trace of what happened."""


@dataclass
class SlotRecord:
    assign_part_id: Optional[object] = None
    entry_pulse: Optional[int] = None
    results: dict = field(default_factory=dict)


class IndexerSlotTracker:
    def __init__(self, n_slots: int, encoder_cpr: int, station_pulse_offsets: Dict[str, int]):
        if n_slots <= 0:
            raise ValueError(f"n_slots must be positive, got {n_slots}")
        if encoder_cpr % n_slots != 0:
            raise ValueError(
                f"encoder_cpr ({encoder_cpr}) must be evenly divisible by n_slots ({n_slots})"
            )
        self.n_slots = n_slots
        self.encoder_cpr = encoder_cpr
        self.pulses_per_slot = encoder_cpr // n_slots

        # station_offset computed once, in slot units, from each station's
        # pulse distance from Entry -- never recomputed per tick.
        self.station_offsets: Dict[str, int] = {
            station_id: round(pulse_dist / self.pulses_per_slot)
            for station_id, pulse_dist in station_pulse_offsets.items()
        }

        # Fixed-size preallocated slot table -- allocated once, never
        # created/destroyed at runtime (matches indexer_simulation 1.html's
        # "static array" design).
        self.slots: Dict[int, SlotRecord] = {i: SlotRecord() for i in range(n_slots)}

        self._accumulated_pulses = 0
        self._last_raw_pulse = 0
        self._entry_slot_id = 0

        # Bookkeeping for the conservation invariant: entered == exited + in_flight.
        self.entered_count = 0
        self.exited_count = 0

    def on_pulse_update(self, raw_pulse_count: int) -> None:
        """Feed the latest raw PULSE_COUNT register value. Wrap-corrected --
        PULSE_COUNT resets to 0 every revolution, so we never divide the raw
        register directly; we maintain a never-reset internal accumulator."""
        if raw_pulse_count < self._last_raw_pulse:
            gap = (self.encoder_cpr - self._last_raw_pulse) + raw_pulse_count
        else:
            gap = raw_pulse_count - self._last_raw_pulse
        self._accumulated_pulses += gap
        self._last_raw_pulse = raw_pulse_count

    def tick(self) -> Dict[str, int]:
        """Advance the entry pointer from the accumulator and return each
        station's current slot_id. Flags are unconditional -- returned for
        every station regardless of whether a part is present there. Firing
        (camera capture, reject actuation) is a separate check the caller
        (StationDispatcher) makes on slot.assign_part_id is not None."""
        self._entry_slot_id = (self._accumulated_pulses // self.pulses_per_slot) % self.n_slots
        return {station_id: self.station_slot_id(station_id) for station_id in self.station_offsets}

    def station_slot_id(self, station_id: str) -> int:
        offset = self.station_offsets[station_id]
        # Python's % already returns a positive result for negative operands
        # (-1 % 8 == 7) -- exactly the wraparound behavior needed here, so
        # never replace this with a manual sign check.
        return (self._entry_slot_id - offset) % self.n_slots

    def on_part_entered(self, entry_pulse: int, part_id: object) -> int:
        """Called when the entry-queue ring buffer yields an exact captured
        pulse for a newly-arrived part. entry_pulse is the PLC's raw,
        single-revolution captured PULSE_COUNT value (0..encoder_cpr-1) --
        floor-dividing it directly gives the correct physical slot_id with no
        wraparound correction needed, since slot_id is inherently mod n_slots
        regardless of which revolution the part entered on."""
        slot_id = (entry_pulse // self.pulses_per_slot) % self.n_slots
        record = self.slots[slot_id]
        if record.assign_part_id is not None:
            raise SlotCollisionError(
                f"slot {slot_id} still occupied by part {record.assign_part_id!r} "
                f"when part {part_id!r} entered -- a discharge was missed"
            )
        record.assign_part_id = part_id
        record.entry_pulse = entry_pulse
        record.results = {}
        self.entered_count += 1
        return slot_id

    def get_slot(self, slot_id: int) -> SlotRecord:
        return self.slots[slot_id]

    def free_slot(self, slot_id: int) -> None:
        """Called once a part has been accepted or rejected and discharged --
        the slot record resets to empty (never a new object created beyond
        startup, matches the fixed-table design)."""
        record = self.slots[slot_id]
        if record.assign_part_id is not None:
            self.exited_count += 1
        record.assign_part_id = None
        record.entry_pulse = None
        record.results = {}

    @property
    def in_flight_count(self) -> int:
        return sum(1 for s in self.slots.values() if s.assign_part_id is not None)
