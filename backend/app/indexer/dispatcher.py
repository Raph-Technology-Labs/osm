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
"""

from __future__ import annotations

import logging
import threading
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


class NoTickSourceConfiguredError(ValueError):
    """Raised when plc.sim.enabled is False. There is no implemented
    real-PLC-pulse-driven tick source yet (CLAUDE.md: real PLC-pulse-driven
    firing is not wired yet) -- refuse to start rather than silently
    falling back to a guessed interval, which is exactly what the old
    per-station-interval-scanning code's `else 3.0` fallback did (3.0/1000
    = 3ms, not 3s -- a latent bug, never hit because every station used to
    default to type: simulation).

    Subclasses ValueError so routers/inspection.py's existing
    `except ValueError -> HTTPException(400)` around start_session() catches
    this for free."""


class StationDispatcher:
    def __init__(self, resolved_config, station_registry, indexer_tracker):
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
        if not sim_cfg.enabled:
            raise NoTickSourceConfiguredError(
                "StationDispatcher has no tick source: plc.sim.enabled is False and "
                "there is no real-PLC-pulse-driven dispatch wired yet. Set "
                "plc.sim.enabled=True to run the dispatcher's own timer tick, or "
                "wire real PLC-driven dispatch before disabling sim."
            )
        self._tick_interval_s = sim_cfg.tick_interval_ms / 1000

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
        self._timer = threading.Timer(self._current_interval_s(), self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self) -> None:
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
