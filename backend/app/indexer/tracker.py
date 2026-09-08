"""Pure ring-math slot tracker for the rotary indexer.

No hardware I/O here -- app/plc/plc_manager.py feeds on_pulse_update() from
polled PULSE_COUNT reads and on_part_entered() from the entry-queue ring
buffer (see plan.txt section 2); app/indexer/dispatcher.py reads tick() /
station_slot_id() to decide when to fire cameras and rejects. Formulas follow
the project's indexer-ring-math skill.

Slot lifecycle (SlotRecord.status): EMPTY -> LOADED (on_part_entered) ->
EMPTY again (transition_reject or transition_exit, whichever actually
discharges the part). BLANK is a sim-only permanent mark (seed_sim) for a
slot the feeder deterministically never loads -- distinct from a slot that's
merely EMPTY-right-now-but-feedable.

Per-station verdict (SlotRecord.station_states, one entry per INSPECTION
station only -- not entry/reject/exit): unreached -> pending (mark_pending,
called when the dispatcher actually fires that station for this slot) ->
ok/nok (apply_station_result, called once that station's cameras have all
reported back). Each inspection station's state is independent -- a part
can be "ok at s1, still pending at s2" simultaneously; there is no single
whole-slot OK/NOK, only what's derived from station_states:
  - any_station_nok(slot_id) / any_watched_station_nok(slot_id, watches):
    true the instant ANY (or any WATCHED, spec11 Part 2) station reports
    nok, even while others are still unreached/pending -- this is what
    gates a reject station (reject on the first sign of a problem it
    cares about, don't wait for the rest).
  - all_stations_ok(slot_id): true only once EVERY station has resolved ok
    -- this is what gates exit (accept only once everything has cleared).
Matches docs/reference/segment_slot_simulator.html's segState()/allOk()
model exactly.

Two different call contexts mutate this state, concurrently:
  - Synchronous, tick-driven: StationDispatcher's tick thread calls
    on_part_entered/mark_pending/transition_reject/transition_exit/tick
    once per tick.
  - Asynchronous, inference-driven: app/inspection_session.py's per-camera
    on_result callbacks (running in station_registry's background capture
    threads) call record_camera_result/apply_station_result whenever a
    capture finishes, independently of the tick clock. self._lock
    serializes all of the above against each other.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Dict, Optional, Set

log = logging.getLogger("tracker")


class SlotCollisionError(RuntimeError):
    """A part entered a slot that's still occupied by a previous part. Under
    correct operation a slot cannot come back around to Entry before its
    prior occupant is discharged (accepted/rejected) -- if this fires, a
    discharge was missed somewhere upstream. Callers (StationDispatcher)
    should treat this as FAULT_STATUS, not swallow it -- silently
    overwriting the slot would corrupt the entered == exited + in_flight
    conservation invariant with no trace of what happened."""


class BlankSlotEntryError(RuntimeError):
    """A caller tried to assign a part into a slot seed_sim() marked BLANK
    (permanently unfed). The dispatcher must already skip these at Entry
    (tracker.get_slot(slot).blank) -- this is the defensive backstop, not
    the primary guard."""


class SlotStatus(str, Enum):
    EMPTY = "EMPTY"
    LOADED = "LOADED"  # a part is present -- see station_states for per-station detail
    BLANK = "BLANK"  # sim-only: permanently unfed, never EMPTY-and-feedable


# station_states values -- not an Enum since they're plain strings on the
# wire (RingState JSON) and never compared to anything but each other.
STATION_UNREACHED = "unreached"  # the part hasn't physically reached this station's position yet
STATION_PENDING = "pending"  # at/past the station, camera fired, inference result not back yet
STATION_OK = "ok"
STATION_NOK = "nok"


@dataclass
class SlotRecord:
    assign_part_id: Optional[object] = None
    entry_pulse: Optional[int] = None
    # spec12 (pulse-precise reject timing) -- the MONOTONIC, unwrapped pulse
    # count at the instant this occupant was actually detected (real-mode
    # part_sensor rising edge), as opposed to entry_pulse above (a raw,
    # revolution-relative 0..encoder_cpr-1 value, sim mode's only use of
    # entry_pulse). StationDispatcher._arm_reject_targets() subtracts
    # entry_sensor_mid_offset_pulses/entry_sensor_response_delay_ms from
    # this to get the part's true arrival pulse, then projects forward to
    # the reject station. None until real-mode entry detection sets it
    # (sim mode never does -- reject there is slot-changed, not pulse-
    # precise, so this stays None for every sim-mode occupant).
    pulse_count_at_detection: Optional[int] = None
    results: dict = field(default_factory=dict)
    status: SlotStatus = SlotStatus.EMPTY
    # One entry per INSPECTION station (station_id -> STATION_* state) for
    # the CURRENT occupant -- per-part, reset on_part_entered()/free_slot().
    # No entry-level whole-slot OK/NOK is stored; any_station_nok()/
    # all_stations_ok() derive it from this on demand.
    station_states: dict = field(default_factory=dict)
    # Sim-only, set once by seed_sim() and preserved across every
    # entry/discharge cycle for this physical slot index thereafter --
    # unlike `status`, these are NOT reset by free_slot().
    blank: bool = False
    forced_verdict: Optional[str] = None  # "OK" | "NOK" | None (real/hardware mode)


class IndexerSlotTracker:
    def __init__(
        self,
        n_slots: int,
        encoder_cpr: int,
        station_pulse_offsets: Dict[str, int],
        inspection_station_ids: Optional[list] = None,
    ):
        if n_slots <= 0:
            raise ValueError(f"n_slots must be positive, got {n_slots}")
        if encoder_cpr % n_slots != 0:
            raise ValueError(
                f"encoder_cpr ({encoder_cpr}) must be evenly divisible by n_slots ({n_slots})"
            )
        self.n_slots = n_slots
        self.encoder_cpr = encoder_cpr
        self.pulses_per_slot = encoder_cpr // n_slots
        # Which of station_pulse_offsets' keys are INSPECTION-type stations
        # (not entry/reject/exit) -- one radial band per entry here, per
        # slot, in this exact order (config order, never re-sorted). None/
        # [] is valid (a ring with no inspection stations configured --
        # every part is trivially all_stations_ok()).
        self.inspection_station_ids: list = list(inspection_station_ids or [])

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

        # Ring-wide verdict counters (reject/exit discharge bookkeeping --
        # see transition_reject/transition_exit below). reject_removed is a
        # single ring-wide total across every reject station (spec11 Part
        # 2 can have more than one) -- not consumed by any frontend code
        # today (confirmed), so no per-station breakdown was added; a
        # future need for that is a separate, later change.
        self.ok_total = 0
        self.nok_total = 0
        self.reject_removed = 0

        # Serializes tick-driven mutation (dispatcher's tick thread) against
        # inference-driven mutation (station_registry's background capture
        # threads calling back into apply_measurement_result/
        # apply_defect_result/record_camera_result) -- see module docstring.
        self._lock = threading.Lock()

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

    @property
    def current_raw_pulse(self) -> int:
        """Last raw PULSE_COUNT value fed via on_pulse_update() (0..encoder_cpr-1).
        Public accessor so callers (StationDispatcher's simulated tick
        source today, a real Modbus poller later) can read back the
        current position without reaching into a private field."""
        return self._last_raw_pulse

    @property
    def revolutions(self) -> int:
        """True count of full ring rotations, derived from the never-reset
        pulse accumulator -- NOT entered_count // n_slots (that undercounts:
        entered_count only grows when a part is actually assigned, gated by
        ENTRY_INTERVAL_TICKS and by the target slot being free, and never
        counts seed_sim()'s permanently-BLANK slots at all, so it lags the
        ring's real physical rotation badly whenever entry throughput can't
        keep up with tick rate -- e.g. very fast sim ticks). on_pulse_update()
        runs unconditionally every tick regardless of entry/exit throughput,
        so this always matches the ring's actual visual rotation."""
        return self._accumulated_pulses // self.encoder_cpr

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
        with self._lock:
            record = self.slots[slot_id]
            if record.blank:
                raise BlankSlotEntryError(
                    f"slot {slot_id} is marked BLANK (seed_sim) -- the caller must skip "
                    f"blank slots at Entry, not attempt to assign a part into one"
                )
            if record.assign_part_id is not None:
                raise SlotCollisionError(
                    f"slot {slot_id} still occupied by part {record.assign_part_id!r} "
                    f"when part {part_id!r} entered -- a discharge was missed"
                )
            record.assign_part_id = part_id
            record.entry_pulse = entry_pulse
            # In real mode, callers pass the monotonic accumulated pulse
            # count here (see StationDispatcher._on_part_sensor_edge) --
            # the same value that belongs in pulse_count_at_detection.
            # Harmless in sim mode too (entry_pulse there is revolution-
            # relative, but nothing reads pulse_count_at_detection for a
            # sim-mode occupant -- reject is slot-changed, not pulse-precise).
            record.pulse_count_at_detection = entry_pulse
            record.results = {}
            record.station_states = {sid: STATION_UNREACHED for sid in self.inspection_station_ids}
            record.status = SlotStatus.LOADED
            self.entered_count += 1
            return slot_id

    def get_slot(self, slot_id: int) -> SlotRecord:
        """Returns a copy, never the live SlotRecord (spec13 #10, found
        missing in spec12's code review) -- every caller outside this
        module (dispatcher.py, station_registry.py) only ever reads from
        what this returns today (confirmed: none mutate it), but a live
        reference would let a caller bypass self._lock's discipline
        entirely, mutating tracker state from outside every locked method
        above. Internal code must always go through the locked methods
        (mark_pending, apply_station_result, free_slot, ...), never
        get_slot() + mutate. results/station_states are copied too, not
        just the SlotRecord wrapper -- both are mutable dicts that would
        otherwise still be shared with the live record even after a
        shallow copy."""
        with self._lock:
            record = self.slots[slot_id]
            return replace(record, results=dict(record.results), station_states=dict(record.station_states))

    def free_slot(self, slot_id: int) -> None:
        """Called once a part has been accepted or rejected and discharged --
        the slot record resets to empty (never a new object created beyond
        startup, matches the fixed-table design). blank/forced_verdict are
        seed_sim()-set permanent properties of this physical slot index and
        are deliberately NOT reset here -- only the per-part fields are."""
        with self._lock:
            record = self.slots[slot_id]
            if record.assign_part_id is not None:
                self.exited_count += 1
            record.assign_part_id = None
            record.entry_pulse = None
            record.pulse_count_at_detection = None
            record.results = {}
            record.station_states = {}
            record.status = SlotStatus.BLANK if record.blank else SlotStatus.EMPTY

    @property
    def in_flight_count(self) -> int:
        return sum(1 for s in self.slots.values() if s.assign_part_id is not None)

    def seed_sim(self, blank: int, nok: int = 0) -> None:
        """Randomly marks `blank` slot indices BLANK (feeder skips forever
        -- per explicit instruction 2026-09-07, replacing the earlier fixed-
        first-N-indices choice now that the sim harness itself is
        validated). Every other slot gets forced_verdict=None, meaning
        sim_frame_provider() (app/camera/station_registry.py) runs REAL
        defect/measurement inference against it -- no synthetic override.
        Production (app/inspection_session.py) always calls this with
        nok=0: OK/NOK is decided by YOLO/the measurement pipeline against
        the actual sim images (which already include both good and
        defective photos), never forced here.

        `nok` (default 0) exists only for dispatcher/tracker unit tests
        that need a FAST, deterministic NOK without running real inference
        (see test_reject_and_sim.py) -- when nok>0, the first `nok` of the
        non-blank slots get forced_verdict="NOK" and the rest "OK" (the old
        deterministic behavior, preserved for that test-only use case).

        Idempotent/safe to call again with the same counts (e.g. re-seeded
        at both boot and session-start) since it always recomputes from
        scratch over the full fixed-size table; called with DIFFERENT counts
        mid-run would be a config change while parts are in flight, not
        supported -- caller's responsibility to only do this before/between
        sessions."""
        if blank + nok > self.n_slots:
            raise ValueError(
                f"sim blank ({blank}) + nok ({nok}) exceeds n_slots ({self.n_slots})"
            )
        with self._lock:
            blank_indices = set(random.sample(range(self.n_slots), blank)) if blank > 0 else set()
            remaining = [i for i in range(self.n_slots) if i not in blank_indices]
            nok_indices = set(remaining[:nok])
            for i in range(self.n_slots):
                record = self.slots[i]
                if i in blank_indices:
                    record.blank = True
                    record.forced_verdict = None
                    if record.assign_part_id is None:
                        record.status = SlotStatus.BLANK
                else:
                    record.blank = False
                    if i in nok_indices:
                        record.forced_verdict = "NOK"
                    elif nok > 0:
                        record.forced_verdict = "OK"  # test-only deterministic path, see docstring
                    else:
                        record.forced_verdict = None  # let real inference decide
                    if record.assign_part_id is None and record.status == SlotStatus.BLANK:
                        record.status = SlotStatus.EMPTY  # re-seeded with fewer blanks than before

    def record_camera_result(self, slot_id: int, result_key: str, camera_id: str, passed: bool) -> None:
        """Thread-safe -- called from station_registry's background capture
        threads via inspection_session.py's on_result callback. result_key
        is f"{station_id}:defect" or f"{station_id}:measurement" (not the
        bare station_id), so a station that someday configures both a
        defect and a measurement block on the same camera doesn't collide."""
        with self._lock:
            record = self.slots[slot_id]
            record.results.setdefault(result_key, {})[camera_id] = passed

    def station_aggregate(
        self, slot_id: int, result_key: str, expected_cameras: Set[str], pass_if: str
    ) -> Optional[bool]:
        """Returns None while not every camera in expected_cameras has
        reported into result_key yet; once they all have, returns the
        aggregated pass/fail per pass_if ("all_cameras_pass"/
        "any_camera_pass"). Read-only -- callers apply the result via
        apply_station_result."""
        with self._lock:
            reported = self.slots[slot_id].results.get(result_key, {})
            if not expected_cameras.issubset(reported.keys()):
                return None
            values = [reported[c] for c in expected_cameras]
        return all(values) if pass_if == "all_cameras_pass" else any(values)

    def mark_pending(self, slot_id: int, station_id: str, part_id: object = None) -> None:
        """Tick-driven -- called by StationDispatcher._tick() at the exact
        moment it fires that station's cameras for this slot (i.e. the part
        has physically arrived at that station's position). unreached ->
        pending. Guarded to only fire from unreached, since a re-fire on an
        already-pending/resolved station would be a dispatcher bug (the
        edge-triggered "slot_id just changed" guard in _tick() should
        already prevent this), not silently overwritten.

        part_id (optional): when the caller knows which part it fired this
        station for, passing it lets a call for a part that's no longer in
        this slot be dropped outright (see apply_station_result's docstring
        for the full reasoning -- same identity-guard pattern, added here
        for symmetry even though mark_pending's synchronous, tick-driven
        call site is far less exposed to this race in practice). Omitted
        (None) disables the check entirely -- existing callers that don't
        pass it keep today's exact behavior."""
        with self._lock:
            record = self.slots[slot_id]
            if part_id is not None and record.assign_part_id != part_id:
                log.warning(
                    "mark_pending(slot=%d, station=%s, part=%r): slot now holds %r -- "
                    "stale call for a part that's no longer here, dropping",
                    slot_id, station_id, part_id, record.assign_part_id,
                )
                return
            current = record.station_states.get(station_id, STATION_UNREACHED)
            if current != STATION_UNREACHED:
                log.warning(
                    "mark_pending(slot=%d, station=%s): expected unreached, found %s -- "
                    "dispatcher fired this station twice for the same occupant?",
                    slot_id, station_id, current,
                )
            record.station_states[station_id] = STATION_PENDING

    def apply_station_result(self, slot_id: int, station_id: str, passed: bool, part_id: object = None) -> None:
        """Async, inference-driven -- called once station_aggregate() has
        every expected camera's result in for this station. pending ->
        ok/nok. One method for every inspection station (not split by
        measurement vs. defect) -- station_states treats every inspection
        station symmetrically; WHICH pipeline block produced `passed` is
        inspection_session.py's concern, not the tracker's.

        part_id (optional, found missing in spec12's code review): the
        part_id this result was actually captured for, if the caller has
        it (inspection_session.py's on_result closure captures it at
        fire-time). If given and it no longer matches this slot's current
        occupant, the result is stale -- the part it was for already left
        (rejected/exited) and a DIFFERENT part has since rotated into the
        same slot index -- and is dropped before the write, not just
        logged-and-applied. This is a distinct, separate check from the
        state-mismatch one below: a part_id mismatch means "wrong part,"
        drop unconditionally; a state mismatch with a MATCHING part_id
        means "same part, unexpected state" (e.g. a genuine double-fire),
        which still logs and applies exactly as before -- only identity
        mismatches are new grounds for dropping a result. Omitted (None)
        disables the identity check entirely, preserving today's behavior
        for any caller that doesn't pass it."""
        with self._lock:
            record = self.slots[slot_id]
            if part_id is not None and record.assign_part_id != part_id:
                log.warning(
                    "apply_station_result(slot=%d, station=%s, part=%r): slot now holds "
                    "%r -- stale async result for a part that's no longer here, dropping",
                    slot_id, station_id, part_id, record.assign_part_id,
                )
                return
            current = record.station_states.get(station_id, STATION_UNREACHED)
            if current != STATION_PENDING:
                log.warning(
                    "apply_station_result(slot=%d, station=%s): expected pending, found %s -- "
                    "async race (result arrived after the ring moved on) or an out-of-order call",
                    slot_id, station_id, current,
                )
            record.station_states[station_id] = STATION_OK if passed else STATION_NOK

    def any_station_nok(self, slot_id: int) -> bool:
        """True the instant ANY inspection station has reported nok for the
        current occupant, regardless of whether others are still
        unreached/pending -- a real defect doesn't need corroboration from
        the other stations before it's actionable at a reject station."""
        with self._lock:
            return any(v == STATION_NOK for v in self.slots[slot_id].station_states.values())

    def any_watched_station_nok(self, slot_id: int, watches: Optional[list]) -> bool:
        """spec11 Part 2 (dual reject routing) -- like any_station_nok(),
        but scoped to only the given station ids (a reject station's
        RejectStation.watches). watches=None means "watch every inspection
        station," delegating to any_station_nok() so a reject station with
        no watches configured keeps the exact original (pre-Part-2, single-
        reject-station) behavior."""
        if watches is None:
            return self.any_station_nok(slot_id)
        with self._lock:
            states = self.slots[slot_id].station_states
            return any(states.get(sid) == STATION_NOK for sid in watches)

    def all_stations_ok(self, slot_id: int) -> bool:
        """True only once EVERY inspection station has resolved ok. A slot
        with zero inspection stations configured is trivially all-ok."""
        with self._lock:
            states = self.slots[slot_id].station_states.values()
            return all(v == STATION_OK for v in states)

    def transition_reject(self, slot_id: int, reject_station) -> None:
        """Tick-driven (called from StationDispatcher._tick, synchronous
        with the ring clock -- NOT from an async on_result callback).
        No-op unless reject_station.enabled and
        any_watched_station_nok(reject_station.watches): a disabled reject
        station lets NOK parts ride through untouched (commissioning mode,
        no actuator wired), and a part failing a station this particular
        reject station doesn't watch also rides through it untouched --
        caught by a later reject station that does watch it (spec11 Part
        2), or falls through to Exit's own any_station_nok() fallback if
        none does. reject_station is a RejectStation config object (needs
        only .enabled/.watches), not just an id, so callers don't need a
        separate station lookup."""
        if not reject_station.enabled or not self.any_watched_station_nok(slot_id, reject_station.watches):
            return
        self.free_slot(slot_id)
        with self._lock:
            self.nok_total += 1
            self.reject_removed += 1

    def transition_exit(self, slot_id: int) -> None:
        """Tick-driven. all_stations_ok() -> freed, ok_total+=1. Otherwise
        -> freed, nok_total+=1 -- covers two distinct cases, logged
        differently: (a) every reject station that could have caught this
        is disabled, or none of them watches whatever station actually
        went nok, and any_station_nok() is true (the expected fallback-
        resolution path), or (b) some station is still unreached/pending
        when the part physically reached exit (the async race this
        codebase already flags elsewhere as a known, narrow-window
        limitation) -- fails SAFE to NOK per CLAUDE.md Section 15
        ("defaults to NOK, fail-safe not fail-open") rather than silently
        let an unresolved part through as OK."""
        if self.all_stations_ok(slot_id):
            self.free_slot(slot_id)
            with self._lock:
                self.ok_total += 1
            return

        if self.any_station_nok(slot_id):
            log.info("transition_exit(slot=%d): NOK (no enabled/watching reject station caught it)", slot_id)
        else:
            with self._lock:
                unresolved = {
                    sid: st for sid, st in self.slots[slot_id].station_states.items() if st != STATION_OK
                }
            log.error(
                "transition_exit(slot=%d): part reached exit with unresolved station(s) %s "
                "-- inference result hadn't landed in time; failing safe to NOK",
                slot_id, unresolved,
            )
        self.free_slot(slot_id)
        with self._lock:
            self.nok_total += 1

    def transition_virtual_exit(self, slot_id: int) -> None:
        """spec11 Part 3 (continuous, no removal) -- tick-driven, fired by
        a type: virtual_exit station exactly like transition_exit() is
        fired by type: exit. Reuses transition_exit's exact ok/nok
        decision (all_stations_ok() -> ok_total++, anything else ->
        nok_total++), including the same fail-safe-to-NOK-on-unresolved
        philosophy (CLAUDE.md Section 15), but does NOT call free_slot():
        assign_part_id and the part stay on the ring permanently -- there
        is nothing to discharge here, unlike a real exit. Instead,
        station_states resets to unreached (not assign_part_id) so the
        digital twin shows a fresh pending->resolved sweep next
        revolution -- same physical part, same eventual result (driven by
        the sim harness's forced_verdict, which free_slot() would have
        preserved anyway), every lap."""
        all_ok = self.all_stations_ok(slot_id)
        if not all_ok and not self.any_station_nok(slot_id):
            with self._lock:
                unresolved = {
                    sid: st for sid, st in self.slots[slot_id].station_states.items() if st != STATION_OK
                }
            log.error(
                "transition_virtual_exit(slot=%d): part reached virtual exit with "
                "unresolved station(s) %s -- inference result hadn't landed in "
                "time; failing safe to NOK",
                slot_id, unresolved,
            )
        with self._lock:
            if all_ok:
                self.ok_total += 1
            else:
                self.nok_total += 1
            record = self.slots[slot_id]
            record.station_states = {sid: STATION_UNREACHED for sid in self.inspection_station_ids}
