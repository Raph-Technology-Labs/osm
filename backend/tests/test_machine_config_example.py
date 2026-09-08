"""machine_config.example.yaml regression test (spec13 #9, found missing in
spec12's code review) -- this file is meant to bootstrap a new machine
deployment, so it must actually validate against the schema
config_loader.py enforces today, not just be a plausible-looking sketch.
Loads and resolves it exactly the way resolve_config_for_part() does."""

from pathlib import Path

from app.config.config_loader import ResolvedMachineConfig, load_machine_config

EXAMPLE_CONFIG_PATH = Path(__file__).parent.parent / "app" / "config" / "machine_config.example.yaml"


def test_example_config_resolves_cleanly():
    raw = load_machine_config(EXAMPLE_CONFIG_PATH)

    resolved = ResolvedMachineConfig(
        part_code=raw["machine"]["part_code"],
        part_name=raw["machine"]["part_name"],
        indexer=raw["indexer"],
        plc=raw["plc"],
        stations=raw["stations"],
        actuators=raw.get("actuators", []),
    )

    assert resolved.exit_station().id == "exit1"
    assert resolved.reject_station() is not None
    assert resolved.indexer.n_slots > 0
    assert resolved.indexer.pulses_per_slot > 0
