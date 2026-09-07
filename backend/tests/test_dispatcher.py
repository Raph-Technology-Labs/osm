"""StationDispatcher unit tests -- real IndexerSlotTracker (the actual
ring-math, not mocked), a fake station_registry that just records
fire_station() calls, and a lightweight fake resolved_config (dispatcher.py
only ever touches .stations/.inspection_stations() and each station's
.id/.type/.source.type/.source.sim_interval_ms, so a full
ResolvedMachineConfig with PLC/pipeline config isn't needed here).

Timing-based (real threading.Timer ticks via time.sleep) -- same pattern
already used successfully in tests/plc/test_watchdog.py tonight, generous
margins to avoid flakiness from thread-scheduling jitter.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List

from app.indexer.dispatcher import ENTRY_INTERVAL_TICKS, StationDispatcher
from app.indexer.tracker import IndexerSlotTracker


@dataclass
class FakeSource:
    type: str = "simulation"
    sim_interval_ms: int = 20


@dataclass
class FakeStation:
    id: str
    type: str = "inspection"
    source: FakeSource = field(default_factory=FakeSource)


class FakeResolvedConfig:
    def __init__(self, stations: List[FakeStation]):
        self.stations = stations

    def inspection_stations(self):
        return [s for s in self.stations if s.type == "inspection"]


class FakeStationRegistry:
    def __init__(self):
        self.fired: List[str] = []

    def fire_station(self, station_id: str) -> None:
        self.fired.append(station_id)


def make_dispatcher(n_slots=10, encoder_cpr=100, pulse_offsets: Dict[str, int] = None, tick_ms=20):
    pulse_offsets = pulse_offsets or {"s1": 20, "exit1": 80}
    fake_stations = [
        FakeStation(id=sid, type="exit" if sid.startswith("exit") else "inspection", source=FakeSource(sim_interval_ms=tick_ms))
        for sid in pulse_offsets
    ]
    config = FakeResolvedConfig(fake_stations)
    tracker = IndexerSlotTracker(n_slots=n_slots, encoder_cpr=encoder_cpr, station_pulse_offsets=pulse_offsets)
    registry = FakeStationRegistry()
    dispatcher = StationDispatcher(config, registry, tracker)
    return dispatcher, tracker, registry


def wait_ticks(n: int, tick_s: float):
    time.sleep(n * tick_s + tick_s * 2)  # generous margin


def test_entry_assigns_parts_periodically():
    dispatcher, tracker, _registry = make_dispatcher(tick_ms=60)
    dispatcher.start()
    try:
        wait_ticks(ENTRY_INTERVAL_TICKS * 3, 0.06)
    finally:
        dispatcher.stop()
    assert tracker.entered_count >= 2


def test_inspection_station_fires_when_a_part_rotates_into_its_slot():
    # n_slots=10, encoder_cpr=100 -> pulses_per_slot=10; s1 at pulse-offset
    # 20 -> station_offset=2 slots from entry.
    dispatcher, _tracker, registry = make_dispatcher(n_slots=10, encoder_cpr=100, pulse_offsets={"s1": 20, "exit1": 80}, tick_ms=60)
    dispatcher.start()
    try:
        wait_ticks(15, 0.06)  # long enough for a part to enter and reach s1
    finally:
        dispatcher.stop()
    assert "s1" in registry.fired


def test_exit_frees_the_slot_instead_of_firing_cameras():
    dispatcher, tracker, registry = make_dispatcher(n_slots=6, encoder_cpr=60, pulse_offsets={"s1": 10, "exit1": 50}, tick_ms=60)
    dispatcher.start()
    try:
        wait_ticks(20, 0.06)
    finally:
        dispatcher.stop()
    assert "exit1" not in registry.fired  # exit never fires cameras, only frees the slot
    assert tracker.exited_count >= 1


def test_slots_are_reused_after_exit_frees_them():
    dispatcher, tracker, _registry = make_dispatcher(n_slots=4, encoder_cpr=40, pulse_offsets={"exit1": 20}, tick_ms=60)
    dispatcher.start()
    try:
        wait_ticks(24, 0.06)  # several full revolutions
    finally:
        dispatcher.stop()
    # the tracker's own conservation invariant
    assert tracker.entered_count == tracker.exited_count + tracker.in_flight_count
    # proves the same physical slots were actually reused, not just filled once
    assert tracker.entered_count > tracker.n_slots


def test_speed_scale_shortens_the_tick_interval():
    dispatcher, _tracker, _registry = make_dispatcher(tick_ms=100)
    assert dispatcher._current_interval_s() == 0.1
    dispatcher.set_speed_scale(2.0)
    assert dispatcher._current_interval_s() == 0.05


def test_stop_prevents_further_ticks():
    dispatcher, _tracker, registry = make_dispatcher(tick_ms=60)
    dispatcher.start()
    time.sleep(0.05)
    dispatcher.stop()
    fired_at_stop = len(registry.fired)
    time.sleep(0.1)
    assert len(registry.fired) == fired_at_stop


def test_differing_sim_intervals_uses_the_smallest_and_warns(caplog):
    pulse_offsets = {"s1": 10, "s2": 20, "exit1": 80}
    fake_stations = [
        FakeStation(id="s1", type="inspection", source=FakeSource(sim_interval_ms=50)),
        FakeStation(id="s2", type="inspection", source=FakeSource(sim_interval_ms=100)),
        FakeStation(id="exit1", type="exit", source=FakeSource(sim_interval_ms=50)),
    ]
    config = FakeResolvedConfig(fake_stations)
    tracker = IndexerSlotTracker(n_slots=10, encoder_cpr=100, station_pulse_offsets=pulse_offsets)
    registry = FakeStationRegistry()
    with caplog.at_level("WARNING"):
        dispatcher = StationDispatcher(config, registry, tracker)
    assert dispatcher._tick_interval_s == 0.05  # the smaller of 50ms/100ms
    assert any("different sim_interval_ms" in r.message for r in caplog.records)
