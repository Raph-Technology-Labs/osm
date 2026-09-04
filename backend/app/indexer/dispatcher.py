"""Routes stations to their cameras. Today's demo wires the "simulation"
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
        for station in self.resolved_config.inspection_stations():
            if station.source.type == "simulation":
                self._start_simulation_source(station)
            else:
                log.info(
                    "Station %s uses source.type=%r -- not wired for live dispatch in "
                    "this demo build (floor scope is simulation-only, see plan.txt)",
                    station.id, station.source.type,
                )

    def _start_simulation_source(self, station) -> None:
        interval_s = station.source.sim_interval_ms / 1000

        def fire():
            if self._stopped:
                return
            log.info("Station %s fired (simulation, interval=%dms)", station.id, station.source.sim_interval_ms)
            self.station_registry.fire_station(station.id)
            t = threading.Timer(interval_s, fire)
            t.daemon = True
            self._timers.append(t)
            t.start()

        t = threading.Timer(interval_s, fire)
        t.daemon = True
        self._timers.append(t)
        t.start()
        log.info("Simulation source started for station %s (every %dms)", station.id, station.source.sim_interval_ms)

    def stop(self) -> None:
        self._stopped = True
        for t in self._timers:
            t.cancel()
