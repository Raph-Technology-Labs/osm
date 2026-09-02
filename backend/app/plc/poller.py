"""PC-side slot tracking: wrap-corrected pulse-to-slot conversion
(SlotTracker) and the Modbus client that drives it (PlcPoller).

Wrap-correction follows the indexer-ring-math convention used elsewhere in
this project: PULSE_COUNT resets to 0 every revolution, so slot-boundary
math is done against a never-reset internal accumulator, never the raw
register value directly.
"""

from __future__ import annotations

import time

from pymodbus.client import AsyncModbusTcpClient

from app.plc.registers import POLL_BATCH_WIDTH, PULSE_COUNT, SPEED_SETPOINT

HEARTBEAT_STALE_TIMEOUT_S = 0.5


class SlotTracker:
    """Pure wrap-corrected slot-index tracker. No I/O, no asyncio.

    pulses_per_slot is computed by the caller as encoder_cpr // n_slots (the
    project convention -- see the indexer-ring-math skill); SlotTracker only
    needs the resulting value plus encoder_cpr for wrap correction.
    """

    def __init__(self, pulses_per_slot: int, encoder_cpr: int):
        if pulses_per_slot <= 0:
            raise ValueError("pulses_per_slot must be positive")
        if encoder_cpr <= 0:
            raise ValueError("encoder_cpr must be positive")
        self.pulses_per_slot = pulses_per_slot
        self.encoder_cpr = encoder_cpr
        self._accumulated = 0
        self._last_raw: int | None = None

    def update(self, raw_count: int) -> int:
        """Feed one raw PULSE_COUNT reading, return the current slot index."""
        if self._last_raw is None:
            gap = 0
        elif raw_count < self._last_raw:
            # wraparound: the gap is what remained before the wrap plus
            # what's accumulated since it, never a reset to zero
            gap = (self.encoder_cpr - self._last_raw) + raw_count
        else:
            gap = raw_count - self._last_raw

        self._accumulated += gap
        self._last_raw = raw_count
        return self._accumulated // self.pulses_per_slot

    @staticmethod
    def slot_boundary_crossed(prev_slot: int, new_slot: int) -> bool:
        return new_slot != prev_slot


class PlcPoller:
    """AsyncModbusTcpClient wrapper: batches PULSE_COUNT + HEARTBEAT into one
    read per poll (Throughput Design Requirement 1), feeds SlotTracker, and
    raises TimeoutError if HEARTBEAT goes stale for >500ms."""

    def __init__(
        self,
        host: str,
        port: int,
        slot_tracker: SlotTracker,
        poll_hz: float = 20.0,
        heartbeat_stale_timeout_s: float = HEARTBEAT_STALE_TIMEOUT_S,
    ):
        self.host = host
        self.port = port
        self.slot_tracker = slot_tracker
        self.poll_hz = poll_hz
        self.heartbeat_stale_timeout_s = heartbeat_stale_timeout_s

        self._client = AsyncModbusTcpClient(host, port=port)
        self._last_heartbeat: int | None = None
        self._last_heartbeat_change_ts: float | None = None

    async def connect(self) -> bool:
        return await self._client.connect()

    def close(self) -> None:
        self._client.close()

    async def write_speed_setpoint(self, rpm: float) -> None:
        rpm_x10 = round(rpm * 10)
        rr = await self._client.write_register(SPEED_SETPOINT, rpm_x10)
        if rr.isError():
            raise RuntimeError(f"SPEED_SETPOINT write failed: {rr}")

    async def poll_once(self) -> int:
        # PULSE_COUNT + HEARTBEAT are contiguous specifically so this is a
        # single batched read (Throughput Design Requirement 1).
        rr = await self._client.read_holding_registers(PULSE_COUNT, count=POLL_BATCH_WIDTH)
        if rr.isError():
            raise RuntimeError(f"poll read failed: {rr}")
        high, low, heartbeat = rr.registers
        raw_count = (high << 16) | low

        now = time.monotonic()
        if self._last_heartbeat is None or heartbeat != self._last_heartbeat:
            self._last_heartbeat = heartbeat
            self._last_heartbeat_change_ts = now
        elif now - self._last_heartbeat_change_ts > self.heartbeat_stale_timeout_s:
            raise TimeoutError("PLC heartbeat stalled")

        return self.slot_tracker.update(raw_count)
