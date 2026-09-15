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
import threading

from pymodbus.client import ModbusTcpClient

from app.config.config_loader import PLCConnectionConfig

log = logging.getLogger("plc.modbus_client")

# registers.py/RegisterMapConfig values are literal Modicon 4xxxx addresses,
# not 0-based pymodbus protocol addresses (same offset app/plc/poller.py's
# _protocol_address() and app/plc/simulator.py's _read()/_write() already
# subtract) -- every read/write below must convert before calling pymodbus.
MODBUS_ADDRESS_OFFSET = 40001


def _protocol_address(register: int) -> int:
    return register - MODBUS_ADDRESS_OFFSET


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
        # pymodbus's sync client is one blocking TCP socket -- not safe for
        # concurrent use from multiple threads. Found live, 2026-09-15:
        # StationDispatcher's tick thread (~every real_poll_interval_ms) and
        # the new /health/plc endpoint (polled from the frontend's global
        # disconnect-toast hook) both call into this same client instance
        # from different threads with no serialization, which can interleave
        # two Modbus request/response pairs on one socket -- indistinguishable
        # from a real timeout/disconnect, and a likely contributor to slow
        # requests (session start blocking behind a contended read) and
        # spurious "No response received" errors that weren't necessarily a
        # genuine hardware/network issue. Every method below holds this for
        # its one request/response round trip -- matches zeromq.py's
        # _send_lock for the exact same class of shared-socket hazard.
        self._lock = threading.Lock()

    def connect(self) -> bool:
        with self._lock:
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

    def _mark(self, ok: bool) -> None:
        """Every read/write updates _connected from its own outcome, not
        just connect()/close() -- found live, 2026-09-15: a request timeout
        ("No response received") raised PLCConnectionError but never
        touched _connected, so is_connected() (Health Check page, and any
        future live disconnect toast) kept reporting connected=True through
        an actual outage. pymodbus's own .connected doesn't reliably flip on
        a timed-out request either (the socket can stay open), so this is
        the only place that actually tracks it. Self-healing: the next
        successful call flips it back True, no explicit reconnect() needed."""
        self._connected = ok

    def read_heartbeat(self) -> int:
        """Minimal liveness check -- one read of registers.heartbeat.
        Not a watchdog: no periodic polling, no staleness detection, no
        escalation (see app/plc/watchdog.py for that). Just proves the
        connection round-trips a real read."""
        with self._lock:
            rr = self._client.read_holding_registers(_protocol_address(self.config.registers.heartbeat), count=1)
            if rr.isError():
                self._mark(False)
                raise PLCConnectionError(f"heartbeat read failed: {rr}")
            self._mark(True)
            return rr.registers[0]

    def read_register(self, reg: int) -> int:
        """Single-register read, for actuator/error-register lookups
        (Device Settings / Health Check). `reg` is a literal Modicon
        register number (e.g. 40011), not a protocol address -- converted
        here. Not the batched read_holding_registers(start, count) call
        CLAUDE.md Throughput Design Requirement 1 wants for the hot
        inspection path -- these reads are low-frequency, user-triggered or
        slow-polled."""
        with self._lock:
            rr = self._client.read_holding_registers(_protocol_address(reg), count=1)
            if rr.isError():
                self._mark(False)
                raise PLCConnectionError(f"register {reg} read failed: {rr}")
            self._mark(True)
            return rr.registers[0]

    def read_registers(self, start_reg: int, count: int) -> list[int]:
        """Batched read -- CLAUDE.md Throughput Design Requirement 1: one
        read_holding_registers(start, count) round trip for contiguous,
        frequently-co-read registers (e.g. pulse_count + part_sensor, both
        read every StationDispatcher._tick_real() tick) instead of N
        separate ones -- each round trip is ~5-20ms over TCP, which
        compounds fast at the 900 PPM / 15 events-sec target. `start_reg`
        is a literal Modicon register number (e.g. 40001), not a protocol
        address -- converted here, same as read_register()."""
        with self._lock:
            rr = self._client.read_holding_registers(_protocol_address(start_reg), count=count)
            if rr.isError():
                self._mark(False)
                raise PLCConnectionError(f"batched register read failed (start={start_reg}, count={count}): {rr}")
            self._mark(True)
            return rr.registers

    def write_register(self, reg: int, value: int) -> None:
        with self._lock:
            rr = self._client.write_register(_protocol_address(reg), value)
            if rr.isError():
                self._mark(False)
                raise PLCConnectionError(f"register {reg} write failed: {rr}")
            self._mark(True)

    def close(self) -> None:
        with self._lock:
            self._client.close()
            self._connected = False
