"""Minimal Modbus TCP client -- connect + one liveness read only.

This is NOT the watchdog. app/plc/watchdog.py (heartbeat staleness + ACK
timeout monitoring, STOP_COMMAND ownership, per CLAUDE.md Architecture
section and the modbus-register-design skill's CMD/ACK escalation rules) is
separate, larger, future work -- this file only proves the TCP connection is
real and exposes a register-read primitive for that later work to build on.

Sync client (pymodbus.client.ModbusTcpClient), not async -- this app's
FastAPI startup handler and StationDispatcher are plain sync/threading code
today, with no running asyncio loop to hang an async client off. Revisit
when watchdog.py's continuous poll loop is built.

"PLC" here means the Integra controller (in-house, plain TCP) -- Modbus TCP
is an explicitly-labeled dev-time transport stand-in until Integra's real
wire protocol is documented (see backend/services/plc_sim/config.py's docstring).
Tested only against that simulator, never real hardware, per CLAUDE.md
Section 10.
"""

from __future__ import annotations

import logging

from pymodbus.client import ModbusTcpClient

from app.config.config_loader import PLCConnectionConfig

log = logging.getLogger("plc.modbus_client")


def resolve_plc_target(plc_cfg: PLCConnectionConfig) -> tuple[str, int]:
    if plc_cfg.sim.enabled:
        return plc_cfg.sim.host, plc_cfg.sim.port
    return plc_cfg.ip, plc_cfg.port


class PLCConnectionError(RuntimeError):
    """connect() or the liveness read failed. Callers decide whether that's
    fatal -- app/inspection_session.py logs and continues rather than
    crashing the app."""


class ModbusPLCClient:
    def __init__(self, config: PLCConnectionConfig):
        self.config = config
        host, port = resolve_plc_target(config)
        self._client = ModbusTcpClient(host, port=port)
        self._connected = False

    def connect(self) -> bool:
        self._connected = self._client.connect()
        if not self._connected:
            raise PLCConnectionError(
                f"Could not open Modbus TCP connection to {self._client.comm_params.host}"
                f":{self._client.comm_params.port}"
            )
        log.info("PLC connected (%s)", "sim" if self.config.sim.enabled else "real hardware")
        return self._connected

    def is_connected(self) -> bool:
        return self._connected and self._client.connected

    def read_heartbeat(self) -> int:
        """Minimal liveness check -- one read of registers.heartbeat_plc.
        Not a watchdog: no periodic polling, no staleness detection, no
        escalation. Just proves the connection round-trips a real read."""
        rr = self._client.read_holding_registers(self.config.registers.heartbeat_plc, count=1)
        if rr.isError():
            raise PLCConnectionError(f"heartbeat_plc read failed: {rr}")
        return rr.registers[0]

    def read_register(self, reg: int) -> int:
        """Single-register read, for actuator/error-register lookups
        (Device Settings / Health Check). Not the batched
        read_holding_registers(start, count) call CLAUDE.md Throughput
        Design Requirement 1 wants for the hot inspection path -- these
        reads are low-frequency, user-triggered or slow-polled."""
        rr = self._client.read_holding_registers(reg, count=1)
        if rr.isError():
            raise PLCConnectionError(f"register {reg} read failed: {rr}")
        return rr.registers[0]

    def write_register(self, reg: int, value: int) -> None:
        rr = self._client.write_register(reg, value)
        if rr.isError():
            raise PLCConnectionError(f"register {reg} write failed: {rr}")

    def close(self) -> None:
        self._client.close()
        self._connected = False
