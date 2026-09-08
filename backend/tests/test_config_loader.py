"""config_loader.py schema/validator unit tests -- built directly from
dicts (ResolvedMachineConfig(**...)), no real machine_config.yaml file
needed. Covers the reject-before-exit ring-order validator added in
spec13 (found missing during spec12's code review), generalized in
spec11 Part 2 (dual reject routing) to check every reject station, plus
that generalization's own new validators/accessors."""

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


def make_config(reject_offset=None, exit_offset=100, reject_stations=None, inspection_ids=()):
    stations = [
        {
            "id": sid,
            "name": sid,
            "type": "inspection",
            "station_offset_pulses": 10,
            "cameras": {},
            "pipeline": {"defect": {
                "model_path": "m.pt", "model_type": "yolo",
                "allowed_cameras": [], "detect_classes": [], "allowed_defects": [],
            }},
        }
        for sid in inspection_ids
    ]
    if reject_stations is not None:
        stations.extend(reject_stations)
    elif reject_offset is not None:
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
        indexer={
            "diameter_mm": 150.0, "part_size_mm": 20.0, "tolerance_pct": 15.0,
            "encoder_cpr": 3600, "entry_sensor_mid_offset_pulses": 0,
        },
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
    assert config.reject_stations()[0].station_offset_pulses == 50
    assert config.exit_station().station_offset_pulses == 100


def test_reject_at_same_offset_as_exit_rejected():
    with pytest.raises(ValidationError, match="must be strictly before the exit"):
        make_config(reject_offset=100, exit_offset=100)


def test_reject_after_exit_rejected():
    with pytest.raises(ValidationError, match="must be strictly before the exit"):
        make_config(reject_offset=150, exit_offset=100)


def test_no_reject_station_skips_the_check():
    # reject disabled/absent (commissioning mode) -- nothing to validate.
    config = make_config(reject_offset=None, exit_offset=100)
    assert config.reject_stations() == []


def test_multiple_reject_stations_allowed():
    # spec11 Part 2 -- at_most_one_reject_station is gone.
    config = make_config(reject_stations=[
        {"id": "r1", "name": "R1", "type": "reject", "station_offset_pulses": 30, "enabled": True},
        {"id": "r2", "name": "R2", "type": "reject", "station_offset_pulses": 60, "enabled": True},
    ], exit_offset=100)
    assert [s.id for s in config.reject_stations()] == ["r1", "r2"]


def test_reject_stations_returns_ring_order_regardless_of_yaml_order():
    # Declared r2-before-r1 in the YAML, but r2 physically sits AFTER r1
    # (larger station_offset_pulses) -- reject_stations() must still
    # return them in ring order, not declaration order, since
    # StationDispatcher depends on this for overlapping-watches safety.
    config = make_config(reject_stations=[
        {"id": "r2", "name": "R2", "type": "reject", "station_offset_pulses": 60, "enabled": True},
        {"id": "r1", "name": "R1", "type": "reject", "station_offset_pulses": 30, "enabled": True},
    ], exit_offset=100)
    assert [s.id for s in config.reject_stations()] == ["r1", "r2"]


def test_all_reject_stations_checked_against_exit_not_just_the_first():
    with pytest.raises(ValidationError, match="must be strictly before the exit"):
        make_config(reject_stations=[
            {"id": "r1", "name": "R1", "type": "reject", "station_offset_pulses": 30, "enabled": True},
            {"id": "r2", "name": "R2", "type": "reject", "station_offset_pulses": 150, "enabled": True},  # past exit(100)
        ], exit_offset=100)


def test_reject_watches_defaults_to_none_meaning_watch_everything():
    config = make_config(reject_offset=50, exit_offset=100)
    assert config.reject_stations()[0].watches is None


def test_reject_watches_referencing_unknown_station_rejected():
    with pytest.raises(ValidationError, match="unknown inspection station"):
        make_config(
            reject_stations=[{
                "id": "r1", "name": "R1", "type": "reject",
                "station_offset_pulses": 50, "enabled": True, "watches": ["does_not_exist"],
            }],
            exit_offset=100,
            inspection_ids=["s1"],
        )


