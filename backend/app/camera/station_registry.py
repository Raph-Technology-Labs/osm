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
from typing import TYPE_CHECKING, Callable, Dict, Optional, Tuple

import cv2
import numpy as np

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

FrameProvider = Callable[[Optional[int]], "CapturedFrame"]


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
    forced_verdict: Optional[str] = None,
) -> CapturedFrame:
    """Shared by sim_frame_provider's image_path branch and
    real_frame_provider -- runs whichever pipeline block is configured and
    builds a CapturedFrame with both the display label (defect_label, kept
    for the existing ZMQ wire shape) and the structured detail
    (defect_confidence/defect_count/measurement_data) the Inspection page's
    live per-camera cards and results_writer.py need.

    forced_verdict ("OK"/"NOK"/None) is the sim verification harness's
    deterministic-verdict override (machine_config.yaml's top-level sim:
    block, IndexerSlotTracker.seed_sim) -- ONLY consulted on the
    defect_config path (s2), never measurement (s1 keeps using real
    inference against the real calibrated sim images, per this feature's
    frozen spec). None in real/hardware mode -- real_frame_provider never
    passes a non-None value, so this branch is simply dead code there.

    defect_config and measurement_config are not mutually exclusive -- a
    "cmd" camera (config_loader.InspectionPipeline.cmd_cameras(): in both
    blocks' allowed_cameras, the measurement_shares_defect_model() case)
    gets BOTH passed here for the same capture. Previously the defect
    branch returned immediately, so measurement never ran on a shared
    camera at all (found in spec13's review, #5). Now defect inference (or
    its forced_verdict) runs first as before, then -- if measurement_config
    is also set -- measurement runs against the defect stage's own output
    frame (so any drawn defect boxes and the measurement ellipse both land
    on the one returned frame, not two independent copies), and the two
    verdicts combine: NOK if either fails."""
    defect_result: Optional[CapturedFrame] = None
    working_frame = frame

    if defect_config is not None:
        if forced_verdict is not None:
            is_nok = forced_verdict == "NOK"
            defect_result = CapturedFrame(
                frame=frame,
                is_defect=is_nok,
                defect_label="sim_forced_nok" if is_nok else None,
                defect_confidence=None,
                defect_count=1 if is_nok else 0,
            )
        else:
            from app.pipeline.defect import run_defect_inference  # deferred: avoids importing
            # ultralytics for stations that never run inference

            is_defect, label, confidence, count, frame_out = run_defect_inference(frame, defect_config, draw_result)
            defect_result = CapturedFrame(
                frame=frame_out,
                is_defect=is_defect,
                defect_label=label,
                defect_confidence=confidence,
                defect_count=count,
            )
        working_frame = defect_result.frame
        if measurement_config is None:
            return defect_result

    if measurement_config is not None:
        from app.pipeline.measurement import run_measurement_inference  # deferred, same reason

        result = run_measurement_inference(working_frame, measurement_config, draw_result)
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
        if defect_result is not None:
            # Shared camera: combine both verdicts rather than letting
            # measurement silently overwrite defect's (or vice versa).
            combined_label = f"{defect_result.defect_label} | {label}" if defect_result.defect_label else label
            return CapturedFrame(
                frame=result.frame_out,
                is_defect=defect_result.is_defect or not result.passed,
                defect_label=combined_label,
                defect_confidence=defect_result.defect_confidence,
                defect_count=defect_result.defect_count,
                measurement_data=measurement_data,
            )
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
    indexer_tracker=None,
    sim_verdict_enabled: bool = False,
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

        def provide(slot_id: Optional[int] = None) -> CapturedFrame:
            frame = cv2.imread(random.choice(image_paths))
            forced_verdict = None
            if sim_verdict_enabled and indexer_tracker is not None and slot_id is not None and defect_config is not None:
                forced_verdict = indexer_tracker.get_slot(slot_id).forced_verdict
            return _run_pipeline(frame, defect_config, measurement_config, draw_result, forced_verdict=forced_verdict)

        return provide

    good_paths = sorted(glob.glob(os.path.join(SIM_IMAGE_DIR, f"{camera_id}_good_*.jpg")))
    defect_paths = sorted(glob.glob(os.path.join(SIM_IMAGE_DIR, f"{camera_id}_defect_*.jpg")))
    if not good_paths:
        raise FileNotFoundError(f"No sim images found for {camera_id} under {SIM_IMAGE_DIR}")

    def provide(slot_id: Optional[int] = None) -> CapturedFrame:
        # No image_path configured -- the older random glob-cycling mock,
        # predates forced_verdict and doesn't call _run_pipeline/defect_config
        # at all. Not exercised by today's config (both real stations set
        # image_path), left as-is rather than retrofit sim-verdict support
        # into a fallback path nothing currently uses.
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

    def provide(slot_id: Optional[int] = None) -> CapturedFrame:
        # slot_id accepted (matches FrameProvider's signature) but
        # deliberately unused -- real hardware always runs real inference,
        # unconditionally. forced_verdict is intentionally NOT threaded in
        # here (unlike sim_frame_provider) so a real camera's verdict can
        # never be overridden by sim config, even by accident.
        frame = driver.read_frame()
        return _run_pipeline(frame, defect_config, measurement_config, draw_result)

    return provide, driver


