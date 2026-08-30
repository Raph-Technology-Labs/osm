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
from typing import Callable, Dict, Optional

import cv2
import numpy as np

log = logging.getLogger("station_registry")

SIM_IMAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sim")

FrameProvider = Callable[[], "CapturedFrame"]


@dataclass
class CapturedFrame:
    frame: np.ndarray
    # Ground truth from the simulator, standing in for a real defect model's
    # verdict since no trained weights exist in this repo yet (MockDefectModel).
    is_defect: bool
    defect_label: Optional[str] = None


def sim_frame_provider(camera_id: str, defect_rate: float = 0.10) -> FrameProvider:
    """Cycles the generated sample images for this camera. ~defect_rate of
    captures return the defective sample -- approximates the demo's "2 of 20
    defective" scenario without needing real inference."""
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
