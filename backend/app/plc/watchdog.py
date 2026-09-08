"""PLC connection-loss watchdog (CLAUDE.md Section 15: "PLC connection
loss: watchdog must detect and trigger the STOP_COMMAND path, not silently
retry forever" -- part of Critical Rule 4's ACK-timeout escalation intent).

Scope today: HEARTBEAT staleness only. True CMD/ACK-pair timeout escalation
per Rule 4 ("Missed REJECT_ACK escalates to STOP_COMMAND... missed OK_ACK
only raises FAULT_STATUS") needs REJECT_CMD/STOP_CMD to actually have
paired _ACK registers -- they don't, per the instrumentation sheet
(machine_config.yaml's own comment on this). Not inventing one; ask the
instrumentation team. This watchdog covers what's actually possible with
today's real register map: if HEARTBEAT stops changing for longer than
the configured timeout, the PLC is considered lost and STOP_CMD is written,
logged at ERROR with a full register snapshot (CLAUDE.md Section 14).

timeout_ms (PLCConnectionConfig.watchdog_timeout_ms) is an explicit
PLACEHOLDER -- real tuning happens once the indexer/PLC hardware actually
exists, per instruction, not guessed at now.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from app.plc.modbus_client import ModbusPLCClient, PLCConnectionError

log = logging.getLogger("plc.watchdog")


class PLCWatchdog:
    def __init__(self, client: ModbusPLCClient, timeout_ms: float, poll_interval_s: float = 0.5):
        self._client = client
        self._timeout_s = timeout_ms / 1000.0
        self._poll_interval_s = poll_interval_s
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_heartbeat: Optional[int] = None
        self._last_change_ts: Optional[float] = None
        self._escalated = False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info(
            "PLC watchdog started (timeout=%.0fms -- PLACEHOLDER, not yet tuned against real hardware)",
            self._timeout_s * 1000,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop_event.wait(self._poll_interval_s):
            self._check_once()

    def _check_once(self) -> None:
        if not self._client.is_connected():
            return  # connection loss at the TCP level is already handled/logged
            # where connect() is called (app/inspection_session.py) -- nothing
            # new to escalate here until it reconnects and heartbeat can be read again.
        try:
            heartbeat = self._client.read_heartbeat()
        except PLCConnectionError:
            log.error("watchdog: heartbeat read failed -- treating as connection loss", exc_info=True)
            self._escalate({"heartbeat_read": "failed"})
            return

        now = time.monotonic()
        if self._last_heartbeat is None or heartbeat != self._last_heartbeat:
            self._last_heartbeat = heartbeat
            self._last_change_ts = now
            self._escalated = False
            return

        if self._escalated:
            return  # already escalated for this stall -- don't spam STOP_CMD writes every poll

        stalled_for_s = now - self._last_change_ts
        if stalled_for_s > self._timeout_s:
            log.error(
                "watchdog: HEARTBEAT stalled at %d for %.2fs (timeout %.0fms) -- escalating to STOP_CMD",
                heartbeat, stalled_for_s, self._timeout_s * 1000,
            )
            self._escalate({"heartbeat": heartbeat, "stalled_for_s": stalled_for_s})

    def _escalate(self, register_snapshot: dict) -> None:
        self._escalated = True
        try:
            # stop_cmd is a combined run/stop bit (1=run, 0=halt) per the
            # 2026-09-07 convention change -- see routers/inspection.py's
            # _write_stop_cmd(), the newer, authoritative source for this
            # register's meaning. A halt-on-escalation write is therefore 0,
            # not 1 (the register's original, pre-convention-change meaning
            # this watchdog was still using -- found in spec12's code
            # review: the two PC-side writers of this register disagreed).
            self._client.write_register(self._client.config.registers.stop_cmd, 0)
        except PLCConnectionError:
            log.error("watchdog: STOP_CMD write ALSO failed -- PLC fully unreachable", exc_info=True)
        log.error("watchdog: FAULT_STATUS -- register snapshot at escalation: %s", register_snapshot)
