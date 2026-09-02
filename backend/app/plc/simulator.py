"""Minimal Modbus TCP PLC simulator for the handshake prototype.

Runs a pymodbus async TCP server plus a background tick loop that advances
PULSE_COUNT and HEARTBEAT the way a real PLC's encoder/scan loop would.
Dev/test stand-in only.

Pinned to pymodbus==3.7.4 deliberately, matching backend/services/plc_sim/main.py
and backend/requirements.txt -- pymodbus 3.15's datastore API was overhauled
(ModbusDeviceContext, devices= kwarg) and isn't a drop-in match for this
file's ModbusSlaveContext usage. Bump only with a deliberate rewrite.
"""

from __future__ import annotations

import asyncio
import logging

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

from app.plc.registers import HEARTBEAT, PULSE_COUNT, SPEED_SETPOINT

log = logging.getLogger("plc.simulator")

# A handful of spare registers past HEARTBEAT (addr 3) -- room to grow the
# register map without resizing the datastore every time.
DATASTORE_SIZE = 16

HOLDING_FN_CODE = 3


class PlcSimulator:
    """Async Modbus TCP server + background tick loop.

    encoder_cpr and port are constructor args, never hardcoded, per spec.
    """

    def __init__(
        self,
        encoder_cpr: int,
        port: int,
        tick_hz: float = 50.0,
        host: str = "127.0.0.1",
    ):
        if encoder_cpr <= 0:
            raise ValueError("encoder_cpr must be positive")
        self.encoder_cpr = encoder_cpr
        self.port = port
        self.host = host
        self.tick_hz = tick_hz

        self._context: ModbusServerContext | None = None
        self._server_task: asyncio.Task | None = None
        self._tick_task: asyncio.Task | None = None
        self._pulse_count = 0.0  # fractional accumulator, register gets the truncated int
        self._heartbeat = 0
        self._frozen = False  # test hook: simulate a stalled PLC (see set_frozen)

    def _make_context(self) -> ModbusServerContext:
        holding = [0] * DATASTORE_SIZE
        store = ModbusSlaveContext(
            di=ModbusSequentialDataBlock(0, [0] * 8),
            co=ModbusSequentialDataBlock(0, [0] * 8),
            hr=ModbusSequentialDataBlock(0, holding),
            ir=ModbusSequentialDataBlock(0, [0] * 8),
        )
        return ModbusServerContext(slaves=store, single=True)

    def _read(self, addr: int, count: int = 1) -> list[int]:
        return self._context[0x00].getValues(HOLDING_FN_CODE, addr, count=count)

    def _write(self, addr: int, values: list[int]) -> None:
        self._context[0x00].setValues(HOLDING_FN_CODE, addr, values)

    async def start(self) -> None:
        self._context = self._make_context()
        self._server_task = asyncio.create_task(
            StartAsyncTcpServer(context=self._context, address=(self.host, self.port))
        )
        self._tick_task = asyncio.create_task(self._tick_loop())
        # give the TCP server a moment to actually bind before returning
        await asyncio.sleep(0.1)
        log.info(
            "PlcSimulator listening on %s:%d (encoder_cpr=%d, tick_hz=%s)",
            self.host,
            self.port,
            self.encoder_cpr,
            self.tick_hz,
        )

    async def stop(self) -> None:
        for task in (self._tick_task, self._server_task):
            if task is not None:
                task.cancel()
        for task in (self._tick_task, self._server_task):
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def set_frozen(self, frozen: bool) -> None:
        """Test hook: stop advancing PULSE_COUNT/HEARTBEAT while keeping the
        TCP server up, to simulate a stalled PLC (acceptance test 5) without
        tearing down the connection."""
        self._frozen = frozen

    async def _tick_loop(self) -> None:
        tick_interval = 1.0 / self.tick_hz
        while True:
            await asyncio.sleep(tick_interval)
            if self._frozen:
                continue
            rpm_x10 = self._read(SPEED_SETPOINT)[0]
            rpm = rpm_x10 / 10.0
            pulses_this_tick = (rpm / 60.0) * self.encoder_cpr * tick_interval
            self._pulse_count = (self._pulse_count + pulses_this_tick) % self.encoder_cpr
            self._heartbeat = (self._heartbeat + 1) % 65536

            raw = int(self._pulse_count)
            self._write(PULSE_COUNT, [(raw >> 16) & 0xFFFF, raw & 0xFFFF])
            self._write(HEARTBEAT, [self._heartbeat])


async def start_simulator(
    encoder_cpr: int,
    port: int,
    tick_hz: float = 50.0,
    host: str = "127.0.0.1",
) -> PlcSimulator:
    """Construct and start a PlcSimulator, returning it once its TCP server
    is listening."""
    sim = PlcSimulator(encoder_cpr=encoder_cpr, port=port, tick_hz=tick_hz, host=host)
    await sim.start()
    return sim
