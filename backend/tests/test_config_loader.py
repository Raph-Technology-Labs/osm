"""config_loader.py schema/validator unit tests -- built directly from
dicts (ResolvedMachineConfig(**...)), no real machine_config.yaml file
needed. Covers the reject-before-exit ring-order validator added in
spec13 (found missing during spec12's code review)."""

import pytest
from pydantic import ValidationError

from app.config.config_loader import ResolvedMachineConfig

MINIMAL_REGISTERS = {
    "pulse_count": 1,
    "encoder_indexer_ppr": 2,
    "encoder_count": 3,
    "part_sensor": 4,
    "heartbeat": 5,
    "indexing_pulse": 6,
    "heartbeat_per_slot": 7,
    "indexing_pulse_per_slot": 8,
    "reject_cmd": 9,
    "stop_cmd": 10,
    "speed_setpoint": 11,
    "fault": 12,
}


def make_config(reject_offset=None, exit_offset=100):
    stations = []
    if reject_offset is not None:
        stations.append({
            "id": "r1",
            "name": "R1",
            "type": "reject",
            "station_offset_pulses": reject_offset,
            "enabled": True,
        })
    stations.append({
        "id": "exit1",
        "name": "Exit",
        "type": "exit",
        "station_offset_pulses": exit_offset,
        "result_write": {"part_id_reg": 100, "result_reg": 101, "ack_reg": 102},
    })
    return ResolvedMachineConfig(
        part_code="TEST-001",
        part_name="Test Part",
        indexer={"diameter_mm": 150.0, "part_size_mm": 20.0, "tolerance_pct": 15.0, "encoder_cpr": 3600},
        plc={
            "ip": "1.2.3.4",
            "port": 502,
            "vendor": "test",
            "speed_setpoint_rpm": 10.0,
            "registers": MINIMAL_REGISTERS,
        },
        stations=stations,
    )


def test_reject_before_exit_passes_validation():
    config = make_config(reject_offset=50, exit_offset=100)
    assert config.reject_station().station_offset_pulses == 50
    assert config.exit_station().station_offset_pulses == 100


def test_reject_at_same_offset_as_exit_rejected():
    with pytest.raises(ValidationError, match="must be strictly before the exit"):
        make_config(reject_offset=100, exit_offset=100)


def test_reject_after_exit_rejected():
    with pytest.raises(ValidationError, match="must be strictly before the exit"):
        make_config(reject_offset=150, exit_offset=100)


def test_no_reject_station_skips_the_check():
    # r1 disabled/absent (commissioning mode) -- nothing to validate.
    config = make_config(reject_offset=None, exit_offset=100)
    assert config.reject_station() is None
