"""ModbusPLCClient must turn pymodbus exceptions (dead link) into
PLCConnectionError and report disconnected -- 2026-09-28: a raised
ConnectionException escaped unwrapped and is_connected() stayed True."""

import pytest
from pymodbus.exceptions import ConnectionException

from app.plc.modbus_client import ModbusPLCClient, PLCConnectionError


class _DeadSocketClient:
    connected = True

    def __init__(self):
        self.closed = 0
        self.connect_ok = False

    def read_holding_registers(self, address, count=1):
        raise ConnectionException("Failed to connect[ModbusTcpClient 192.168.7.72:502]")

    def write_register(self, address, value):
        raise ConnectionException("Failed to connect")

    def close(self):
        self.closed += 1

    def connect(self):
        return self.connect_ok


def _client():
    c = ModbusPLCClient.__new__(ModbusPLCClient)  # skip real socket setup
    import threading

    c._client = _DeadSocketClient()
    c._connected = True
    c._lock = threading.Lock()
    return c


def test_read_registers_raises_plc_error_and_marks_disconnected():
    c = _client()
    with pytest.raises(PLCConnectionError, match="PLC unreachable"):
        c.read_registers(40001, 4)
    assert c.is_connected() is False


def test_write_register_raises_plc_error_and_marks_disconnected():
    c = _client()
    with pytest.raises(PLCConnectionError):
        c.write_register(40009, 1)
    assert c.is_connected() is False


def test_reconnect_closes_stale_socket_and_raises_while_plc_down():
    c = _client()

    class _Params:
        host, port = "192.168.7.72", 502

    c._client.comm_params = _Params()
    c.config = type("Cfg", (), {"sim": type("Sim", (), {"enabled": False})()})()
    with pytest.raises(PLCConnectionError):
        c.reconnect()
    assert c._client.closed == 1
    c._client.connect_ok = True
    assert c.reconnect() is True



def test_client_uses_configured_short_timeout_and_retries(monkeypatch):
    import app.plc.modbus_client as mc
    from app.config.config_loader import load_machine_config, resolve_config_for_part

    seen = {}

    class _Capture:
        def __init__(self, host, port=502, **kw):
            seen.update(host=host, port=port, **kw)

    monkeypatch.setattr(mc, "ModbusTcpClient", _Capture)
    cfg = resolve_config_for_part(load_machine_config()["machine"]["part_code"])
    mc.ModbusPLCClient(cfg.plc)
    assert seen["timeout"] == cfg.plc.modbus_timeout_s == 1.0
    assert seen["retries"] == cfg.plc.modbus_retries == 1
