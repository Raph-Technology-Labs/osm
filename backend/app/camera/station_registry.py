"""N-camera-ready station registry. Keyed by camera_id, built from the
resolved config's stations -- adding a 3rd/4th camera later is a config
change, not a code change (gcm's CameraManager hardcodes a single device;
this doesn't).

Two frame providers: sim_frame_provider() (folder-glob mock/sample images)
and real_frame_provider() (real hardware via app.camera.driver_registry --
Lucid today, any future vendor via the same CameraDriver contract).
Both return the same FrameProvider shape so set_frame_provider() never needs
to know which one it got.
"""

from __future__ import annotations

import glob
import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Dict, Optional, Tuple, Iterator
from contextlib import contextmanager
from plc import ModbusPLCClient
import cv2
import numpy as np
from app.plc import ModbusPLCClient
from app.camera.camera_driver import CameraConnectionError

if TYPE_CHECKING:
    from app.camera.camera_driver import CameraDriver
    from app.config.config_loader import CameraConfig, DefectConfig, MeasurementConfig

log = logging.getLogger("station_registry")

SIM_IMAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sim")
# backend/data -- machine_config.yaml's sim.image_path uses container-style
# absolute paths (e.g. /data/sim/cats/cat1.jpg), same convention as
# pipeline.model_registry.MODELS_ROOT for /models/... paths.
SIM_DATA_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "data")

FrameProvider = Callable[[], "CapturedFrame"]


def resolve_sim_image_path(image_path: str) -> str:
    if image_path.startswith("/data/"):
        return os.path.join(SIM_DATA_ROOT, image_path[len("/data/"):])
    return image_path


# Every extension OpenCV's imread() can decode (see the OpenCV imgcodecs
# docs) -- used when sim.image_path is a directory, so "drop any image
# format in this folder" actually holds.
IMAGE_EXTENSIONS = (
    "bmp", "dib",
    "jpg", "jpeg", "jpe", "jp2",
    "png",
    "webp",
    "pbm", "pgm", "ppm", "pxm", "pnm",
    "sr", "ras",
    "tiff", "tif",
    "exr",
    "hdr", "pic",
)


@dataclass
class CapturedFrame:
    frame: np.ndarray
    # True = NOK. Real defect/measurement verdict when image_path + a
    # pipeline block are configured (see sim_frame_provider); otherwise the
    # random good/defect glob-cycling mock's ground truth.
    is_defect: bool
    # Defect class name (defect stations) or "⌀X.XXmm" (measurement
    # stations) -- just a display string, not defect-specific despite the
    # field name (kept to avoid a wire-schema change in zeromq.publish_inspection_result).
    defect_label: Optional[str] = None
    # Structured detail for the Inspection page's live per-camera cards and
    # for CameraResult persistence (app/services/results_writer.py) -- None
    # on a plain pass-through capture (no pipeline configured).
    defect_confidence: Optional[float] = None
    defect_count: int = 0
    # {"diameter_mm": {"nominal": .., "upper_limit": .., "lower_limit": ..,
    #  "measured": .., "unit": "mm", "passed": bool}} -- shape matches
    # CameraResult.measurement_data's own documented shape (models.py).
    measurement_data: Optional[dict] = None


