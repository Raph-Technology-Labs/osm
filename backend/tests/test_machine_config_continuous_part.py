"""machine_config.continuous_part.yaml regression test (spec11 Part 3) --
structural/schema-level checks; the actual no-removal/no-double-counting
behavior is exercised against the dispatcher directly in
test_virtual_exit.py."""

from pathlib import Path

from app.config.config_loader import resolve_config_for_part

CONTINUOUS_PART_CONFIG_PATH = Path(__file__).parent.parent / "app" / "config" / "machine_config.continuous_part.yaml"


def test_continuous_part_resolves_cleanly():
    resolved = resolve_config_for_part("CP-001", config_path=CONTINUOUS_PART_CONFIG_PATH)

    assert resolved.part_name == "Continuous Part"
    assert resolved.indexer.n_slots > 0


def test_continuous_part_has_no_reject_or_real_exit_station():
    resolved = resolve_config_for_part("CP-001", config_path=CONTINUOUS_PART_CONFIG_PATH)

    assert resolved.reject_stations() == []
    assert sum(1 for s in resolved.stations if s.type == "exit") == 0


def test_continuous_part_has_exactly_one_virtual_exit_station():
    resolved = resolve_config_for_part("CP-001", config_path=CONTINUOUS_PART_CONFIG_PATH)

    virtual_exits = resolved.virtual_exit_stations()
    assert len(virtual_exits) == 1
    assert virtual_exits[0].id == "vexit1"


def test_continuous_part_has_two_inspection_stations():
    resolved = resolve_config_for_part("CP-001", config_path=CONTINUOUS_PART_CONFIG_PATH)

    assert [s.id for s in resolved.inspection_stations()] == ["s1", "s2"]
