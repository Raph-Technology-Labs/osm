# backend/app/config/config_loader.py
import os
import threading
import yaml
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, model_validator


# ─────────────────────────────────────────────────────────────────
# SHARED INFRA
# ─────────────────────────────────────────────────────────────────

class PLCSimConfig(BaseModel):
    enabled: bool = False
    host: str = "localhost"
    port: int = 5502

class PLCInfraConfig(BaseModel):
    ip: str
    port: int = 502
    sim: PLCSimConfig

    def get_endpoint(self) -> tuple[str, int]:
        return (self.sim.host, self.sim.port) if self.sim.enabled else (self.ip, self.port)

class ZMQConfig(BaseModel):
    port: int

class RedisKeysConfig(BaseModel):
    result: str
    trigger: str

class RedisConfig(BaseModel):
    host: str
    port: int
    keys: RedisKeysConfig

class MachineInfo(BaseModel):
    part_code: str
    part_name: str


# ─────────────────────────────────────────────────────────────────
# CAMERA
# ─────────────────────────────────────────────────────────────────

class CameraResolution(BaseModel):
    x: int
    y: int

class CameraROI(BaseModel):
    x1: int = 0
    y1: int = 0
    x2: int = 1920
    y2: int = 1080

class CameraSimConfig(BaseModel):
    enabled: bool = False
    image_path: Optional[str] = None
    video_path: Optional[str] = None

    def get_source(self) -> Optional[str]:
        return self.image_path or self.video_path

class CameraConfig(BaseModel):
    ip: str
    resolution: CameraResolution
    fps: int
    roi: CameraROI = CameraROI()
    sim: CameraSimConfig = CameraSimConfig()

    def grab_frame(self):
        import cv2
        if self.sim.enabled:
            src = self.sim.get_source()
            if not src:
                raise ValueError("sim.enabled but no image_path or video_path set")
            frame = cv2.imread(src)
            if frame is None:
                raise FileNotFoundError(f"Sim image not found: {src}")
            return frame
        cap = cv2.VideoCapture(self.ip)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            raise RuntimeError(f"Failed to grab frame from {self.ip}")
        return frame


# ─────────────────────────────────────────────────────────────────
# TRIGGER SOURCE + PLC REGISTERS
# ─────────────────────────────────────────────────────────────────

class TriggerSourceConfig(BaseModel):
    type: Literal["simulation", "plc", "ui_button"]
    sim_interval_ms: int = 3000

class TriggerPLCConfig(BaseModel):
    trigger_reg: int
    ok_reg: int
    nok_reg: int
    rejection_reg: Optional[int] = None
    reset_reg: Optional[int] = None


# ─────────────────────────────────────────────────────────────────
# OBJECT DETECTION (locator — nested inside defect / measurement)
# ─────────────────────────────────────────────────────────────────

class ObjectDetectionConfig(BaseModel):
    classes: Dict[str, float]       # { class_name: conf_thresh }
    allowed_classes: List[str]      # which detected classes pass downstream


# ─────────────────────────────────────────────────────────────────
# DEFECT BLOCK
# ─────────────────────────────────────────────────────────────────

class DefectConfig(BaseModel):
    model_path: str
    model_type: Literal["yolo", "nanodet", "onnx", "tensorrt", "torchvision"]
    conf_thresh: float = 0.50
    classes: Dict[str, float]       # { class_name: per_class_conf_thresh }
    allowed_cameras: List[str]
    allowed_classes: List[str]
    object_detection: Optional[ObjectDetectionConfig] = None


# ─────────────────────────────────────────────────────────────────
# MEASUREMENT BLOCK
#
# calibration_factor is per-parameter (not global per camera)
# because vertical vs horizontal px/mm may differ per lens setup
#
# parameters:
#   diameter_mm:
#     calibration_factor: 10.5
#   length_mm:
#     calibration_factor: 10.2
# ─────────────────────────────────────────────────────────────────

class MeasurementParamConfig(BaseModel):
    calibration_factor: float = 10.0  # px per mm for this dimension

class MeasurementConfig(BaseModel):
    method: Literal["caliper", "contour", "ellipse"] = "caliper"
    allowed_cameras: List[str]
    allowed_classes: List[str]
    parameters: Dict[str, MeasurementParamConfig] = {}
    # { param_name: { calibration_factor } }
    # param_name keys must exist in Part.dimensions (DB)
    object_detection: Optional[ObjectDetectionConfig] = None


