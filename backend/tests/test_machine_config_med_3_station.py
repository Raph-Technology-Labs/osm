"""machine_config.med_3_station.yaml regression test (spec11 Part 2) --
exercises dual reject routing (watches:) on top of Part 1's N-cameras-
per-station generality. Structural/schema-level checks; the actual routing
behavior (s1-fail pulled at r1, s2/s3-fail pulled at r2) is exercised
against the dispatcher directly in test_dual_reject_routing.py."""

from pathlib import Path

from app.config.config_loader import resolve_config_for_part

MED_3_STATION_CONFIG_PATH = Path(__file__).parent.parent / "app" / "config" / "machine_config.med_3_station.yaml"


def test_med_3_station_resolves_cleanly():
    resolved = resolve_config_for_part("M3S-001", config_path=MED_3_STATION_CONFIG_PATH)

    assert resolved.part_name == "Med 3-Station"
    assert resolved.indexer.n_slots > 0


def test_med_3_station_has_three_inspection_stations_two_cameras_each():
    resolved = resolve_config_for_part("M3S-001", config_path=MED_3_STATION_CONFIG_PATH)

    inspection_stations = resolved.inspection_stations()
    assert [s.id for s in inspection_stations] == ["s1", "s2", "s3"]
    for station in inspection_stations:
        assert len(station.cameras) == 2
    assert len(resolved.cameras()) == 6


def test_med_3_station_has_two_reject_stations_with_disjoint_watches():
    resolved = resolve_config_for_part("M3S-001", config_path=MED_3_STATION_CONFIG_PATH)

    rejects = resolved.reject_stations()
    assert [r.id for r in rejects] == ["r1", "r2"]  # ring order: r1 (600) before r2 (1700)
    assert rejects[0].watches == ["s1"]
    assert rejects[1].watches == ["s2", "s3"]
    assert set(rejects[0].watches).isdisjoint(rejects[1].watches)  # med-3-station's own layout doesn't overlap
    assert all(r.enabled for r in rejects)


def test_med_3_station_reject_stations_sit_before_exit_in_ring_order():
    resolved = resolve_config_for_part("M3S-001", config_path=MED_3_STATION_CONFIG_PATH)

    exit_station = resolved.exit_station()
    for reject in resolved.reject_stations():
        assert reject.station_offset_pulses < exit_station.station_offset_pulses