def _run_pipeline(
    frame: np.ndarray,
    defect_config: Optional["DefectConfig"],
    measurement_config: Optional["MeasurementConfig"],
    draw_result: bool,
) -> CapturedFrame:
    """Shared by sim_frame_provider's image_path branch and
    real_frame_provider -- runs whichever pipeline block is configured and
    builds a CapturedFrame with both the display label (defect_label, kept
    for the existing ZMQ wire shape) and the structured detail
    (defect_confidence/defect_count/measurement_data) the Inspection page's
    live per-camera cards and results_writer.py need."""
    if defect_config is not None:
        from app.pipeline.defect import run_defect_inference  # deferred: avoids importing
        # ultralytics for stations that never run inference

        is_defect, label, confidence, count, frame_out = run_defect_inference(frame, defect_config, draw_result)
        return CapturedFrame(
            frame=frame_out,
            is_defect=is_defect,
            defect_label=label,
            defect_confidence=confidence,
            defect_count=count,
        )
    if measurement_config is not None:
        from app.pipeline.measurement import run_measurement_inference  # deferred, same reason

        result = run_measurement_inference(frame, measurement_config, draw_result)
        label = f"⌀{result.diameter_mm:.2f}mm oval {result.ovality_mm:.2f}mm"
        # Matches run_measurement_inference's own hardcoded "diameter_mm"
        # param lookup -- not generalizing to other param names here since
        # the pipeline itself doesn't calibrate/check any others yet.
        param = measurement_config.parameters.get("diameter_mm")
        measurement_data = {
            "diameter_mm": {
                "nominal": param.nominal_value if param else None,
                "upper_limit": param.upper_limit if param else None,
                "lower_limit": param.lower_limit if param else None,
                "measured": result.diameter_mm,
                "unit": param.unit if param else "mm",
                "passed": result.passed,
            }
        }
        return CapturedFrame(
            frame=result.frame_out,
            is_defect=not result.passed,
            defect_label=label,
            measurement_data=measurement_data,
        )
    return CapturedFrame(frame=frame, is_defect=False, defect_label=None)


def sim_frame_provider(
    camera_id: str,
    image_path: Optional[str] = None,
    defect_config: Optional["DefectConfig"] = None,
    measurement_config: Optional["MeasurementConfig"] = None,
    draw_result: bool = True,
    defect_rate: float = 0.10,
) -> FrameProvider:
    """If image_path is set (cameras.<id>.sim.image_path in
    machine_config.yaml), every capture loads a configured image, then runs
    real inference against a real loaded model (never a mock):
      - defect_config set (camera_id in its allowed_cameras) ->
        app.pipeline.defect.run_defect_inference
      - measurement_config set (camera_id in its allowed_cameras) ->
        app.pipeline.measurement.run_measurement_inference
      - neither -> plain pass-through, always OK, no label
    draw_result controls whether the returned frame has boxes/contour/
    diameter overlays drawn on it (mirrors pipeline.result.draw_result).

    image_path may point at a single file (always that one image) or a
    directory (every capture globs every OpenCV-readable image extension --
    IMAGE_EXTENSIONS below -- in it and picks one at random, so a session
    cycles through the whole folder instead of one fixed frame).

    Falls back to the earlier random good/defect glob-cycling mock when no
    image_path is configured, so cameras without an explicit sim image keep
    the "~defect_rate of captures defective" demo behavior.
    """
    if image_path:
        resolved_path = resolve_sim_image_path(image_path)
        if os.path.isdir(resolved_path):
            image_paths = sorted(
                {
                    p
                    for ext in IMAGE_EXTENSIONS
                    for p in glob.glob(os.path.join(resolved_path, f"*.{ext}"))
                    + glob.glob(os.path.join(resolved_path, f"*.{ext.upper()}"))
                }
            )
            if not image_paths:
                raise FileNotFoundError(
                    f"sim.image_path for {camera_id} has no readable images "
                    f"({', '.join(IMAGE_EXTENSIONS)}) under: {resolved_path}"
                )
        elif os.path.isfile(resolved_path):
            image_paths = [resolved_path]
        else:
            raise FileNotFoundError(f"sim.image_path for {camera_id} not found: {resolved_path}")

        def provide() -> CapturedFrame:
            frame = cv2.imread(random.choice(image_paths))
            return _run_pipeline(frame, defect_config, measurement_config, draw_result)

        return provide

    good_paths = sorted(glob.glob(os.path.join(SIM_IMAGE_DIR, f"{camera_id}_good_*.jpg")))
    defect_paths = sorted(glob.glob(os.path.join(SIM_IMAGE_DIR, f"{camera_id}_defect_*.jpg")))
    if not good_paths:
        raise FileNotFoundError(f"No sim images found for {camera_id} under {SIM_IMAGE_DIR}")

    def provide() -> CapturedFrame:
        use_defect = defect_paths and random.random() < defect_rate
        path = random.choice(defect_paths) if use_defect else random.choice(good_paths)
        frame = cv2.imread(path)
        return CapturedFrame(frame=frame, is_defect=bool(use_defect), defect_label="scratch" if use_defect else None)

    return provide