# ─────────────────────────────────────────────────────────────────
# INSPECTION PIPELINE
# ─────────────────────────────────────────────────────────────────

class PipelineResultConfig(BaseModel):
    pass_if: Literal["all_cameras_pass", "any_camera_pass"] = "all_cameras_pass"

class InspectionPipeline(BaseModel):
    defect: Optional[DefectConfig] = None
    measurement: Optional[MeasurementConfig] = None
    result: PipelineResultConfig = PipelineResultConfig()

    @model_validator(mode="after")
    def at_least_one_block(self):
        if self.defect is None and self.measurement is None:
            raise ValueError("Pipeline must have at least one of: defect | measurement")
        return self

    def cmd_cameras(self) -> set:
        """Cameras in both defect + measurement → serial execution."""
        if not self.defect or not self.measurement:
            return set()
        return set(self.defect.allowed_cameras) & set(self.measurement.allowed_cameras)

    def defect_only_cameras(self) -> set:
        if not self.defect:
            return set()
        return set(self.defect.allowed_cameras) - self.cmd_cameras()

    def measure_only_cameras(self) -> set:
        if not self.measurement:
            return set()
        return set(self.measurement.allowed_cameras) - self.cmd_cameras()

    def all_active_cameras(self) -> set:
        return self.cmd_cameras() | self.defect_only_cameras() | self.measure_only_cameras()


# ─────────────────────────────────────────────────────────────────
# INSPECTION TRIGGER
# ─────────────────────────────────────────────────────────────────

class InspectionTrigger(BaseModel):
    id: str
    name: str
    type: Literal["inspection"] = "inspection"
    source: TriggerSourceConfig
    plc: TriggerPLCConfig
    cameras: Dict[str, CameraConfig]
    pipeline: InspectionPipeline

    @model_validator(mode="after")
    def validate_camera_refs(self):
        registered = set(self.cameras.keys())
        active = self.pipeline.all_active_cameras()
        unknown = active - registered
        if unknown:
            raise ValueError(f"Pipeline references unregistered cameras: {unknown}")
        return self

    def get_camera(self, cam_id: str) -> CameraConfig:
        if cam_id not in self.cameras:
            raise KeyError(f"Camera '{cam_id}' not in trigger '{self.id}'")
        return self.cameras[cam_id]


# ─────────────────────────────────────────────────────────────────
# COUNTING TRIGGER
# ─────────────────────────────────────────────────────────────────

class CountingPLCConfig(BaseModel):
    start_stop: int
    count_out: int
    speeds: Dict[str, int]
    switches: Dict[str, int]
    errors: Dict[str, int]
    hopper_gate: int
    hopper_gate_ack: int

class CountingSpeedRange(BaseModel):
    min: int
    max: int

class ConveyorFSMConfig(BaseModel):
    count_threshold: int = 20
    count_threshold_last: int = 5

class ConveyorConfig(BaseModel):
    line_position: int = 400
    counting_line_y: int = 300
    max_missed: int = 5
    min_movement: int = 5
    fsm: ConveyorFSMConfig = ConveyorFSMConfig()

class CountingCameraConfig(BaseModel):
    id: str
    ip: str
    resolution: CameraResolution
    fps: int
    roi: CameraROI = CameraROI()
    sim: CameraSimConfig = CameraSimConfig()

class CountingPipelineConfig(BaseModel):
    model_path: str
    model_type: Literal["yolo", "nanodet", "onnx", "tensorrt", "torchvision"]
    conf_thresh: float = 0.50
    iou: float = 0.45
    conveyor: Optional[ConveyorConfig] = None

class CountingTrigger(BaseModel):
    id: str
    name: str
    type: Literal["counting"]
    sub_mode: Literal["conveyor", "gcm", "scm", "batch", "bulk"] = "conveyor"
    source: TriggerSourceConfig
    plc: CountingPLCConfig
    speeds: Dict[str, CountingSpeedRange]
    camera: CountingCameraConfig
    pipeline: CountingPipelineConfig

    def get_sub_config(self):
        return getattr(self.pipeline, self.sub_mode, None)


# ─────────────────────────────────────────────────────────────────
# ROOT CONFIG
# ─────────────────────────────────────────────────────────────────

