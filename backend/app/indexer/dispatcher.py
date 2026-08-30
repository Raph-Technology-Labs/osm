"""Routes triggers to their cameras. Today's demo wires the "simulation"
source path only (timer-fired, zero PLC dependency -- the guaranteed floor
committed to in plan.txt given the compressed timeline). The "plc"
source path (IndexerSlotTracker-driven self-fire per CLAUDE.md Rule 1) is
sketched but not started here -- tracker.py is built and unit-tested
independently; wiring it into live dispatch is the next step once the floor
demo is solid.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("dispatcher")


class StationDispatcher:
    def __init__(self, resolved_config, station_registry):
        self.resolved_config = resolved_config
        self.station_registry = station_registry
        self._timers: list[threading.Timer] = []
        self._stopped = False

    def start(self) -> None:
        for trig in self.resolved_config.inspection_triggers():
            if trig.source.type == "simulation":
                self._start_simulation_source(trig)
            else:
                log.info(
                    "Trigger %s uses source.type=%r -- not wired for live dispatch in "
                    "this demo build (floor scope is simulation-only, see plan.txt)",
                    trig.id, trig.source.type,
                )

    def _start_simulation_source(self, trig) -> None:
        interval_s = trig.source.sim_interval_ms / 1000

        def fire():
            if self._stopped:
                return
            log.info("Trigger %s fired (simulation, interval=%dms)", trig.id, trig.source.sim_interval_ms)
            self.station_registry.fire_trigger(trig.id)
            t = threading.Timer(interval_s, fire)
            t.daemon = True
            self._timers.append(t)
            t.start()

        t = threading.Timer(interval_s, fire)
        t.daemon = True
        self._timers.append(t)
        t.start()
        log.info("Simulation source started for trigger %s (every %dms)", trig.id, trig.source.sim_interval_ms)

    def stop(self) -> None:
        self._stopped = True
        for t in self._timers:
            t.cancel()
