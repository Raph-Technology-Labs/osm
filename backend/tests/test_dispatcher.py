"""StationDispatcher unit tests -- real IndexerSlotTracker (the actual
ring-math, not mocked), a fake station_registry that just records
fire_station() calls, and a lightweight fake resolved_config (dispatcher.py
only ever touches .stations/.inspection_stations(), each station's
.id/.type, and .plc.sim.enabled/.plc.sim.tick_interval_ms, so a full
ResolvedMachineConfig with PLC/pipeline config isn't needed here).

Timing-based (real threading.Timer ticks via time.sleep) -- same pattern
already used successfully in tests/plc/test_watchdog.py tonight, generous
margins to avoid flakiness from thread-scheduling jitter.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List

import pytest

from app.indexer.dispatcher import ENTRY_INTERVAL_TICKS, NoTickSourceConfiguredError, StationDispatcher
from app.indexer.tracker import IndexerSlotTracker


@dataclass
class FakeStation:
    id: str
    type: str = "inspection"
    enabled: bool = True  # only meaningful for type="reject" -- see test_reject_and_sim.py


@dataclass
class FakePlcSim:
    enabled: bool = True
    tick_interval_ms: int = 20


@dataclass
class FakePlc:
    sim: FakePlcSim = field(default_factory=FakePlcSim)


class FakeResolvedConfig:
    def __init__(self, stations: List[FakeStation], tick_interval_ms: int = 20, sim_enabled: bool = True):
        self.stations = stations
        self.plc = FakePlc(sim=FakePlcSim(enabled=sim_enabled, tick_interval_ms=tick_interval_ms))

    def inspection_stations(self):
        return [s for s in self.stations if s.type == "inspection"]


class FakeStationRegistry:
    def __init__(self):
        self.fired: List[str] = []

    def fire_station(self, station_id: str, slot_id=None, part_id=None) -> None:
        self.fired.append(station_id)


def make_dispatcher(n_slots=10, encoder_cpr=100, pulse_offsets: Dict[str, int] = None, tick_ms=20):
    pulse_offsets = pulse_offsets or {"s1": 20, "exit1": 80}
    fake_stations = [
        FakeStation(id=sid, type="exit" if sid.startswith("exit") else "inspection")
        for sid in pulse_offsets
    ]
    config = FakeResolvedConfig(fake_stations, tick_interval_ms=tick_ms)
    inspection_ids = [sid for sid in pulse_offsets if not sid.startswith("exit")]
    tracker = IndexerSlotTracker(
        n_slots=n_slots, encoder_cpr=encoder_cpr, station_pulse_offsets=pulse_offsets,
        inspection_station_ids=inspection_ids,
    )
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


def test_start_is_idempotent():
    # Motor start is now a repeatable manual operator action rather than a
    # single call from session-start -- calling start() while already
    # running must not schedule a second concurrent _tick() chain (which
    # would silently double the effective tick rate).
    dispatcher, tracker, _registry = make_dispatcher(tick_ms=60)
    dispatcher.start()
    dispatcher.start()  # should be a no-op, not a second timer chain
    try:
        wait_ticks(ENTRY_INTERVAL_TICKS * 3, 0.06)  # ~6 ticks -> ~3 entries on a single chain
    finally:
        dispatcher.stop()
    # a doubled chain would produce roughly double this
    assert tracker.entered_count <= 4


def test_stop_prevents_further_ticks():
    dispatcher, _tracker, registry = make_dispatcher(tick_ms=60)
    dispatcher.start()
    time.sleep(0.05)
    dispatcher.stop()
    fired_at_stop = len(registry.fired)
    time.sleep(0.1)
    assert len(registry.fired) == fired_at_stop


def test_stop_blocks_until_an_in_flight_tick_finishes():
    # spec13 #6: stop() must actually drain, not just cancel the
    # not-yet-fired timer -- a tick already executing when stop() is
    # called must finish before stop() returns, so a caller (e.g.
    # start_session() reseeding IndexerSlotTracker sim state) can rely on
    # "stopped" meaning no more ticks will fire. Deterministic via a
    # patched, coordinated slow tick rather than timing/probability.
    dispatcher, _tracker, _registry = make_dispatcher(tick_ms=50)
    tick_started = threading.Event()
    tick_may_finish = threading.Event()
    original_tick = dispatcher._tick_fn

    def slow_tick():
        tick_started.set()
        tick_may_finish.wait(timeout=2)
        original_tick()

    dispatcher._tick_fn = slow_tick
    dispatcher.start()
    assert tick_started.wait(timeout=1), "tick never started"

    stop_thread = threading.Thread(target=dispatcher.stop)
    stop_thread.start()
    time.sleep(0.05)  # stop() should be blocked in join(), waiting on the in-flight tick
    assert stop_thread.is_alive(), "stop() returned before the in-flight tick finished draining"

    tick_may_finish.set()  # let the slow tick complete
    stop_thread.join(timeout=2)
    assert not stop_thread.is_alive(), "stop() never returned after the tick finished"


def test_plc_sim_disabled_raises_instead_of_guessing():
    # plc.sim.enabled=False with no plc_client given -- there's nothing to
    # drive real-hardware polling from (spec12 added real dispatch, but it
    # still needs a connected client), so the dispatcher must refuse to
    # start rather than silently picking a bogus interval (the old
    # per-station-interval fallback's latent bug). See
    # test_dispatcher_real_mode.py for real-mode dispatch with a plc_client.
    pulse_offsets = {"s1": 20, "exit1": 80}
    fake_stations = [
        FakeStation(id="s1", type="inspection"),
        FakeStation(id="exit1", type="exit"),
    ]
    config = FakeResolvedConfig(fake_stations, sim_enabled=False)
    tracker = IndexerSlotTracker(
        n_slots=10, encoder_cpr=100, station_pulse_offsets=pulse_offsets, inspection_station_ids=["s1"],
    )
    registry = FakeStationRegistry()
    with pytest.raises(NoTickSourceConfiguredError):
        StationDispatcher(config, registry, tracker)
