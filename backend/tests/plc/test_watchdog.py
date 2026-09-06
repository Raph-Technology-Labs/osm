"""PLCWatchdog unit tests -- fake ModbusPLCClient, no real/simulated PLC
needed. Covers the heartbeat-staleness -> STOP_CMD escalation path
(CLAUDE.md Section 15) that app/plc/watchdog.py implements."""

import time
from dataclasses import dataclass, field
from types import SimpleNamespace

from app.plc.watchdog import PLCWatchdog


@dataclass
class FakePLCClient:
    """Stands in for ModbusPLCClient -- same read_heartbeat/write_register/
    is_connected surface, no real socket."""
    heartbeat_value: int = 1
    connected: bool = True
    written: list = field(default_factory=list)
    fail_reads: bool = False

    def __post_init__(self):
        self.config = SimpleNamespace(registers=SimpleNamespace(stop_cmd=40010))

    def is_connected(self) -> bool:
        return self.connected

    def read_heartbeat(self) -> int:
        if self.fail_reads:
            from app.plc.modbus_client import PLCConnectionError

            raise PLCConnectionError("simulated read failure")
        return self.heartbeat_value

    def write_register(self, reg: int, value: int) -> None:
        self.written.append((reg, value))


def test_watchdog_does_not_escalate_while_heartbeat_advances():
    client = FakePLCClient(heartbeat_value=1)
    wd = PLCWatchdog(client, timeout_ms=100, poll_interval_s=0.02)

    for i in range(5):
        client.heartbeat_value = i  # advancing every check -- never stale
        wd._check_once()
        time.sleep(0.03)

    assert client.written == []


def test_watchdog_escalates_to_stop_cmd_on_stalled_heartbeat():
    client = FakePLCClient(heartbeat_value=7)
    wd = PLCWatchdog(client, timeout_ms=50, poll_interval_s=0.02)

    wd._check_once()  # establishes baseline (heartbeat=7, "just changed")
    time.sleep(0.08)  # exceed the 50ms timeout with no heartbeat change
    wd._check_once()

    assert client.written == [(40010, 1)]  # stop_cmd written exactly once


def test_watchdog_does_not_spam_stop_cmd_after_first_escalation():
    client = FakePLCClient(heartbeat_value=3)
    wd = PLCWatchdog(client, timeout_ms=30, poll_interval_s=0.02)

    wd._check_once()
    time.sleep(0.05)
    wd._check_once()  # first escalation
    wd._check_once()  # still stalled -- must not write again
    wd._check_once()

    assert client.written == [(40010, 1)]


def test_watchdog_recovers_after_heartbeat_resumes():
    client = FakePLCClient(heartbeat_value=1)
    wd = PLCWatchdog(client, timeout_ms=30, poll_interval_s=0.02)

    wd._check_once()
    time.sleep(0.05)
    wd._check_once()  # escalates once
    assert client.written == [(40010, 1)]

    client.heartbeat_value = 2  # PLC resumes ticking
    wd._check_once()
    assert wd._escalated is False  # cleared once heartbeat advances again


def test_watchdog_treats_read_failure_as_escalation():
    client = FakePLCClient(fail_reads=True)
    wd = PLCWatchdog(client, timeout_ms=1000, poll_interval_s=0.02)

    wd._check_once()

    assert client.written == [(40010, 1)]


def test_watchdog_ignores_checks_while_disconnected():
    client = FakePLCClient(connected=False)
    wd = PLCWatchdog(client, timeout_ms=10, poll_interval_s=0.02)

    wd._check_once()
    time.sleep(0.05)
    wd._check_once()

    assert client.written == []  # nothing to escalate -- connect() path owns this, not the watchdog


def test_watchdog_start_stop_thread_lifecycle():
    client = FakePLCClient(heartbeat_value=1)
    wd = PLCWatchdog(client, timeout_ms=20, poll_interval_s=0.01)

    wd.start()
    assert wd._thread is not None and wd._thread.is_alive()
    wd.stop()
    assert not wd._thread.is_alive()
