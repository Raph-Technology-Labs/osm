"""Verifies the camera-handle leak fix from earlier tonight:
StationRegistry.build_from_config() must close a camera's existing driver
before replacing/dropping it on reload (session restart / part reselect),
otherwise each reload leaks one real device handle. Uses a fake
CameraDriver -- no arena_api or real hardware needed.
"""

from unittest.mock import patch

from app.camera.camera_driver import CameraDriver
from app.camera.station_registry import StationRegistry, real_frame_provider
from app.config.config_loader import (
    CameraConfig,
    CameraSimConfig,
    InspectionStation,
    ROIConfig,
    ResolutionConfig,
    StationSourceConfig,
)


class FakeCameraDriver(CameraDriver):
    """Tracks open handles via a class-level counter -- open_count minus
    close_count is the number of handles currently leaked, if any."""

    open_count = 0
    close_count = 0

    def __init__(self, camera_id, config):
        super().__init__(camera_id, config)
        self._connected = False

    def connect(self):
        self._connected = True
        FakeCameraDriver.open_count += 1

    def read_frame(self):
        import numpy as np

        return np.zeros((4, 4, 3), dtype="uint8")

    def close(self):
        if self._connected:
            self._connected = False
            FakeCameraDriver.close_count += 1

    def is_connected(self):
        return self._connected

    @classmethod
    def reset(cls):
        cls.open_count = 0
        cls.close_count = 0


def make_station(camera_id: str, station_id: str) -> InspectionStation:
    camera_config = CameraConfig(
        ip="10.0.0.1",
        vendor="fake",
        resolution=ResolutionConfig(x=640, y=480),
        roi=ROIConfig(x1=0, y1=0, x2=640, y2=480),
        sim=CameraSimConfig(enabled=False),  # non-sim -- real_frame_provider() path
    )
    return InspectionStation(
        id=station_id,
        name=f"Station {station_id}",
        station_offset_pulses=0,
        source=StationSourceConfig(type="simulation", sim_interval_ms=1000),
        cameras={camera_id: camera_config},
        # InspectionPipeline requires at least one of defect/measurement --
        # this test never calls read_frame() through the pipeline (only
        # connect()/close() lifecycle matters), so an empty-but-valid
        # measurement block is enough to satisfy the model.
        pipeline={"measurement": {"allowed_cameras": [], "allowed_classes": []}},
    )


class FakeResolvedConfig:
    """Minimal stand-in for ResolvedMachineConfig -- build_from_config()
    only calls .inspection_stations()."""

    def __init__(self, stations):
        self._stations = stations

    def inspection_stations(self):
        return self._stations


def test_reload_same_camera_does_not_leak_handles():
    FakeCameraDriver.reset()
    registry = StationRegistry()

    with patch("app.camera.driver_registry.get_driver_class", return_value=FakeCameraDriver):
        for _ in range(10):
            config = FakeResolvedConfig([make_station("cam1", "s1")])
            registry.build_from_config(config)
            provide, driver = real_frame_provider("cam1", config.inspection_stations()[0].cameras["cam1"])
            registry.get("cam1").set_frame_provider(provide)
            registry.get("cam1").set_driver(driver)

    # 10 reloads -> 10 opens. Each reload's build_from_config() must have
    # closed the *previous* iteration's driver before this one replaced it,
    # so closes should be 9 (all but the current, still-open one) at minimum,
    # and never fall behind opens by more than 1.
    assert FakeCameraDriver.open_count == 10
    assert FakeCameraDriver.close_count >= 9

    registry.close_all()
    assert FakeCameraDriver.open_count == FakeCameraDriver.close_count == 10


def test_camera_dropped_from_new_config_gets_closed():
    FakeCameraDriver.reset()
    registry = StationRegistry()

    with patch("app.camera.driver_registry.get_driver_class", return_value=FakeCameraDriver):
        config_a = FakeResolvedConfig([make_station("cam1", "s1")])
        registry.build_from_config(config_a)
        provide, driver = real_frame_provider("cam1", config_a.inspection_stations()[0].cameras["cam1"])
        registry.get("cam1").set_frame_provider(provide)
        registry.get("cam1").set_driver(driver)

        # New config no longer has cam1 at all (topology changed) --
        # build_from_config must close it, not just silently orphan it.
        config_b = FakeResolvedConfig([make_station("cam2", "s2")])
        registry.build_from_config(config_b)

    assert FakeCameraDriver.open_count == 1
    assert FakeCameraDriver.close_count == 1
    assert "cam1" not in [s.camera_id for s in registry.all_stations()]
