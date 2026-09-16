"""Verifies StationRegistry.build_from_config()'s camera reconnect/reuse
lifecycle: a camera whose config actually changed (or was dropped) between
reloads must have its old driver closed before being replaced/dropped, or
each reload leaks one real device handle -- but a camera whose config is
IDENTICAL to what's already connected must be left alone entirely, not
torn down and reconnected for no reason (found live 2026-09-16: this used
to happen on every single session start, even back-to-back on the same
part). Uses a fake CameraDriver -- no arena_api or real hardware needed.
"""

from unittest.mock import patch

from app.camera.camera_driver import CameraDriver
from app.camera.station_registry import CameraStation, StationRegistry, real_frame_provider
from app.config.config_loader import (
    CameraConfig,
    CameraSimConfig,
    InspectionStation,
    ROIConfig,
    ResolutionConfig,
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


def make_station(camera_id: str, station_id: str, ip: str = "10.0.0.1") -> InspectionStation:
    camera_config = CameraConfig(
        ip=ip,
        vendor="fake",
        resolution=ResolutionConfig(x=640, y=480),
        roi=ROIConfig(x1=0, y1=0, x2=640, y2=480),
        sim=CameraSimConfig(enabled=False),  # non-sim -- real_frame_provider() path
    )
    return InspectionStation(
        id=station_id,
        name=f"Station {station_id}",
        station_offset_pulses=0,
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


def test_reload_same_camera_reuses_connection_when_config_unchanged():
    """2026-09-16 follow-up: an unchanged config (same part started twice in
    a row, nothing reselected) must NOT pay for a reconnect at all --
    build_from_config() keeps the existing CameraStation, and
    real_frame_provider(existing_driver=...) (the same call shape
    inspection_session.py's camera loop uses) reuses its still-open driver
    instead of opening a new one."""
    FakeCameraDriver.reset()
    registry = StationRegistry()

    with patch("app.camera.driver_registry.get_driver_class", return_value=FakeCameraDriver):
        for _ in range(10):
            config = FakeResolvedConfig([make_station("cam1", "s1")])
            registry.build_from_config(config)
            station = registry.get("cam1")
            provide, driver = real_frame_provider(
                "cam1",
                config.inspection_stations()[0].cameras["cam1"],
                existing_driver=station.driver,
            )
            station.set_frame_provider(provide)
            station.set_driver(driver)

    # Config never changed across the 10 reloads -- exactly one real
    # connect, zero reconnects/closes until teardown.
    assert FakeCameraDriver.open_count == 1
    assert FakeCameraDriver.close_count == 0

    registry.close_all()
    assert FakeCameraDriver.open_count == FakeCameraDriver.close_count == 1


def test_reload_with_changed_camera_config_reconnects_without_leaking():
    """The original leak-fix guarantee still holds when a camera's config
    actually changes between reloads (e.g. different IP) -- each such
    reload must close the previous driver before reconnecting, never just
    orphan it."""
    FakeCameraDriver.reset()
    registry = StationRegistry()

    with patch("app.camera.driver_registry.get_driver_class", return_value=FakeCameraDriver):
        for ip in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
            config = FakeResolvedConfig([make_station("cam1", "s1", ip=ip)])
            registry.build_from_config(config)
            station = registry.get("cam1")
            provide, driver = real_frame_provider(
                "cam1",
                config.inspection_stations()[0].cameras["cam1"],
                existing_driver=station.driver,
            )
            station.set_frame_provider(provide)
            station.set_driver(driver)

    # Config changed every time -- each reload must reconnect, and
    # build_from_config() must have closed the previous driver first.
    assert FakeCameraDriver.open_count == 3
    assert FakeCameraDriver.close_count >= 2

    registry.close_all()
    assert FakeCameraDriver.open_count == FakeCameraDriver.close_count == 3


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


def test_is_connected_reflects_driver_liveness_not_capture_staleness():
    """The 2026-09-16 fix: CameraStation.is_connected() for a real camera
    must delegate to the driver's own liveness probe, not infer
    disconnection from how recently it last captured a frame -- a real
    station's capture cadence tracks part feed rate/RPM, not link health,
    so it was never a valid proxy (that's what caused the false
    "disconnected" toast)."""
    FakeCameraDriver.reset()
    station = CameraStation("cam1", "s1")

    # Never connected -- no driver at all yet.
    assert station.is_connected() is False

    driver = FakeCameraDriver("cam1", None)
    driver.connect()
    station.set_driver(driver)
    assert station.is_connected() is True

    # No capture ever recorded (last_capture_ts stays None) -- still
    # "connected" per the driver. The old staleness heuristic would have
    # reported False here even though the camera is fully live, simply
    # because it hasn't been triggered yet.
    assert station.last_capture_ts is None
    assert station.is_connected() is True

    # Driver reports the link is actually down -- station follows
    # immediately, with no staleness window to wait out.
    driver.close()
    assert station.is_connected() is False


def test_is_connected_for_sim_camera_ignores_driver_and_capture_timing():
    """A sim camera has no physical link to lose -- "connected" only ever
    means "configured and ready," same as is_initialized(), regardless of
    capture timing or driver state (sim cameras never get a real driver)."""
    station = CameraStation("cam1", "s1")
    station.set_frame_provider(lambda slot_id=None: None, is_sim=True)
    assert station.is_connected() is True
