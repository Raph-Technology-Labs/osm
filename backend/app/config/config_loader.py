from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, model_validator


class DefectConfig(BaseModel):
    model_path: str
    model_type: Literal["yolo", "nanodet", "onnx", "tensorrt", "torchvision"]
    conf_thresh: float = 0.50
    allowed_cameras: List[str]
    detect_classes: List[str]           # every class this model detects
    allowed_defects: List[str]          # ok/nok decided ONLY on these
    resolved_classes: Dict[str, float] = {}   # conf_thresh per class, filled from Part.defects


class MeasurementParamConfig(BaseModel):
    calibration_factor: float = 10.0
    nominal_value: Optional[float] = None
    upper_limit: Optional[float] = None
    lower_limit: Optional[float] = None
    unit: str = "mm"


class MeasurementConfig(BaseModel):
    allowed_cameras: List[str]
    allowed_classes: List[str]          # which class(es) to pull, from own or shared detections
    method: Literal["caliper", "contour", "ellipse"] = "caliper"
    parameters: Dict[str, MeasurementParamConfig] = {}

    # optional — only set if measurement needs its own model (different from defect's)
    model_path: Optional[str] = None
    model_type: Optional[Literal["yolo", "nanodet", "onnx", "tensorrt", "torchvision"]] = None

    def uses_own_model(self) -> bool:
        return self.model_path is not None


class PipelineResultConfig(BaseModel):
    pass_if: Literal["all_cameras_pass", "any_camera_pass"] = "all_cameras_pass"
    save_result: bool = True
    draw_result: bool = True


class InspectionPipeline(BaseModel):
    defect: Optional[DefectConfig] = None
    measurement: Optional[MeasurementConfig] = None
    result: PipelineResultConfig = PipelineResultConfig()

    @model_validator(mode="after")
    def at_least_one_block(self):
        if self.defect is None and self.measurement is None:
            raise ValueError("Pipeline must have at least one of: defect | measurement")
        return self

    def measurement_shares_defect_model(self) -> bool:
        return (
            self.measurement is not None
            and self.defect is not None
            and not self.measurement.uses_own_model()
        )

    def cmd_cameras(self) -> set:
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


class TriggerPLCConfig(BaseModel):
    trigger_reg: int
    part_id_reg: int


class InspectionTrigger(BaseModel):
    id: str
    name: str
    type: Literal["inspection"] = "inspection"
    is_last_trigger: bool = False
    source: "TriggerSourceConfig"
    plc: TriggerPLCConfig
    cameras: Dict[str, "CameraConfig"]
    pipeline: InspectionPipeline

    @model_validator(mode="after")
    def validate_camera_refs(self):
        registered = set(self.cameras.keys())
        active = self.pipeline.all_active_cameras()
        unknown = active - registered
        if unknown:
            raise ValueError(f"Pipeline references unregistered cameras: {unknown}")
        return self


class PartAggregationResultWrite(BaseModel):
    part_id_reg: int
    result_reg: int
    ack_reg: int


class PartAggregationConfig(BaseModel):
    pass_if: Literal["all_triggers_pass", "any_trigger_pass"] = "all_triggers_pass"
    result_write: PartAggregationResultWrite