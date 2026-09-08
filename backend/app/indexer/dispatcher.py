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
  5. The reject station (r1, if configured): IndexerSlotTracker
     .transition_r1() -- removes the part (free_slot + nok_total++) the
     instant ANY inspection station has reported nok, even if others are
     still unreached/pending; a no-op passthrough otherwise (disabled, or
     nothing nok yet) so the part continues to exit.
  6. The exit station: IndexerSlotTracker.transition_exit() -- frees the
     slot and counts it into ok_total (every station resolved ok) or
     nok_total (anything else -- either r1 disabled and a nok slipped
     through, or a station's async result hadn't landed in time, both
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
from typing import Dict, Optional

from app.utils import zeromq

log = logging.getLogger("dispatcher")

MIN_INTERVAL_S = 0.05
# PLACEHOLDER -- a new part enters the ring every N ticks (a real disc
# isn't 100% full end to end). Real cadence depends on the bowl feeder's
# actual part rate, not guessed at here -- matches this file's existing
# convention of flagging unconfirmed physical constants rather than
# inventing them.
ENTRY_INTERVAL_TICKS = 2

# spec12 -- pulse_count (40001) is read as a single Modbus holding register
# (app/plc/poller.py reads it with count=1), so ASSUMED to wrap at 2**16 as
# a plain uint16. Flagged assumption, not confirmed with instrumentation --
# only matters at the raw-register-unwrap step in _tick_real(); everything
# downstream (slot math, target_fire_pulse, the crossing check) works in
# the already-unwrapped monotonic pulse space and never uses this directly.
PULSE_COUNT_REGISTER_WRAP = 1 << 16


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
            self._last_part_sensor_state = False
            # slot_id -> target_fire_pulse (monotonic space), armed the
            # instant any inspection station reports nok for that slot.
            self._pending_reject_targets: Dict[int, int] = {}
            # slot_id -> pulse_count_at_detection, recorded once a slot's
            # reject target is found already-passed at arm time (see
            # _arm_reject_targets) so the same occupant isn't re-logged
            # every tick -- keyed by detection pulse, not just slot_id, so
            # a later, different occupant of the same physical slot index
            # is re-evaluated fresh rather than silently staying skipped.
            self._reject_target_skipped: Dict[int, int] = {}
            # For converting a ms delay into a pulse count at the real,
            # currently-measured rotation rate (never from speed_scale,
            # which only affects _tick_sim -- see _ms_to_pulses()).
            self._last_rate_sample_ts_ms: Optional[float] = None
            self._last_rate_sample_pulses: Optional[int] = None
            self._pulses_per_ms: float = 0.0

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
            elif station.type == "reject":
                self.tracker.transition_r1(slot_id, enabled=station.enabled)
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

        Wraparound: pulse_count is read as a raw, wrapping hardware register
        (PULSE_COUNT_REGISTER_WRAP) and unwrapped ONCE into
        self._real_accumulated_pulses, a monotonic count that never wraps
        within a session. Every downstream calculation (slot math, entry
        detection, target_fire_pulse, the crossing check) works in that
        already-unwrapped space with plain arithmetic -- this is also how
        tracker.on_pulse_update()'s own revolution-reset assumption (CLAUDE.md
        Rule 2) is kept satisfied without touching it: we feed it the
        revolution-relative projection of our monotonic count
        (accumulated % encoder_cpr), which looks exactly like the
        resets-every-revolution signal it already expects, regardless of
        whether the real register itself resets or free-runs.
        """
        if self._stopped:
            return

        registers = self.resolved_config.plc.registers

        # -- 1. Unwrap the raw (wrapping) register into a monotonic count.
        raw_pulse = self.plc_client.read_register(registers.pulse_count)
        if self._last_raw_pulse_count is None:
            gap = 0
        elif raw_pulse < self._last_raw_pulse_count:
            gap = (PULSE_COUNT_REGISTER_WRAP - self._last_raw_pulse_count) + raw_pulse
        else:
            gap = raw_pulse - self._last_raw_pulse_count
        self._real_accumulated_pulses += gap
        self._last_raw_pulse_count = raw_pulse
        self._update_pulse_rate_sample()

        # Feed the tracker's existing (revolution-bounded) API so camera/
        # station dispatch below is byte-for-byte the same mechanism as sim
        # mode -- "Do not touch" per spec12.
        self.tracker.on_pulse_update(self._real_accumulated_pulses % self.tracker.encoder_cpr)

        # -- 2. Entry: real part_sensor rising-edge, one-shot latch.
        # ASSUMPTION (explicit instruction, 2026-09-08): part_sensor is a
        # clean one-shot edge, not a noisy level -- no multi-sample
        # debounce. If real hardware turns out to bounce, add confirmation
        # logic here; don't assume it's needed pre-emptively.
        sensor_state = bool(self.plc_client.read_register(registers.part_sensor))
        if sensor_state and not self._last_part_sensor_state:
            self._on_part_sensor_edge(raw_pulse)
        self._last_part_sensor_state = sensor_state

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
                log.info("Part %r reached exit station %s (slot %d)", record.assign_part_id, station.id, slot_id)
                self.tracker.transition_exit(slot_id)
            else:
                self.tracker.mark_pending(slot_id, station.id)
                self.station_registry.fire_station(station.id, slot_id=slot_id, part_id=record.assign_part_id)

        # -- 4. Reject: pulse-precise, not slot-changed.
        reject_station = self.resolved_config.reject_station()
        if reject_station is not None and reject_station.enabled:
            self._arm_reject_targets(reject_station)
            self._fire_crossed_reject_targets(reject_station, registers)

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

    def _on_part_sensor_edge(self, raw_pulse: int) -> None:
        pulse_count_at_detection = self._real_accumulated_pulses
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

    def _arm_reject_targets(self, reject_station) -> None:
        """Computes target_fire_pulse once per slot, the instant any
        inspection station reports nok for it -- reusing tracker's existing
        any_station_nok() rather than reimplementing that check. Checked
        every tick across every in-flight slot (not just when the reject
        station's own slot_id changes), since a nok can land asynchronously
        at any point in the rotation, independent of ring position."""
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
            if self._reject_target_skipped.get(slot_id) == record.pulse_count_at_detection:
                continue  # already logged as missed for this exact occupant -- don't spam every tick
            if not self.tracker.any_station_nok(slot_id):
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

            if target_fire_pulse < self._real_accumulated_pulses:
                # The nok verdict landed so late the physical part has
                # already passed the reject nozzle -- arming this target
                # now would fire on whatever OTHER part currently sits at
                # the nozzle, not this one (found in review, 2026-09-08).
                # Don't arm it: firing on the wrong part is worse than not
                # firing at all. This part rides through un-rejected --
                # transition_exit()'s own any_station_nok() fallback still
                # catches it as nok_total at exit, same as today's
                # r1-disabled commissioning path, so it's still correctly
                # tallied as NOK, just not physically discarded.
                log.error(
                    "reject target for slot %d (part %r) already passed by the "
                    "time it was armed: target_fire_pulse=%d, current "
                    "accumulated_pulses=%d (%d pulses late) -- nok verdict "
                    "arrived too slowly for pulse-precise rejection; skipping "
                    "fire rather than actuating on whatever part is now at the "
                    "reject nozzle. Part will still be tallied nok at exit.",
                    slot_id, record.assign_part_id, target_fire_pulse,
                    self._real_accumulated_pulses,
                    self._real_accumulated_pulses - target_fire_pulse,
                )
                self._reject_target_skipped[slot_id] = record.pulse_count_at_detection
                continue

            self._pending_reject_targets[slot_id] = target_fire_pulse

    def _fire_crossed_reject_targets(self, reject_station, registers) -> None:
        """Fires reject_cmd for every pending target the ring has now
        reached or passed. Fire-and-immediately-clear, not hold-then-clear
        (explicit instruction, 2026-09-08): the PLC generates the actual
        pulse width itself, so the PC's job is just to set reject_cmd and
        clear it right back down, not time a hold."""
        crossed = [
            slot_id for slot_id, target in self._pending_reject_targets.items()
            if self._real_accumulated_pulses >= target
        ]
        for slot_id in crossed:
            del self._pending_reject_targets[slot_id]
            self.plc_client.write_register(registers.reject_cmd, 1)
            self.plc_client.write_register(registers.reject_cmd, 0)
            # spec11 hasn't landed (paused, nothing implemented) -- this is
            # the correct current method name. Flag: if spec11's later
            # transition_r1 -> transition_reject(slot_id, reject_station)
            # rename lands, this call site needs updating too.
            self.tracker.transition_r1(slot_id, enabled=reject_station.enabled)

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