def real_frame_provider(
    camera_id: str,
    camera_config: "CameraConfig",
    defect_config: Optional["DefectConfig"] = None,
    measurement_config: Optional["MeasurementConfig"] = None,
    draw_result: bool = True,
) -> Tuple[FrameProvider, "CameraDriver"]:
    """Real-hardware sibling of sim_frame_provider(). Looks up the right
    CameraDriver by camera_config.vendor (driver_registry.py), connects
    once, and returns a zero-arg provide() that pulls one frame per call and
    runs the exact same real defect/measurement inference sim_frame_provider
    runs above -- only the frame source differs.

    Raises CameraConnectionError if the device can't be reached -- callers
    (start_session) must catch this and leave the station uninitialized
    rather than crash session start over one bad camera (CLAUDE.md's
    camera-disconnect-mid-session rule)."""
    from app.camera.driver_registry import get_driver_class

    driver = get_driver_class(camera_config.vendor)(camera_id, camera_config)
    driver.connect()  # raises CameraConnectionError -- caller's problem

    def provide() -> CapturedFrame:
        frame = driver.read_frame()
        return _run_pipeline(frame, defect_config, measurement_config, draw_result)

    return provide, driver


class CameraStation:
    def __init__(self, camera_id: str, station_id: str, strobe_reg: Optional[int]):
        self.camera_id = camera_id
        self.station_id = station_id
        self.zmq_topic = f"MessageType.CameraFeed.{camera_id}"
        self._frame_provider: Optional[FrameProvider] = None
        # Only set for real (non-sim) cameras -- tracked so close() can
        # release the physical device on session teardown/app shutdown.
        self.driver: Optional["CameraDriver"] = None
        self.on_result: Optional[Callable[[str, CapturedFrame], None]] = None
        # Health Check page reads these -- "initialized" = frame provider
        # set, "connected" = produced a capture recently (see is_connected()).
        self.last_capture_ts: Optional[float] = None
        self.last_capture_ok: Optional[bool] = None
        self.strobe_reg = strobe_reg
        self.plc = ModbusPLCClient  # type: ignore
    def is_initialized(self) -> bool:
        return self._frame_provider is not None

    def is_connected(self, staleness_threshold_s: float = 10.0) -> bool:
        if self.last_capture_ts is None:
            return False
        return (time.time() - self.last_capture_ts) < staleness_threshold_s

    def set_frame_provider(self, provider: FrameProvider) -> None:
        self._frame_provider = provider

    def set_driver(self, driver: "CameraDriver") -> None:
        self.driver = driver

    # def fire_strobe(self, duration_ms: int = 2) -> None:
    #     if self.strobe_reg is None:
    #         log.warning(f"{self.camera_id}: strobe_reg not configured, can't fire strobe")
    #         return None
    #     try:
    #         self.plc.write_register(self.strobe_reg, duration_ms)
    #         time.sleep(duration_ms / 1000.0)
    #         try:
    #             self.plc.write_register(self.strobe_reg, 0)
    #         except Exception as e:
    #             log.warning(f"{self.camera_id}: failed to reset strobe at reg {self.strobe_reg}: {e}", exc_info=True)
    #     except Exception as e:
    #         log.warning(f"{self.camera_id}: failed to fire strobe at reg {self.strobe_reg}: {e}", exc_info=True)
    @contextmanager
    def fire_strobe(self, duration_ms: int = 2) -> Iterator[None]:
        if self.strobe_reg is None:
            log.warning(
                f"{self.camera_id}: strobe_reg not configured, can't fire strobe"
            )
            yield
            return

        try:
            self.plc.write_register(self.strobe_reg, 1)
            yield
        finally:
            try:
                self.plc.write_register(self.strobe_reg, 0)
            except Exception as e:
                log.warning(
                    f"{self.camera_id}: failed to reset strobe "
                    f"at reg {self.strobe_reg}: {e}",
                    exc_info=True,
                )


    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
            self.driver = None

    # def capture_and_infer(self) -> Optional[CapturedFrame]:
    #     """Runs on its own thread per firing -- captures one frame and
    #     returns the inference result. A real camera that never connected, or
    #     that disconnects mid-session, is logged and marks the station
    #     unavailable rather than crashing this thread (CLAUDE.md's
    #     camera-disconnect-mid-session rule)."""
    #     if self._frame_provider is None:
    #         log.warning(f"{self.camera_id}: fired with no frame provider set (not connected) -- skipping")
    #         return None
    #     try:
    #         self.fire_strobe(2)
    #         captured = self._frame_provider()
    #     except CameraConnectionError:
    #         log.warning(f"{self.camera_id}: capture failed, marking disconnected", exc_info=True)
    #         self.last_capture_ok = False
    #         return None
    #     self.last_capture_ts = time.time()
    #     self.last_capture_ok = True
    #     if self.on_result:
    #         self.on_result(self.camera_id, captured)
    #     return captured
    def capture_and_infer(self) -> Optional[CapturedFrame]:
        if self._frame_provider is None:
            log.warning(
                f"{self.camera_id}: fired with no frame provider set "
                f"(not connected) -- skipping"
            )
            return None

        try:
            with self.fire_strobe():
                captured = self._frame_provider()

        except CameraConnectionError:
            log.warning(
                f"{self.camera_id}: capture failed, marking disconnected",
                exc_info=True,
            )
            self.last_capture_ok = False
            return None

        self.last_capture_ts = time.time()
        self.last_capture_ok = True

        if self.on_result:
            self.on_result(self.camera_id, captured)

        return captured