def test_reject_watches_referencing_real_station_accepted():
    config = make_config(
        reject_stations=[{
            "id": "r1", "name": "R1", "type": "reject",
            "station_offset_pulses": 50, "enabled": True, "watches": ["s1"],
        }],
        exit_offset=100,
        inspection_ids=["s1", "s2"],
    )
    assert config.reject_stations()[0].watches == ["s1"]


# --- spec11 Part 3 (continuous, no removal): VirtualExitStation + the
# generalized exactly_one_terminal_station validator ---

def make_config_with_stations(stations):
    """Full control over stations[] -- make_config() above always appends
    a real exit station, which Part 3's virtual_exit-only configs must
    NOT have."""
    return ResolvedMachineConfig(
        part_code="TEST-001",
        part_name="Test Part",
        indexer={
            "diameter_mm": 150.0, "part_size_mm": 20.0, "tolerance_pct": 15.0,
            "encoder_cpr": 3600, "entry_sensor_mid_offset_pulses": 0,
        },
        plc={
            "ip": "1.2.3.4",
            "port": 502,
            "vendor": "test",
            "speed_setpoint_rpm": 10.0,
            "registers": MINIMAL_REGISTERS,
        },
        stations=stations,
    )


INSPECTION_STATION = {
    "id": "s1", "name": "s1", "type": "inspection", "station_offset_pulses": 10,
    "cameras": {}, "pipeline": {"defect": {
        "model_path": "m.pt", "model_type": "yolo",
        "allowed_cameras": [], "detect_classes": [], "allowed_defects": [],
    }},
}


def test_virtual_exit_only_config_resolves_cleanly():
    config = make_config_with_stations([
        INSPECTION_STATION,
        {"id": "vexit1", "name": "Virtual Exit", "type": "virtual_exit", "station_offset_pulses": 50},
    ])
    assert config.virtual_exit_stations()[0].id == "vexit1"
    assert config.reject_stations() == []


def test_multiple_virtual_exit_stations_allowed():
    # Unlike real exit stations (exactly one), multiple virtual_exit
    # checkpoints are fine -- none of them discharge the part.
    config = make_config_with_stations([
        INSPECTION_STATION,
        {"id": "vexit1", "name": "V1", "type": "virtual_exit", "station_offset_pulses": 50},
        {"id": "vexit2", "name": "V2", "type": "virtual_exit", "station_offset_pulses": 80},
    ])
    assert [s.id for s in config.virtual_exit_stations()] == ["vexit1", "vexit2"]


def test_neither_exit_nor_virtual_exit_rejected():
    with pytest.raises(ValidationError, match="exactly one type: exit"):
        make_config_with_stations([INSPECTION_STATION])


def test_both_exit_and_virtual_exit_rejected():
    with pytest.raises(ValidationError, match="exactly one type: exit"):
        make_config_with_stations([
            INSPECTION_STATION,
            {"id": "vexit1", "name": "V1", "type": "virtual_exit", "station_offset_pulses": 50},
            {
                "id": "exit1", "name": "Exit", "type": "exit", "station_offset_pulses": 80,
                "result_write": {"part_id_reg": 100, "result_reg": 101, "ack_reg": 102},
            },
        ])


def test_reject_before_exit_skips_entirely_for_virtual_exit_only_config():
    # A reject station alongside virtual_exit-only stations (not what
    # spec11 Part 3 itself builds, but not forbidden by the schema either)
    # must not crash reject_before_exit by calling exit_station() when no
    # real exit station exists.
    config = make_config_with_stations([
        INSPECTION_STATION,
        {"id": "r1", "name": "R1", "type": "reject", "station_offset_pulses": 30, "enabled": True},
        {"id": "vexit1", "name": "V1", "type": "virtual_exit", "station_offset_pulses": 50},
    ])
    assert config.reject_stations()[0].id == "r1"
