"""Routes stations to their cameras, driven by ONE shared tick source via
IndexerSlotTracker's ring-math -- not independent per-station timers like
before. This is what CLAUDE.md's own architecture notes flag as still
needed (real PLC-pulse-driven firing is not wired yet): today's simulated
tick (gated by plc.sim.enabled, paced by plc.sim.tick_interval_ms) uses the
exact same tracker-driven model real PLC pulses will use later, differing
only in WHERE pulses come from (a simulated ticker here vs. real Modbus
polling later, both via tracker.on_pulse_update() -- nothing else changes).
Generalizes to any
number of stations, each with any number of cameras, since it only ever
iterates resolved_config.stations and calls station_registry.fire_station(
station_id) (which itself already fires every camera configured under that
station) -- nothing here is hardcoded to today's 2-station/1-camera demo.

Per-tick model, matching docs/specs/09_system_simulator.html's step():
  1. Advance the ring by one slot's worth of pulses (the simulated stand-in
     for a real PULSE_COUNT read).
  2. Periodically assign a new part into the ring at ENTRY (IndexerSlotTracker
     .on_part_entered()) -- gated by entry_interval_ticks so the ring isn't
     100% full end to end, same as the reference file.
  3. For every station, read its current slot_id (IndexerSlotTracker
     .station_slot_id() -- pure ring-math, recomputed every tick per the
     indexer-ring-math skill). Position is unconditional; firing is a
     separate check on whether that slot has an assigned part AND the
     slot_id just changed (a NEW part rotated into position, not the same
     one sitting there across several ticks).
  4. Inspection stations: IndexerSlotTracker.mark_pending() (this
     station's per-station state: unreached -> pending, for this slot's
     current occupant), then fire cameras via the existing
     station_registry.fire_station() path (capture + inference + ZMQ
     publish + DB write -- unchanged, only the trigger condition changed),
     passing slot_id/part_id through so the async inference result can be
     written back onto the right SlotRecord.station_states entry (see
     IndexerSlotTracker.apply_station_result).
  5. Each reject station (zero, one, or more -- spec11 Part 2 added dual
     reject routing): IndexerSlotTracker.transition_reject() -- removes
     the part (free_slot + nok_total++) the instant a station THIS reject
     station watches has reported nok (any_watched_station_nok(); watches
     =None means "watch every inspection station," the original single-
     reject-station behavior), even if others are still unreached/pending;
     a no-op passthrough otherwise (disabled, nothing watched-and-nok yet,
     or the failing station isn't one this particular reject station
     watches) so the part continues on toward the next reject station (if
     any watches its failure) or exit.
  6. The exit station: IndexerSlotTracker.transition_exit() -- frees the
     slot and counts it into ok_total (every station resolved ok) or
     nok_total (anything else -- either no enabled/watching reject station
     caught it, or a station's async result hadn't landed in time, both
     logged distinctly). free_slot() clears assign_part_id, and once the
     ring rotates that same physical index back around to ENTRY, step 2 can
     assign a new part into it again -- this is the actual mechanism by
     which "slots refill after exit" works.

spec12 (pulse-precise reject timing) adds a SECOND, real-hardware tick path
-- _tick_real(), used only when plc.sim.enabled is False. The choice
between the two is made ONCE, in __init__ (self._tick_fn), not checked
per-call -- a single top-level gate, not scattered `if sim.enabled` checks.
_tick_sim() below is byte-for-byte the sim-mode `_tick()` this module had
before spec12 (only renamed) -- deliberately NOT refactored to share code
with _tick_real(), so sim behavior is trivially provable as unchanged
rather than relying on a shared-helper refactor being correct. See
_tick_real()'s own docstring for the real-mode design (real part_sensor
entry detection, pulse-precise reject firing instead of slot-changed
dispatch for the reject station only -- camera/inspection/exit dispatch
stays identical in both modes).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional, Tuple

from app.utils import zeromq

log = logging.getLogger("dispatcher")

MIN_INTERVAL_S = 0.05
# PLACEHOLDER -- a new part enters the ring every N ticks (a real disc
# isn't 100% full end to end). Real cadence depends on the bowl feeder's
# actual part rate, not guessed at here -- matches this file's existing
# convention of flagging unconfirmed physical constants rather than
# inventing them.
ENTRY_INTERVAL_TICKS = 2

# spec12 -- registers.encoder_indexer_ppr (40002, "Reset to 0 at Indexer
# Revolution") is what _tick_real() unwraps for slot/position math. Landed
# on this after ruling out two other registers live, 2026-09-12:
#   1. pulse_count (40001, "Encoder actual pulse") -- assumed to free-run to
#      2**16 before wrapping; wrong (real_accumulated_pulses hit ~262k after
#      barely 1-1.5 real revolutions, every genuine reset unwrapped as a
#      65536-wide wrap, adding ~60,736 phantom pulses each time). Then
#      confirmed it resets at raw≈2400, HALF of encoder_cpr=4800 (it's the
#      raw MOTOR-shaft encoder count, 2:1 gear ratio to the indexer) -- this
#      alone would still have worked with the right wrap width, but...
#   2. encoder_count (40003, sheet-labeled "Total pulses from machine start
#      to stop") -- tried as the "real" per-revolution register instead;
#      turned out to be genuinely monotonic (climbed past 26000 with no
#      reset), and an ordinary 2-count read-noise dip (27703 -> 27701, not a
#      real wrap) got misread as a full revolution reset, injecting a
#      ~4800-pulse phantom jump and firing one reject ~4491 pulses late.
# encoder_indexer_ppr's own sheet label is the direct, literal match for
# what this code needs -- CONFIRMED against real hardware, 2026-09-12, to
# reset once per full indexer revolution, at encoder_cpr (4800), exactly per
# CLAUDE.md Rule 2, with no read-noise false-wrap issue seen. _tick_real()
# below unwraps it against encoder_cpr directly -- see machine_config.yaml's
# register-map comment for the same history.
#
# The wrap-detection's blanket "any decrease means a full revolution
# wrapped" assumption is still a real gap worth hardening someday (it can't
# currently distinguish a genuine wrap from a few counts of read noise --
# e.g. only treat a decrease as a wrap if it's close to a full encoder_cpr's
# worth), but isn't urgent now that the register itself doesn't glitch.


class NoTickSourceConfiguredError(ValueError):
    """Raised when plc.sim.enabled is False and no plc_client was given to
    drive real-hardware polling -- there's nothing to tick from either way.
    Before spec12 this fired unconditionally whenever sim was disabled
    (real dispatch wasn't implemented at all); now real dispatch exists
    (_tick_real()), so this only fires on the genuine misconfiguration of
    disabling sim without providing a plc_client.

    Subclasses ValueError so routers/inspection.py's existing
    `except ValueError -> HTTPException(400)` around start_session() catches
    this for free."""


class StationDispatcher:
    def __init__(self, resolved_config, station_registry, indexer_tracker, plc_client=None):
        self.resolved_config = resolved_config
        self.station_registry = station_registry
        self.tracker = indexer_tracker
        self._stopped = True
        self._timer: Optional[threading.Timer] = None
        self._speed_scale = 1.0
        self._next_part_id = 1
        self._last_slot_ids: Dict[str, int] = {}
        self._ticks_since_entry = 0

        sim_cfg = resolved_config.plc.sim
        if sim_cfg.enabled:
            self._tick_interval_s = sim_cfg.tick_interval_ms / 1000
            self._tick_fn = self._tick_sim
        else:
            if plc_client is None:
                raise NoTickSourceConfiguredError(
                    "StationDispatcher has no tick source: plc.sim.enabled is False "
                    "but no plc_client was given to drive real-hardware polling. Set "
                    "plc.sim.enabled=True to run the dispatcher's own timer tick, or "
                    "pass a connected ModbusPLCClient for real-PLC dispatch."
                )
            self.plc_client = plc_client
            self._tick_interval_s = resolved_config.plc.real_poll_interval_ms / 1000
            self._tick_fn = self._tick_real
            # spec12 real-mode state -- see _tick_real()'s docstring.
            self._real_accumulated_pulses = 0
            self._last_raw_pulse_count: Optional[int] = None
            # None (not False) -- there's no genuine prior reading on the
            # first-ever poll this session, so we can't yet tell a real
            # rising edge from a sensor that just happens to already read
            # HIGH (stuck bit, idle-high default, wiring quirk). Defaulting
            # this to False made the first poll indistinguishable from a
            # real transition -- found via h/w integration testing
            # 2026-09-11: with no part physically present, the first tick
            # still admitted a phantom part AND calibrated home_offset_
            # pulses off that same bogus reading. See _tick_real: None
            # means "establish baseline only, don't treat as an edge,"
            # mirroring how _last_raw_pulse_count's own first sample
            # already means "0 delta, not movement" rather than motion.
            self._last_part_sensor_state: Optional[bool] = None
            # Home calibration (per explicit instruction, 2026-09-11): the
            # raw encoder's own zero (pulse=0 mod encoder_cpr) has no
            # guaranteed relationship to where the presence sensor is
            # physically mounted -- that's just wherever the register last
            # wrapped/was powered on. slot_id math (on_part_entered,
            # tracker.tick()) needs pulse=0 to mean "at the presence
            # sensor," so we capture a one-time offset the first time the
            # sensor fires each session (see _tick_real's calibration
            # check) and shift every downstream pulse read by it via
            # _home_relative_pulses. None means "not yet calibrated this
            # session" -- a fresh StationDispatcher is built on every
            # start_session() call (inspection_session.py), so this
            # naturally recalculates once per new inspection with no
            # separate reset path needed.
            self.home_offset_pulses: Optional[int] = None
            # slot_id -> target_fire_pulse (monotonic space), armed the
            # instant a watched inspection station reports nok for that
            # slot. Deliberately keyed by slot_id ALONE, shared across every
            # reject station (spec11 Part 2 can have more than one) -- a
            # physical slot must only ever be claimed by ONE reject station
            # at a time (once freed, another reject station firing on it
            # would be acting on a phantom/wrong part). _arm_reject_targets'
            # own `if slot_id in self._pending_reject_targets: continue`
            # guard is what enforces that; _tick_real iterates
            # reject_stations() in ring order (sorted by
            # station_offset_pulses) specifically so that if two reject
            # stations' watches ever overlap, the PHYSICALLY-FIRST one
            # always wins the race to claim a slot, never whichever happens
            # to be listed first in the YAML -- see
            # test_dispatcher_real_mode.py's overlapping-watches tests.
            self._pending_reject_targets: Dict[int, int] = {}
            # slot_id -> the RejectStation object that actually armed this
            # target (spec11 Part 2). _fire_crossed_reject_targets() reads
            # this to fire/transition using the SAME station whose
            # .enabled/.watches determined eligibility when it was armed --
            # not whichever reject station's loop iteration happens to
            # notice the crossing, which could be a different one entirely
            # once more than one reject station exists.
            self._pending_reject_armed_by: Dict[int, object] = {}
            # (reject_station_id, slot_id) -> pulse_count_at_detection,
            # recorded once THAT reject station's target for that occupant
            # is found already-passed at arm time (see _arm_reject_targets)
            # so the same occupant isn't re-logged every tick. Keyed
            # per-reject-station (spec11 Part 2), NOT just slot_id: one
            # reject station missing its (earlier) window does not mean a
            # later reject station has also missed its (later) window --
            # each must get its own independent chance. Also keyed by
            # detection pulse (not just slot_id) so a later, different
            # occupant of the same physical slot index is re-evaluated
            # fresh rather than silently staying skipped.
            self._reject_target_skipped: Dict[Tuple[str, int], int] = {}
            # For converting a ms delay into a pulse count at the real,
            # currently-measured rotation rate (never from speed_scale,
            # which only affects _tick_sim -- see _ms_to_pulses()).
            self._last_rate_sample_ts_ms: Optional[float] = None
            self._last_rate_sample_pulses: Optional[int] = None
            self._pulses_per_ms: float = 0.0
            # CLAUDE.md Throughput Design Requirement 1 (Section 5):
            # encoder_indexer_ppr and part_sensor are read every single tick
            # and sit adjacent in the register map (40002/40004 on the
            # current sheet) -- pull both in one
            # read_holding_registers(start, count) round trip instead of two
            # separate ones. Computed once here (not per tick) since the
            # register map never changes after construction; works for
            # either register-number ordering, not just encoder_indexer_ppr <
            # part_sensor, so a future register-map reshuffle doesn't
            # silently break this. encoder_indexer_ppr, NOT pulse_count or
            # encoder_count -- see the module-level comment above this class
            # for why.
            registers = resolved_config.plc.registers
            self._pulse_sensor_read_start = min(registers.encoder_indexer_ppr, registers.part_sensor)
            self._pulse_sensor_read_count = abs(registers.part_sensor - registers.encoder_indexer_ppr) + 1
            self._pulse_offset_in_batch = registers.encoder_indexer_ppr - self._pulse_sensor_read_start
            self._sensor_offset_in_batch = registers.part_sensor - self._pulse_sensor_read_start

    def start(self) -> None:
        """Idempotent -- a no-op if already running. Now that motor start is
        a repeatable manual operator action (not a single call from
        start_session()), calling this while already running must not
        schedule a second concurrent _tick() chain: threading.Timer has no
        built-in "already scheduled" guard, and two interleaved chains would
        silently double the effective tick rate (double pulse increments,
        double entry attempts) with no error to signal it."""
        if not self._stopped:
            return
        self._stopped = False
        self._schedule_tick()
        log.info(
            "Dispatcher started: tick every %.0fms (entry every %d ticks), %d slots",
            self._current_interval_s() * 1000, ENTRY_INTERVAL_TICKS, self.tracker.n_slots,
        )

    def set_speed_scale(self, scale: float) -> None:
        """Takes effect starting from the next scheduled tick (_tick() reads
        the current scale fresh every time it reschedules itself)."""
        self._speed_scale = max(scale, 0.01)
        log.info("Dispatcher speed scale set to %.2fx", self._speed_scale)

    def _current_interval_s(self) -> float:
        return max(self._tick_interval_s / self._speed_scale, MIN_INTERVAL_S)

    def _schedule_tick(self) -> None:
        self._timer = threading.Timer(self._current_interval_s(), self._tick_fn)
        self._timer.daemon = True
        self._timer.start()

    def _tick_sim(self) -> None:
        if self._stopped:
            return

        raw = (self.tracker.current_raw_pulse + self.tracker.pulses_per_slot) % self.tracker.encoder_cpr
        self.tracker.on_pulse_update(raw)

        self._ticks_since_entry += 1
        if self._ticks_since_entry >= ENTRY_INTERVAL_TICKS:
            self._ticks_since_entry = 0
            self._try_assign_entry()

        slot_ids = self.tracker.tick()
        for station in self.resolved_config.stations:
            slot_id = slot_ids.get(station.id)
            if slot_id is None:
                continue
            changed = self._last_slot_ids.get(station.id) != slot_id
            self._last_slot_ids[station.id] = slot_id
            if not changed:
                continue

            record = self.tracker.get_slot(slot_id)
            if record.assign_part_id is None:
                continue  # position is unconditional, actuation isn't -- indexer-ring-math skill

            if station.type == "exit":
                log.info("Part %r reached exit station %s (slot %d)", record.assign_part_id, station.id, slot_id)
                self.tracker.transition_exit(slot_id)
            elif station.type == "virtual_exit":
                # spec11 Part 3 (continuous, no removal) -- same
                # slot-changed dispatch as a real exit station, but never
                # discharges: the part stays on the ring permanently (see
                # transition_virtual_exit's own docstring).
                self.tracker.transition_virtual_exit(slot_id)
            elif station.type == "reject":
                # This per-station loop already naturally handles multiple
                # reject stations (spec11 Part 2) with no restructuring --
                # it fires once per reject-type entry in resolved_config
                # .stations as the ring rotates each one into position, in
                # whatever order they're configured, each independently
                # checking only its own .watches.
                self.tracker.transition_reject(slot_id, station)
            else:
                # Part physically arrived at this inspection station's
                # position -- unreached -> pending, then fire the cameras.
                # mark_pending() before fire_station() so a RingState
                # snapshot published between the two (or a race on the
                # async on_result path) never observes a station that's
                # already "fired" but still shows "unreached". part_id
                # passed through (spec13 #1) so a stale call for a part
                # that's since left this slot is dropped rather than
                # silently overwriting whatever's here now.
                self.tracker.mark_pending(slot_id, station.id, part_id=record.assign_part_id)
                self.station_registry.fire_station(station.id, slot_id=slot_id, part_id=record.assign_part_id)

        zeromq.publish_ring_state(self.tracker, revolutions=self.tracker.revolutions)
        self._schedule_tick()

    def _try_assign_entry(self) -> None:
        entry_pulse = self.tracker.current_raw_pulse
        entry_slot = (entry_pulse // self.tracker.pulses_per_slot) % self.tracker.n_slots
        record = self.tracker.get_slot(entry_slot)
        if record.assign_part_id is not None or record.blank:
            return  # occupied, or permanently unfed (sim seed_sim) -- skip this round, not an error
        part_id = self._next_part_id
        self._next_part_id += 1
        self.tracker.on_part_entered(entry_pulse, part_id)

    def _tick_real(self) -> None:
        """spec12 real-hardware tick: same per-cycle job as _tick_sim (advance
        position, admit new parts at Entry, dispatch stations) but sourced
        from real Modbus reads instead of a synthetic advance. Two behaviors
        differ from sim mode, matching the spec's scope boundary exactly:

        - Entry: a real part_sensor rising-edge (not the fixed-interval
          timer _try_assign_entry() uses).
        - Reject: pulse-precise firing against a computed target_fire_pulse
          (not the slot-changed dispatch inspection/exit stations still use,
          in BOTH modes -- untouched below, same as _tick_sim's).

        Wraparound: encoder_indexer_ppr (NOT pulse_count or encoder_count --
        see the module-level comment above this class) resets to 0 every
        indexer revolution, at encoder_cpr (CLAUDE.md Rule 2, confirmed
        against real hardware 2026-09-12). Unwrapped into self._real_accumulated_pulses, a
        monotonic count that never wraps within a session. Every downstream
        calculation (slot math, entry detection, target_fire_pulse, the
        crossing check) works in that already-unwrapped space with plain
        arithmetic -- this is also how tracker.on_pulse_update()'s own
        revolution-reset assumption (CLAUDE.md Rule 2) is kept satisfied
        without touching it: we feed it the revolution-relative projection
        of our monotonic count (accumulated % encoder_cpr), the same signal
        shape the raw register itself produces.
        """
        if self._stopped:
            return

        registers = self.resolved_config.plc.registers

        # encoder_indexer_ppr + part_sensor in one round trip (CLAUDE.md
        # Throughput Design Requirement 1) -- both are read every tick
        # regardless of ring state, so this is the single biggest fixed
        # per-tick Modbus cost to cut. Span/offsets computed once in
        # __init__, not here.
        pulse_sensor_batch = self.plc_client.read_registers(
            self._pulse_sensor_read_start, self._pulse_sensor_read_count,
        )

        # -- 1. Unwrap the raw (per-revolution-resetting) register into a
        # monotonic count. Wrap point is this dispatcher's own tracker's
        # encoder_cpr -- config-driven per machine (CLAUDE.md Rule 5), never
        # a fixed hardware-register-width constant. NOTE: reads
        # encoder_indexer_ppr (40002), not pulse_count (40001) or
        # encoder_count (40003) -- see the module-level comment above this
        # class for why.
        raw_pulse = pulse_sensor_batch[self._pulse_offset_in_batch]
        if self._last_raw_pulse_count is None:
            gap = 0
        elif raw_pulse < self._last_raw_pulse_count:
            gap = (self.tracker.encoder_cpr - self._last_raw_pulse_count) + raw_pulse
            log.info(
                "encoder_indexer_ppr revolution wrap: last_raw=%d, raw_pulse=%d, "
                "encoder_cpr=%d, computed_gap=%d",
                self._last_raw_pulse_count, raw_pulse, self.tracker.encoder_cpr, gap,
            )
        else:
            gap = raw_pulse - self._last_raw_pulse_count
        log.debug(
            "encoder_indexer_ppr tick: raw_pulse=%d, gap=%d, real_accumulated_pulses=%d",
            raw_pulse, gap, self._real_accumulated_pulses + gap,
        )
        self._real_accumulated_pulses += gap
        self._last_raw_pulse_count = raw_pulse
        self._update_pulse_rate_sample()

        # -- 2. Entry: real part_sensor rising-edge, one-shot latch.
        # ASSUMPTION (explicit instruction, 2026-09-08): part_sensor is a
        # clean one-shot edge, not a noisy level -- no multi-sample
        # debounce. If real hardware turns out to bounce, add confirmation
        # logic here; don't assume it's needed pre-emptively.
        #
        # Home calibration: an incremental encoder has no absolute
        # reference of its own -- pulse=0 is just wherever it happened to
        # be at last power-on/reset, not tied to any physical location.
        # The presence sensor is the only real physical reference we have,
        # so the FIRST edge each session (home_offset_pulses starts None
        # on every freshly-built StationDispatcher -- see __init__) is
        # captured as that reference rather than treated as a normal part
        # detection at some arbitrary pre-existing offset. Every pulse
        # read after this point goes through _home_relative_pulses, never
        # _real_accumulated_pulses directly.
        sensor_state = bool(pulse_sensor_batch[self._sensor_offset_in_batch])
        if self._last_part_sensor_state is None:
            # First-ever poll this session -- establish baseline only, no
            # edge fires. See __init__'s comment: an already-HIGH first
            # reading is indistinguishable from a genuine transition, so
            # treating it as one risks admitting a phantom part and
            # miscalibrating home off a bogus reading with nothing
            # physically at the sensor.
            log.info(
                "part_sensor baseline established: raw_pulse=%d, level=%s "
                "-- no edge/calibration on this first read", raw_pulse, sensor_state,
            )
        elif sensor_state and not self._last_part_sensor_state:
            if self.home_offset_pulses is None:
                self.home_offset_pulses = self._real_accumulated_pulses
                log.info(
                    "Home calibrated at presence sensor: raw_pulse=%d, "
                    "home_offset_pulses=%d", raw_pulse, self.home_offset_pulses,
                )
                zeromq.publish_dispatcher_event(
                    "home_calibrated", raw_pulse=raw_pulse, home_offset_pulses=self.home_offset_pulses,
                )
            self._on_part_sensor_edge(raw_pulse)
        self._last_part_sensor_state = sensor_state

        # Not yet homed this session: there's no physical reference yet (see
        # _home_relative_pulses docstring -- "nothing meaningful has happened
        # yet at that point anyway, no part has reached the ring"). Feeding
        # the tracker/twin raw pre-calibration pulses here was the cause of
        # a real digital-twin desync: the ring would free-run off the raw,
        # arbitrary power-on encoder value for however many ticks preceded
        # the first presence-sensor edge, then visibly jerk/jump the instant
        # home_offset_pulses got set and _home_relative_pulses collapsed to
        # 0 -- indistinguishable, to the frontend's rotation accumulator,
        # from a huge backward spin. Publish the tracker's untouched idle
        # state instead (entry_slot_id=0, 0 revolutions) and wait for homing.
        if self.home_offset_pulses is None:
            zeromq.publish_ring_state(self.tracker, revolutions=self.tracker.revolutions)
            self._schedule_tick()
            return

        # Feed the tracker's existing (revolution-bounded) API so camera/
        # station dispatch below is byte-for-byte the same mechanism as sim
        # mode -- "Do not touch" per spec12. Home-relative, not raw, so
        # entry_slot_id (station dispatch) and on_part_entered's slot_id
        # (above) agree on where slot 0 physically is.
        self.tracker.on_pulse_update(self._home_relative_pulses % self.tracker.encoder_cpr)

        # -- 3. Camera/inspection/exit dispatch: identical slot-changed
        # trigger as _tick_sim, in both modes -- spec12 "Do not touch".
        # Reject stations are handled separately below (pulse-precise).
        slot_ids = self.tracker.tick()
        for station in self.resolved_config.stations:
            if station.type == "reject":
                continue
            slot_id = slot_ids.get(station.id)
            if slot_id is None:
                continue
            changed = self._last_slot_ids.get(station.id) != slot_id
            self._last_slot_ids[station.id] = slot_id
            if not changed:
                continue

            record = self.tracker.get_slot(slot_id)
            if record.assign_part_id is None:
                continue

            if station.type == "exit":
                log.info(
                    "Part %r reached exit station %s (slot %d), home_relative_pulses=%d",
                    record.assign_part_id, station.id, slot_id, self._home_relative_pulses,
                )
                zeromq.publish_dispatcher_event(
                    "exit", station_id=station.id, slot_id=slot_id, part_id=record.assign_part_id,
                    home_relative_pulses=self._home_relative_pulses,
                )
                self._check_exit_ack(registers, slot_id)
                self.tracker.transition_exit(slot_id)
            elif station.type == "virtual_exit":
                log.info(
                    "Part %r reached virtual_exit station %s (slot %d), home_relative_pulses=%d",
                    record.assign_part_id, station.id, slot_id, self._home_relative_pulses,
                )
                zeromq.publish_dispatcher_event(
                    "virtual_exit", station_id=station.id, slot_id=slot_id, part_id=record.assign_part_id,
                    home_relative_pulses=self._home_relative_pulses,
                )
                self.tracker.transition_virtual_exit(slot_id)  # spec11 Part 3 -- see _tick_sim's comment
            else:
                log.info(
                    "Part %r fired at inspection station %s (slot %d), home_relative_pulses=%d",
                    record.assign_part_id, station.id, slot_id, self._home_relative_pulses,
                )
                zeromq.publish_dispatcher_event(
                    "station_fired", station_id=station.id, slot_id=slot_id, part_id=record.assign_part_id,
                    home_relative_pulses=self._home_relative_pulses,
                )
                self.tracker.mark_pending(slot_id, station.id)
                self.station_registry.fire_station(station.id, slot_id=slot_id, part_id=record.assign_part_id)

        # -- 4. Reject: pulse-precise, not slot-changed. reject_stations()
        # is already sorted ring-order (station_offset_pulses ascending) --
        # see its own docstring for why that order matters when two reject
        # stations' watches overlap (spec11 Part 2).
        for reject_station in self.resolved_config.reject_stations():
            if not reject_station.enabled:
                continue
            self._arm_reject_targets(reject_station)
        self._fire_crossed_reject_targets(registers)

        zeromq.publish_ring_state(self.tracker, revolutions=self.tracker.revolutions)
        self._schedule_tick()

    def _update_pulse_rate_sample(self) -> None:
        """Measures the real, currently-observed pulses/ms from consecutive
        ticks -- NOT from speed_scale (that only drives _tick_sim's
        synthetic advance; real mode can't control real RPM, only measure
        it). This is what lets a mid-session RPM change be reflected in
        _ms_to_pulses() without corrupting already-armed reject targets:
        each pending target was computed once, at arm time, from whatever
        rate was current then -- a later rate change only affects targets
        armed after it, never retroactively."""
        now_ms = time.monotonic() * 1000
        if self._last_rate_sample_ts_ms is not None and now_ms > self._last_rate_sample_ts_ms:
            delta_pulses = self._real_accumulated_pulses - self._last_rate_sample_pulses
            delta_ms = now_ms - self._last_rate_sample_ts_ms
            self._pulses_per_ms = delta_pulses / delta_ms
        self._last_rate_sample_ts_ms = now_ms
        self._last_rate_sample_pulses = self._real_accumulated_pulses

    def _ms_to_pulses(self, ms: float) -> int:
        if ms <= 0:
            return 0
        return round(ms * self._pulses_per_ms)

    @property
    def _home_relative_pulses(self) -> int:
        """self._real_accumulated_pulses, shifted so 0 lands at the
        presence sensor's physical position rather than at the encoder's
        own (arbitrary, power-on-dependent) zero. Every real-mode
        consumer of pulse position -- tracker feed, entry slot math,
        reject arm/fire comparisons -- must read through this, never
        _real_accumulated_pulses directly, or home calibration would
        silently apply to only some of them and desync slot math from
        reject timing (they'd be shifted by different amounts). Returns
        the raw accumulator, uncorrected, before the first sensor edge of
        this session calibrates home_offset_pulses (see _tick_real) --
        nothing meaningful has happened yet at that point anyway (no part
        has reached the ring)."""
        if self.home_offset_pulses is None:
            return self._real_accumulated_pulses
        return self._real_accumulated_pulses - self.home_offset_pulses

    def _on_part_sensor_edge(self, raw_pulse: int) -> None:
        pulse_count_at_detection = self._home_relative_pulses
        slot_index = (pulse_count_at_detection // self.tracker.pulses_per_slot) % self.tracker.n_slots
        record = self.tracker.get_slot(slot_index)
        if record.assign_part_id is not None or record.blank:
            log.warning(
                "part_sensor edge at pulse=%d maps to slot %d, which is already "
                "occupied/blank -- dropping this detection (a discharge was missed, "
                "or two parts arrived closer together than one poll interval apart)",
                raw_pulse, slot_index,
            )
            return
        part_id = self._next_part_id
        self._next_part_id += 1
        self.tracker.on_part_entered(pulse_count_at_detection, part_id)
        zeromq.publish_dispatcher_event(
            "part_admitted", slot_id=slot_index, part_id=part_id,
            pulse_count_at_detection=pulse_count_at_detection,
        )

    def _arm_reject_targets(self, reject_station) -> None:
        """Computes target_fire_pulse once per slot, the instant a station
        this reject station watches reports nok for it -- reusing
        tracker's any_watched_station_nok() rather than reimplementing
        that check. Checked every tick across every in-flight slot (not
        just when the reject station's own slot_id changes), since a nok
        can land asynchronously at any point in the rotation, independent
        of ring position.

        Called once per configured, enabled reject station each tick
        (spec11 Part 2), in ring order (_tick_real iterates
        reject_stations(), sorted by station_offset_pulses). The
        `if slot_id in self._pending_reject_targets: continue` guard below
        is a global, cross-reject-station lock on that slot: once ANY
        reject station successfully arms a slot, every other reject
        station's call this tick (and every tick after, until the slot is
        freed) sees it already claimed and skips it outright. Combined
        with ring-order iteration, this guarantees that if two reject
        stations' watches ever overlap in a future config, the
        PHYSICALLY-FIRST eligible one always wins the claim -- never
        whichever happens to run second and would otherwise silently
        overwrite the first one's (earlier, correct) target with its own
        (later) one. See test_dispatcher_real_mode.py's
        test_overlapping_watches_* tests, which exercise this directly
        rather than relying on today's specific station layout never
        overlapping."""
        indexer = self.resolved_config.indexer
        # Ring-wide (not per-station), live-editable directly in
        # machine_config.yaml's plc.sim: block -- per explicit instruction
        # 2026-09-08, trial-and-error'd against real hardware with a
        # stopwatch/scope, no code change needed to retune either value.
        sim_cfg = self.resolved_config.plc.sim
        entry_sensor_response_delay_pulses = self._ms_to_pulses(sim_cfg.entry_sensor_response_delay_ms)
        reject_actuator_response_delay_pulses = self._ms_to_pulses(sim_cfg.reject_actuator_response_delay_ms)

        for slot_id in range(self.tracker.n_slots):
            if slot_id in self._pending_reject_targets:
                continue
            record = self.tracker.get_slot(slot_id)
            if record.assign_part_id is None:
                continue
            if record.pulse_count_at_detection is None:
                continue  # entered before real-mode entry detection was wired up -- can't compute a target
            skip_key = (reject_station.id, slot_id)
            if self._reject_target_skipped.get(skip_key) == record.pulse_count_at_detection:
                continue  # already logged as missed for THIS reject station, this exact occupant -- don't spam every tick
            if not self.tracker.any_watched_station_nok(slot_id, reject_station.watches):
                continue

            corrected_detection = (
                record.pulse_count_at_detection
                - indexer.entry_sensor_mid_offset_pulses
                - entry_sensor_response_delay_pulses
            )
            target_fire_pulse = (
                corrected_detection
                + reject_station.station_offset_pulses
                - reject_actuator_response_delay_pulses
            )

            if target_fire_pulse < self._home_relative_pulses:
                # The nok verdict landed so late the physical part has
                # already passed THIS reject station's nozzle -- arming it
                # now would fire on whatever OTHER part currently sits
                # there, not this one (found in review, 2026-09-08). Don't
                # arm it: firing on the wrong part is worse than not firing
                # at all. This part rides through THIS reject station
                # un-rejected -- a later reject station (spec11 Part 2)
                # that also watches this occupant's failing inspection
                # station still gets its own independent chance (separate
                # skip-tracking, keyed per reject station, see __init__'s
                # comment on _reject_target_skipped), and
                # transition_exit()'s own any_station_nok() fallback still
                # catches it as nok_total at exit either way, same as
                # today's disabled-reject-station commissioning path -- so
                # it's still correctly tallied as NOK, just not physically
                # discarded at this particular station.
                log.error(
                    "reject station %s: target for slot %d (part %r) already passed by "
                    "the time it was armed: target_fire_pulse=%d, current "
                    "accumulated_pulses=%d (%d pulses late) -- nok verdict "
                    "arrived too slowly for pulse-precise rejection; skipping "
                    "fire rather than actuating on whatever part is now at the "
                    "reject nozzle. A later reject station watching the same "
                    "failure (if any) still gets its own chance; otherwise the "
                    "part will still be tallied nok at exit.",
                    reject_station.id, slot_id, record.assign_part_id, target_fire_pulse,
                    self._home_relative_pulses,
                    self._home_relative_pulses - target_fire_pulse,
                )
                self._reject_target_skipped[skip_key] = record.pulse_count_at_detection
                continue

            self._pending_reject_targets[slot_id] = target_fire_pulse
            self._pending_reject_armed_by[slot_id] = reject_station
            log.info(
                "reject station %s ARMED for slot %d (part %r): "
                "pulse_count_at_detection=%d, corrected_detection=%d, "
                "target_fire_pulse=%d, current home_relative_pulses=%d "
                "(%d pulses to go)",
                reject_station.id, slot_id, record.assign_part_id,
                record.pulse_count_at_detection, corrected_detection,
                target_fire_pulse, self._home_relative_pulses,
                target_fire_pulse - self._home_relative_pulses,
            )
            zeromq.publish_dispatcher_event(
                "reject_armed", station_id=reject_station.id, slot_id=slot_id, part_id=record.assign_part_id,
                pulse_count_at_detection=record.pulse_count_at_detection, corrected_detection=corrected_detection,
                target_fire_pulse=target_fire_pulse, home_relative_pulses=self._home_relative_pulses,
            )

    def _fire_crossed_reject_targets(self, registers) -> None:
        """Fires reject_cmd for every pending target the ring has now
        reached or passed. Fire-and-immediately-clear, not hold-then-clear
        (explicit instruction, 2026-09-08): the PLC generates the actual
        pulse width itself, so the PC's job is just to set reject_cmd and
        clear it right back down, not time a hold.

        Called once per tick, after every enabled reject station has had a
        chance to arm (spec11 Part 2) -- NOT once per reject station, since
        this scans the one shared _pending_reject_targets dict regardless.
        Each crossed slot fires/transitions using _pending_reject_armed_by
        [slot_id], the SPECIFIC reject station that armed it, not whichever
        reject station's config happened to be passed in -- using the
        wrong one here would re-check .watches against a station it was
        never armed for and could silently no-op transition_reject() even
        though the physical reject_cmd register was already written,
        leaving a freed-in-the-real-world part still marked in-flight in
        the tracker.

        Register choice (spec14 followup #2 groundwork): armed_by
        .actuator_reg if that reject station set one, else the shared,
        ring-wide RegisterMapConfig.reject_cmd -- correct and intentional
        as the default, since every real machine this app talks to has
        exactly one physical reject actuator today regardless of how many
        logical reject stations spec11 Part 2 lets a config declare.
        Every existing part config omits actuator_reg and keeps writing
        reject_cmd, unchanged."""
        crossed = [
            slot_id for slot_id, target in self._pending_reject_targets.items()
            if self._home_relative_pulses >= target
        ]
        for slot_id in crossed:
            target = self._pending_reject_targets.pop(slot_id)
            armed_by = self._pending_reject_armed_by.pop(slot_id)
            reject_reg = armed_by.actuator_reg if armed_by.actuator_reg is not None else registers.reject_cmd
            self.plc_client.write_register(reject_reg, 1)
            self.plc_client.write_register(reject_reg, 0)
            log.info(
                "reject_cmd fired: station=%s, slot=%d, part=%r, register=%d, "
                "target_fire_pulse=%d, home_relative_pulses=%d (%d pulses late)",
                armed_by.id, slot_id, self.tracker.get_slot(slot_id).assign_part_id, reject_reg,
                target, self._home_relative_pulses, self._home_relative_pulses - target,
            )
            zeromq.publish_dispatcher_event(
                "reject_fired", station_id=armed_by.id, slot_id=slot_id,
                part_id=self.tracker.get_slot(slot_id).assign_part_id, target_fire_pulse=target,
                home_relative_pulses=self._home_relative_pulses,
            )
            self._check_reject_ack(registers, armed_by.id, slot_id)
            self.tracker.transition_reject(slot_id, armed_by)

    def _check_reject_ack(self, registers, station_id: str, slot_id: int) -> None:
        """One-shot presence check, NOT the full CLAUDE.md Rule 4 behavior
        yet (missed REJECT_ACK escalating to STOP_COMMAND needs a
        multi-tick timeout loop -- waiting for the PLC to actually latch
        the ack takes more than one poll interval, so a single read taken
        in the same tick as the write will usually read stale/low even on
        a healthy PLC). This only reads registers.reject_ack once, right
        after firing, and logs whatever it currently reads as -- a
        stepping stone for visibility while that register doesn't exist on
        the instrumentation sheet yet, not a safety interlock. Do not treat
        a False here as a confirmed miss.

        registers.reject_ack is None until a real register number is
        added to machine_config.yaml (CLAUDE.md: ask the instrumentation
        team, don't invent one) -- a no-op until then."""
        reject_ack = getattr(registers, "reject_ack", None)
        if reject_ack is None:
            return
        ack_value = bool(self.plc_client.read_register(reject_ack))
        self.last_reject_ack = ack_value
        log.info(
            "reject_ack read: station=%s, slot=%d, register=%d, ack=%s",
            station_id, slot_id, reject_ack, ack_value,
        )

    def _check_exit_ack(self, registers, slot_id: int) -> None:
        """Same one-shot-presence-check caveat as _check_reject_ack: not
        yet the timeout/escalation behavior CLAUDE.md Rule 4 describes for
        a real _CMD/_ACK pair (missed OK_ACK -> FAULT_STATUS) -- exit today
        has no _CMD register of its own (transition_exit is a pure
        software event, the slot rotating past the exit position), so
        exit_ack, once instrumented, is read as an independent
        confirmation signal rather than a reply to something we wrote.
        registers.exit_ack is None (no-op) until a real register number is
        added -- don't invent one."""
        exit_ack = getattr(registers, "exit_ack", None)
        if exit_ack is None:
            return
        ack_value = bool(self.plc_client.read_register(exit_ack))
        self.last_exit_ack = ack_value
        log.info("exit_ack read: slot=%d, register=%d, ack=%s", slot_id, exit_ack, ack_value)

    def stop(self) -> None:
        """Stops AND drains (spec13 #6, found missing in spec12's code
        review) -- blocks until no more ticks will fire, not just until the
        next-scheduled timer is cancelled. cancel() alone only prevents a
        not-yet-fired timer from running; it does nothing for a tick that's
        already executing on the timer thread at the moment stop() is
        called. That in-flight tick (having already passed its own
        `if self._stopped: return` check) still runs to completion and
        unconditionally schedules one more timer before returning -- but
        THAT tick sees _stopped=True immediately and returns without
        rescheduling again, so the chain always ends within two ticks.
        Joining across both possible timers gives callers (e.g.
        start_session() reseeding IndexerSlotTracker sim state via
        seed_sim(), which is only safe once dispatch has genuinely
        stopped) a real "fully stopped" guarantee."""
        self._stopped = True
        for _ in range(2):
            timer = self._timer
            if timer is None:
                break
            timer.cancel()  # no-op if it's already firing/fired -- cancel() only stops a not-yet-fired timer
            if not timer.is_alive():
                break
            timer.join(timeout=5.0)