class StationRegistry:
    def __init__(self):
        """Create an empty registry keyed by camera ID."""
        self._stations: Dict[str, CameraStation] = {}

    def build_from_config(self, resolved_config) -> None:
        """Create and register one CameraStation for each configured camera.
        Reconciles against whatever was already registered -- closing a real
        camera's device handle before replacing or dropping it is mandatory
        here, since this runs again on every session start / part reselect,
        not just once at boot. Without this, each reload replaces
        CameraStation objects with fresh ones while the old ones' still-open
        LucidCamera driver handles become unreferenced and never released --
        one leaked Arena SDK device handle per reload."""
        new_camera_ids = {
            camera_id
            for station in resolved_config.inspection_stations()
            for camera_id in station.cameras
        }
        # Camera no longer present in the new config (topology changed on
        # part reselect) -- close it now, nothing below will touch it again.
        for camera_id in list(self._stations):
            if camera_id not in new_camera_ids:
                self._stations.pop(camera_id).close()

        for station in resolved_config.inspection_stations():
            for camera_id in station.cameras:
                existing = self._stations.get(camera_id)
                if existing is not None:
                    existing.close()
                self._stations[camera_id] = CameraStation(camera_id, station.id, station.strobe_reg)

    def stations_for_station(self, station_id: str) -> list[CameraStation]:
        """Return all camera stations belonging to the given station ID."""
        return [s for s in self._stations.values() if s.station_id == station_id]

    def all_stations(self) -> list[CameraStation]:
        """Return every registered camera station."""
        return list(self._stations.values())

    def get(self, camera_id: str) -> CameraStation:
        """Return the camera station registered under the given camera ID."""
        return self._stations[camera_id]

    def fire_station(self, station_id: str) -> None:
        """Fires all cameras for a station, each on its own thread -- matches
        gcm's threading (not multiprocessing) pattern for the vision pipeline."""
        for station in self.stations_for_station(station_id):
            threading.Thread(target=station.capture_and_infer, daemon=True).start()

    def close_all(self) -> None:
        """Release every real camera's device -- app shutdown / session teardown."""
        for station in self._stations.values():
            station.close()


_registry: Optional[StationRegistry] = None


def get_station_registry() -> StationRegistry:
    global _registry
    if _registry is None:
        _registry = StationRegistry()
    return _registry