class CameraStation:
    def __init__(self, camera_id: str, station_id: str):
        self.camera_id = camera_id
        self.station_id = station_id
        self.zmq_topic = f"MessageType.CameraFeed.{camera_id}"
        self._frame_provider: Optional[FrameProvider] = None
        # Only set for real (non-sim) cameras -- tracked so close() can
        # release the physical device on session teardown/app shutdown.
        self.driver: Optional["CameraDriver"] = None
        self.on_result: Optional[Callable[[str, CapturedFrame, Optional[int], Optional[object]], None]] = None
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

    def set_driver(self, driver: "CameraDriver") -> None:
        self.driver = driver

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
            self.driver = None

    def capture_and_infer(self, slot_id: Optional[int] = None, part_id: Optional[object] = None) -> Optional[CapturedFrame]:
        """Runs on its own thread per firing -- captures one frame and
        returns the inference result. A real camera that never connected, or
        that disconnects mid-session, is logged and marks the station
        unavailable rather than crashing this thread (CLAUDE.md's
        camera-disconnect-mid-session rule).

        slot_id/part_id identify which physical ring slot triggered this
        fire (StationDispatcher._tick knows this at fire time) -- threaded
        through to on_result so it can write the eventual async result back
        onto the right IndexerSlotTracker SlotRecord. None for callers that
        don't have ring context (e.g. ad-hoc/manual test captures)."""
        if self._frame_provider is None:
            log.warning(f"{self.camera_id}: fired with no frame provider set (not connected) -- skipping")
            return None
        try:
            captured = self._frame_provider(slot_id)
        except CameraConnectionError:
            log.warning(f"{self.camera_id}: capture failed, marking disconnected", exc_info=True)
            self.last_capture_ok = False
            return None
        self.last_capture_ts = time.time()
        self.last_capture_ok = True
        if self.on_result:
            self.on_result(self.camera_id, captured, slot_id, part_id)
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
                self._stations[camera_id] = CameraStation(camera_id, station.id)

    def stations_for_station(self, station_id: str) -> list[CameraStation]:
        """Return all camera stations belonging to the given station ID."""
        return [s for s in self._stations.values() if s.station_id == station_id]

    def all_stations(self) -> list[CameraStation]:
        """Return every registered camera station."""
        return list(self._stations.values())

    def get(self, camera_id: str) -> CameraStation:
        """Return the camera station registered under the given camera ID."""
        return self._stations[camera_id]

    def fire_station(self, station_id: str, slot_id: Optional[int] = None, part_id: Optional[object] = None) -> None:
        """Fires all cameras for a station, each on its own thread -- matches
        gcm's threading (not multiprocessing) pattern for the vision pipeline.
        slot_id/part_id: see CameraStation.capture_and_infer."""
        for station in self.stations_for_station(station_id):
            threading.Thread(target=station.capture_and_infer, args=(slot_id, part_id), daemon=True).start()

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
