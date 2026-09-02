"""Integration test: spins up a real PlcSimulator (small encoder_cpr, so
wraparound happens within seconds) and drives it with a real PlcPoller over
localhost TCP -- no mocking of pymodbus."""

import asyncio
import socket

import pytest

from app.plc.poller import PlcPoller, SlotTracker
from app.plc.simulator import PlcSimulator

ENCODER_CPR = 600
N_SLOTS = 10
PULSES_PER_SLOT = ENCODER_CPR // N_SLOTS  # 60
RPM = 60.0  # 1 rev/sec -- several full revolutions well within a 5s test window


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def running_sim():
    port = free_tcp_port()
    sim = PlcSimulator(encoder_cpr=ENCODER_CPR, port=port, tick_hz=50.0)
    await sim.start()
    yield sim, port
    await sim.stop()


async def test_poller_integration(running_sim):
    sim, port = running_sim
    tracker = SlotTracker(pulses_per_slot=PULSES_PER_SLOT, encoder_cpr=ENCODER_CPR)
    poller = PlcPoller(host="127.0.0.1", port=port, slot_tracker=tracker, poll_hz=20.0)

    connected = await poller.connect()
    assert connected
    try:
        await poller.write_speed_setpoint(RPM)

        slots = []
        deadline = asyncio.get_event_loop().time() + 5.0
        poll_interval = 1.0 / poller.poll_hz
        while asyncio.get_event_loop().time() < deadline:
            slots.append(await poller.poll_once())
            await asyncio.sleep(poll_interval)

        assert len(slots) > 0
        # monotonically advances -- the wrap-corrected accumulator never
        # goes backward, even though raw PULSE_COUNT resets every revolution
        for prev, cur in zip(slots, slots[1:]):
            assert cur >= prev

        # at 1 rev/sec over ~5s, at least 2 full revolutions must have
        # elapsed -- each revolution is N_SLOTS slot transitions
        assert slots[-1] >= 2 * N_SLOTS
    finally:
        poller.close()


async def test_poller_raises_on_stalled_heartbeat(running_sim):
    sim, port = running_sim
    tracker = SlotTracker(pulses_per_slot=PULSES_PER_SLOT, encoder_cpr=ENCODER_CPR)
    poller = PlcPoller(host="127.0.0.1", port=port, slot_tracker=tracker, poll_hz=20.0)

    connected = await poller.connect()
    assert connected
    try:
        await poller.write_speed_setpoint(RPM)
        # one live poll to establish a baseline heartbeat
        await poller.poll_once()

        sim.set_frozen(True)  # stop feeding heartbeat updates
        start = asyncio.get_event_loop().time()

        with pytest.raises(TimeoutError):
            while True:
                await poller.poll_once()
                await asyncio.sleep(0.05)

        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed < 1.0  # comfortably bounds the 500ms staleness window
    finally:
        poller.close()
