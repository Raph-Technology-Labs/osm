"""machine_config.rubber_small.yaml regression test (spec11 Part 1) --
exercises N-cameras-per-station generality (3 inspection stations, 2
cameras each) against the real config schema and resolve_config_for_part(),
the same production entry point start_session() uses (just with an
explicit config_path override, since today's architecture has no
per-part-code file lookup -- see spec11_multi_part_configs.md's Step 0
finding: machine_config.yaml is the only per-part file, config_path is an
existing but currently-unused-by-any-real-caller parameter).

"Fires correctly" (per Part 1's acceptance criteria) isn't re-tested here
-- StationDispatcher/CameraStation are already config-driven and covered
by their own test suites (test_dispatcher.py, test_station_registry.py),
and generalize to any station/camera count by construction, not by
anything specific to this part. This file only proves the config itself
is structurally what Part 1 asks for and resolves cleanly."""

from pathlib import Path

from app.config.config_loader import resolve_config_for_part

RUBBER_SMALL_CONFIG_PATH = Path(__file__).parent.parent / "app" / "config" / "machine_config.rubber_small.yaml"


def test_rubber_small_resolves_cleanly():
    resolved = resolve_config_for_part("RS-001", config_path=RUBBER_SMALL_CONFIG_PATH)

    assert resolved.part_name == "Rubber Small"
    assert resolved.indexer.n_slots > 0
    assert resolved.indexer.pulses_per_slot > 0


def test_rubber_small_has_three_inspection_stations_two_cameras_each():
    resolved = resolve_config_for_part("RS-001", config_path=RUBBER_SMALL_CONFIG_PATH)

    inspection_stations = resolved.inspection_stations()
    assert [s.id for s in inspection_stations] == ["s1", "s2", "s3"]
    for station in inspection_stations:
        assert len(station.cameras) == 2

    assert len(resolved.cameras()) == 6  # 3 stations x 2 cameras, no ID collisions


def test_rubber_small_has_default_single_reject_and_exit():
    # "Rejection and exit are DEFAULT: single r1 after s3, single exit1
    # after that -- same pattern as rubber_big" (not spec11 Part 2's dual
    # reject routing).
    resolved = resolve_config_for_part("RS-001", config_path=RUBBER_SMALL_CONFIG_PATH)

    rejects = resolved.reject_stations()
    exit_station = resolved.exit_station()
    assert len(rejects) == 1
    reject = rejects[0]
    assert reject.id == "r1"
    assert reject.watches is None  # default: watches every inspection station, not selective routing
    assert reject.enabled is True
    assert exit_station.id == "exit1"
    assert reject.station_offset_pulses < exit_station.station_offset_pulses

    reject_count = sum(1 for s in resolved.stations if s.type == "reject")
    exit_count = sum(1 for s in resolved.stations if s.type == "exit")
    assert reject_count == 1
    assert exit_count == 1


def test_rubber_small_reuses_rubber_bigs_pipeline_shapes():
    # "Reuse rubber_big's measurement/defect pipeline blocks as a
    # structural starting point. Don't invent new tolerance/threshold
    # numbers."
    resolved = resolve_config_for_part("RS-001", config_path=RUBBER_SMALL_CONFIG_PATH)
    by_id = {s.id: s for s in resolved.inspection_stations()}

    assert by_id["s1"].pipeline.measurement is not None
    assert by_id["s1"].pipeline.defect is None
    param = by_id["s1"].pipeline.measurement.parameters["diameter_mm"]
    assert (param.nominal_value, param.upper_limit, param.lower_limit) == (10.0, 10.6, 9.2)

    assert by_id["s2"].pipeline.defect is not None
    assert by_id["s2"].pipeline.measurement is None
    assert by_id["s2"].pipeline.defect.allowed_defects == ["cat"]

    assert by_id["s3"].pipeline.measurement is not None
    assert by_id["s3"].pipeline.defect is None
