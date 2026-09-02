"""N-camera-ready station registry. Keyed by camera_id, built from the
resolved config's triggers -- adding a 3rd/4th camera later is a config
change, not a code change (gcm's CameraManager hardcodes a single device;
this doesn't).

Today's demo scope wires the sim frame provider only (no real Arena-SDK-style
camera integration exists in this repo yet) -- but set_frame_provider() is
the swap seam for that later, lifted from gcm's InferenceEngine pattern.
"""

from __future__ import annotations

import glob
import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Dict, Optional

import cv2
import numpy as np

if TYPE_CHECKING:
    from app.config.config_loader import DefectConfig, MeasurementConfig

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
            if defect_config is not None:
                from app.pipeline.defect import run_defect_inference  # deferred: avoids importing
                # ultralytics for stations that never run inference

                is_defect, label, frame_out = run_defect_inference(frame, defect_config, draw_result)
                return CapturedFrame(frame=frame_out, is_defect=is_defect, defect_label=label)
            if measurement_config is not None:
                from app.pipeline.measurement import run_measurement_inference  # deferred, same reason

                result = run_measurement_inference(frame, measurement_config, draw_result)
                label = f"⌀{result.diameter_mm:.2f}mm oval {result.ovality_mm:.2f}mm"
                return CapturedFrame(frame=result.frame_out, is_defect=not result.passed, defect_label=label)
            return CapturedFrame(frame=frame, is_defect=False, defect_label=None)

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


class CameraStation:
    def __init__(self, camera_id: str, trigger_id: str):
        self.camera_id = camera_id
        self.trigger_id = trigger_id
        self.zmq_topic = f"MessageType.CameraFeed.{camera_id}"
        self._frame_provider: Optional[FrameProvider] = None
        self.on_result: Optional[Callable[[str, CapturedFrame], None]] = None
        # Health Check page reads these -- "initialized" = frame provider
        # set, "connected" = produced a capture recently (see is_connected()).
        self.last_capture_ts: Optional[float] = None
        self.last_capture_ok: Optional[bool] = None

    def is_initialized(self) -> bool:
        return self._frame_provider is not None

    def is_connected(self, staleness_threshold_s: float = 10.0) -> bool:
        if self.last_capture_ts is None:
            return False
        return (time.time() - self.last_capture_ts) < staleness_threshold_s

    def set_frame_provider(self, provider: FrameProvider) -> None:
        self._frame_provider = provider

    def capture_and_infer(self) -> CapturedFrame:
        """Runs on its own thread per firing -- captures one frame and
        returns the (mocked) inference result. A real defect/measurement
        pipeline slots in here later without changing the caller's contract."""
        if self._frame_provider is None:
            raise RuntimeError(f"{self.camera_id} has no frame provider set")
        captured = self._frame_provider()
        self.last_capture_ts = time.time()
        self.last_capture_ok = True
        if self.on_result:
            self.on_result(self.camera_id, captured)
        return captured


class StationRegistry:
    def __init__(self):
        self._stations: Dict[str, CameraStation] = {}

    def build_from_config(self, resolved_config) -> None:
        for trig in resolved_config.inspection_triggers():
            for camera_id in trig.cameras:
                self._stations[camera_id] = CameraStation(camera_id, trig.id)

    def stations_for_trigger(self, trigger_id: str) -> list[CameraStation]:
        return [s for s in self._stations.values() if s.trigger_id == trigger_id]

    def all_stations(self) -> list[CameraStation]:
        return list(self._stations.values())

    def get(self, camera_id: str) -> CameraStation:
        return self._stations[camera_id]

    def fire_trigger(self, trigger_id: str) -> None:
        """Fires all cameras for a trigger, each on its own thread -- matches
        gcm's threading (not multiprocessing) pattern for the vision pipeline."""
        for station in self.stations_for_trigger(trigger_id):
            threading.Thread(target=station.capture_and_infer, daemon=True).start()


_registry: Optional[StationRegistry] = None


def get_station_registry() -> StationRegistry:
    global _registry
    if _registry is None:
        _registry = StationRegistry()
    return _registry
