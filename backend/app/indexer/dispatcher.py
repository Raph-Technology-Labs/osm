"""Routes stations to their cameras, driven by ONE shared tick source via
IndexerSlotTracker's ring-math -- not independent per-station timers like
before. This is what CLAUDE.md's own architecture notes flag as still
needed ("PLC-driven source.type: plc firing is not wired yet"): today's
simulation source now uses the exact same tracker-driven model real PLC
pulses will use later, differing only in WHERE pulses come from (a
simulated ticker here vs. real Modbus polling later, both via
tracker.on_pulse_update() -- nothing else changes). Generalizes to any
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
  4. Inspection stations: fire their cameras via the existing
     station_registry.fire_station() path (capture + inference + ZMQ
     publish + DB write -- unchanged, only the trigger condition changed).
  5. The exit station: free the slot (IndexerSlotTracker.free_slot()) --
     this is the actual mechanism by which "slots refill after exit" works:
     free_slot() clears assign_part_id, and once the ring rotates that same
     physical index back around to ENTRY, step 2 can assign a new part into
     it again. Aggregated pass/fail-at-exit is intentionally NOT built here
     yet -- inference completes asynchronously (a separate thread, on its
     own schedule) after a station fires, so evaluating a verdict exactly
     at the exit tick would race against inference still running; this
     build has no reject station either (machine_config.yaml has none
     configured). Scoped out deliberately, not silently skipped.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

log = logging.getLogger("dispatcher")

MIN_INTERVAL_S = 0.05
# PLACEHOLDER -- a new part enters the ring every N ticks (a real disc
# isn't 100% full end to end). Real cadence depends on the bowl feeder's
# actual part rate, not guessed at here -- matches this file's existing
# convention of flagging unconfirmed physical constants rather than
# inventing them.
ENTRY_INTERVAL_TICKS = 2


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

        sim_stations = [s for s in resolved_config.inspection_stations() if s.source.type == "simulation"]
        intervals = {s.source.sim_interval_ms for s in sim_stations}
        if len(intervals) > 1:
            log.warning(
                "Stations configured with different sim_interval_ms values (%s) -- "
                "dispatch is now driven by one shared tick (using the smallest of "
                "them), not independent per-station timers. Physically every "
                "station sees the same ring rotation speed, so per-station "
                "sim_interval_ms was already a config-schema smell; flagging "
                "rather than silently picking one and moving on.",
                sorted(intervals),
            )
        self._tick_interval_s = (min(intervals) if intervals else 3.0) / 1000

    def start(self) -> None:
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
                log.info("Part %r reached exit station %s (slot %d) -- freed", record.assign_part_id, station.id, slot_id)
                self.tracker.free_slot(slot_id)
            else:
                self.station_registry.fire_station(station.id)

        self._schedule_tick()

    def _try_assign_entry(self) -> None:
        entry_pulse = self.tracker.current_raw_pulse
        entry_slot = (entry_pulse // self.tracker.pulses_per_slot) % self.tracker.n_slots
        if self.tracker.get_slot(entry_slot).assign_part_id is not None:
            return  # still occupied -- skip this round rather than raise SlotCollisionError
        part_id = self._next_part_id
        self._next_part_id += 1
        self.tracker.on_part_entered(entry_pulse, part_id)

    def stop(self) -> None:
        self._stopped = True
        if self._timer:
            self._timer.cancel()