class MachineConfig(BaseModel):
    machine: MachineInfo
    plc: PLCInfraConfig
    zmq: ZMQConfig
    redis: RedisConfig
    triggers: List[dict]

    _cache: dict = {}

    def _parse(self, raw: dict):
        t = raw.get("type", "inspection")
        if t == "inspection":
            return InspectionTrigger(**raw)
        if t == "counting":
            return CountingTrigger(**raw)
        raise ValueError(f"Unknown trigger type: '{t}'")

    def get_trigger(self, trigger_id: str):
        if trigger_id not in self._cache:
            for raw in self.triggers:
                if raw.get("id") == trigger_id:
                    self._cache[trigger_id] = self._parse(raw)
                    break
        return self._cache.get(trigger_id)

    def get_all_triggers(self):
        return [self._parse(t) for t in self.triggers]

    def get_inspection_triggers(self) -> List[InspectionTrigger]:
        return [t for t in self.get_all_triggers() if isinstance(t, InspectionTrigger)]

    def get_counting_triggers(self) -> List[CountingTrigger]:
        return [t for t in self.get_all_triggers() if isinstance(t, CountingTrigger)]

    def get_zmq_address(self, bind: bool = False) -> str:
        return f"{'tcp://*' if bind else 'tcp://localhost'}:{self.zmq.port}"


# ─────────────────────────────────────────────────────────────────
# MODEL REGISTRY — load once, cache forever, thread-safe
# ─────────────────────────────────────────────────────────────────

class ModelRegistry:
    _cache: Dict[str, any] = {}
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get(cls, model_path: str, model_type: str) -> any:
        if model_path in cls._cache:
            return cls._cache[model_path]
        with cls._lock:
            if model_path not in cls._cache:
                cls._cache[model_path] = cls._load(model_path, model_type)
        return cls._cache[model_path]

    @staticmethod
    def _load(model_path: str, model_type: str) -> any:
        import logging
        logging.getLogger("ModelRegistry").info(f"Loading [{model_type}]: {model_path}")

        if model_type == "yolo":
            from ultralytics import YOLO
            return YOLO(model_path)
        if model_type in ("nanodet", "onnx"):
            import onnxruntime as ort
            return ort.InferenceSession(
                model_path,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
            )
        if model_type == "tensorrt":
            import tensorrt as trt
            rt = trt.Runtime(trt.Logger(trt.Logger.WARNING))
            with open(model_path, "rb") as f:
                return rt.deserialize_cuda_engine(f.read())
        if model_type == "torchvision":
            import torch
            m = torch.load(model_path, map_location="cuda")
            m.eval()
            return m
        raise ValueError(f"Unknown model_type: '{model_type}'")

    @classmethod
    def preload(cls, config: MachineConfig):
        """Preload all models at startup — fail fast."""
        for t in config.get_inspection_triggers():
            p = t.pipeline
            if p.defect:
                cls.get(p.defect.model_path, p.defect.model_type)
            if p.measurement:
                # measurement shares model with defect obj_detect on CMD cams
                # no separate model to load unless different model path
                pass
        for t in config.get_counting_triggers():
            cls.get(t.pipeline.model_path, t.pipeline.model_type)


# ─────────────────────────────────────────────────────────────────
# SINGLETON LOADER
# ─────────────────────────────────────────────────────────────────

_CONFIG: Optional[MachineConfig] = None


def load_config(path: Optional[str] = None) -> MachineConfig:
    global _CONFIG
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "machine_config.yaml")
    with open(path) as f:
        raw = yaml.safe_load(f)
    _CONFIG = MachineConfig(**raw)
    return _CONFIG


def get_config() -> MachineConfig:
    if _CONFIG is None:
        raise RuntimeError("load_config() must be called before get_config()")
    return _CONFIG


# ─────────────────────────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg = load_config()
    print(f"Part        : {cfg.machine.part_code} — {cfg.machine.part_name}")
    print(f"Redis       : {cfg.redis.host}:{cfg.redis.port}")
    print(f"PLC         : {cfg.plc.ip}:{cfg.plc.port} sim={cfg.plc.sim.enabled}")
    for t in cfg.get_inspection_triggers():
        print(f"\nTrigger     : {t.id} ({t.source.type})")
        print(f"  CMD cams  : {t.pipeline.cmd_cameras()}")
        print(f"  Defect    : {t.pipeline.defect_only_cameras()}")
        print(f"  Measure   : {t.pipeline.measure_only_cameras()}")
    for t in cfg.get_counting_triggers():
        print(f"\nCounting    : {t.id} ({t.sub_mode})")
