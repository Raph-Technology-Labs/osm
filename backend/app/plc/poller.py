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

from app.plc.registers import HEARTBEAT, PULSE_COUNT, SPEED_SETPOINT

HEARTBEAT_STALE_TIMEOUT_S = 0.5

# registers.py stores literal Modicon 4xxxx numbers (per the instrumentation
# team's sheet); pymodbus's read/write calls want a 0-based protocol address.
MODBUS_ADDRESS_OFFSET = 40001


def _protocol_address(register: int) -> int:
    return register - MODBUS_ADDRESS_OFFSET


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
    """AsyncModbusTcpClient wrapper: polls PULSE_COUNT and HEARTBEAT, feeds
    SlotTracker, and raises TimeoutError if HEARTBEAT goes stale for >500ms.

    PULSE_COUNT and HEARTBEAT are no longer contiguous addresses in the
    instrumentation team's register map (40001 vs 40005), so this is two
    separate reads -- the previous single-batched-read optimization
    (Throughput Design Requirement 1) no longer applies as written and isn't
    reinstated here; that's poll-loop design work, not a config/naming
    change."""

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
        # 0-1000 scale per the instrumentation sheet; rpm*10 encoding is the
        # prior best guess and is UNCONFIRMED against that scale -- see
        # machine_config.yaml's speed_setpoint_rpm comment.
        rpm_x10 = round(rpm * 10)
        rr = await self._client.write_register(_protocol_address(SPEED_SETPOINT), rpm_x10)
        if rr.isError():
            raise RuntimeError(f"SPEED_SETPOINT write failed: {rr}")

    async def poll_once(self) -> int:
        pulse_rr = await self._client.read_holding_registers(_protocol_address(PULSE_COUNT), count=1)
        if pulse_rr.isError():
            raise RuntimeError(f"PULSE_COUNT read failed: {pulse_rr}")
        raw_count = pulse_rr.registers[0]

        heartbeat_rr = await self._client.read_holding_registers(_protocol_address(HEARTBEAT), count=1)
        if heartbeat_rr.isError():
            raise RuntimeError(f"HEARTBEAT read failed: {heartbeat_rr}")
        heartbeat = heartbeat_rr.registers[0]

        now = time.monotonic()
        if self._last_heartbeat is None or heartbeat != self._last_heartbeat:
            self._last_heartbeat = heartbeat
            self._last_heartbeat_change_ts = now
        elif now - self._last_heartbeat_change_ts > self.heartbeat_stale_timeout_s:
            raise TimeoutError("PLC heartbeat stalled")

        return self.slot_tracker.update(raw_count)
