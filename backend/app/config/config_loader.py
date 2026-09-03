from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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


class ResolutionConfig(BaseModel):
    x: int
    y: int


class ROIConfig(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class CameraSimConfig(BaseModel):
    enabled: bool = False
    image_path: Optional[str] = None
    video_path: Optional[str] = None

    @model_validator(mode="after")
    def one_source_when_enabled(self):
        if self.enabled and not self.image_path and not self.video_path:
            raise ValueError("camera sim.enabled requires image_path or video_path")
        return self


class CameraConfig(BaseModel):
    ip: str
    resolution: ResolutionConfig
    fps: int = 30
    roi: ROIConfig
    capture_mode: Literal["single_shot", "continuous"] = "single_shot"
    sim: CameraSimConfig = CameraSimConfig()
    # fire-and-forget CMD, no ACK -- per-camera light, not a global strobe line
    strobe_reg: Optional[int] = None


class TriggerSourceConfig(BaseModel):
    # "simulation" = timer-fired, no PLC needed (the guaranteed fallback).
    # "plc" = IndexerSlotTracker-driven self-fire per CLAUDE.md Rule 1.
    type: Literal["simulation", "plc"]
    sim_interval_ms: Optional[int] = None

    @model_validator(mode="after")
    def sim_needs_interval(self):
        if self.type == "simulation" and self.sim_interval_ms is None:
            raise ValueError("source.sim_interval_ms is required when source.type == 'simulation'")
        return self


class InspectionTrigger(BaseModel):
    """A camera station on the ring. No trigger_reg/part_id_reg -- the PC
    self-fires off its own slot math (Rule 1), it never waits on a
    controller trigger register. station_offset_pulses is what makes that
    self-fire possible."""
    id: str
    name: str
    type: Literal["inspection"] = "inspection"
    station_offset_pulses: int
    source: TriggerSourceConfig
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


class PartAggregationResultWrite(BaseModel):
    part_id_reg: int
    result_reg: int
    ack_reg: int   # dummy ack on the OK path only -- confirms the result_aggregator increment


class ExitTrigger(BaseModel):
    """Where OK/NOK is evaluated -- not a physical actuator. This build has
    no reject station; nothing is ever dropped from the ring early. At this
    station's offset, the software checks whether the part passed every
    inspection trigger it went through. OK -> result_write.ack_reg fires
    (dummy ack, result_aggregator increments). NOK -> flagged/displayed
    only, no physical action, so no ack is expected on that path."""
    id: str
    name: str
    type: Literal["exit"] = "exit"
    station_offset_pulses: int
    pass_if: Literal["all_triggers_pass", "any_trigger_pass"] = "all_triggers_pass"
    result_write: PartAggregationResultWrite


Trigger = Annotated[Union[InspectionTrigger, ExitTrigger], Field(discriminator="type")]


class IndexerConfig(BaseModel):
    # PLACEHOLDER values live in machine_config.yaml until the PLC-program
    # owner confirms the real disc's slot count / encoder resolution.
    n_slots: int
    encoder_cpr: int

    @model_validator(mode="after")
    def cpr_divisible_by_slots(self):
        if self.encoder_cpr % self.n_slots != 0:
            raise ValueError(
                f"encoder_cpr ({self.encoder_cpr}) must be evenly divisible by "
                f"n_slots ({self.n_slots})"
            )
        return self

    @property
    def pulses_per_slot(self) -> int:
        return self.encoder_cpr // self.n_slots


class RegisterMapConfig(BaseModel):
    pulse_count: int
    heartbeat_plc: int
    entry_queue_write_idx: int
    entry_queue_slots_start: int
    entry_queue_size: int


class PLCSimConfig(BaseModel):
    enabled: bool = False
    host: str = "localhost"
    port: int = 5502


class ErrorRegisterConfig(BaseModel):
    """Health Check page reads these -- name/reg only, never hardcoded in
    the frontend (CLAUDE.md Section 6). Values are placeholders until the
    Integra controller-program owner confirms the real error-bit layout,
    and are expected to differ per client deployment."""
    name: str
    reg: int


class PLCConnectionConfig(BaseModel):
    ip: str
    port: int
    vendor: str
    sim: PLCSimConfig = PLCSimConfig()
    registers: RegisterMapConfig
    error_registers: List[ErrorRegisterConfig] = []


class ActuatorConfig(BaseModel):
    """Device Settings page renders one row per entry. Placeholder
    name/reg values, same caveat as ErrorRegisterConfig."""
    name: str
    reg: int
    type: Literal["toggle"]


class ResolvedMachineConfig(BaseModel):
    part_code: str
    part_name: str
    indexer: IndexerConfig
    plc: PLCConnectionConfig
    triggers: List[Trigger]
    actuators: List[ActuatorConfig] = []

    @model_validator(mode="after")
    def unique_trigger_ids(self):
        ids = [t.id for t in self.triggers]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate triggers[].id: {ids}")
        return self

    @model_validator(mode="after")
    def exactly_one_exit_trigger(self):
        exits = [t for t in self.triggers if t.type == "exit"]
        if len(exits) != 1:
            raise ValueError(f"triggers[] must contain exactly one type: exit entry, found {len(exits)}")
        return self

    def inspection_triggers(self) -> List[InspectionTrigger]:
        return [t for t in self.triggers if t.type == "inspection"]

    def exit_trigger(self) -> ExitTrigger:
        for t in self.triggers:
            if t.type == "exit":
                return t
        raise ValueError("no type: exit trigger found")  # unreachable, exactly_one_exit_trigger enforces this

    def cameras(self) -> Dict[str, CameraConfig]:
        """All cameras across all inspection triggers, keyed by camera_id --
        what the N-camera-ready station registry is built from."""
        out: Dict[str, CameraConfig] = {}
        for trig in self.inspection_triggers():
            out.update(trig.cameras)
        return out


DEFAULT_CONFIG_PATH = Path(__file__).parent / "machine_config.yaml"


def load_machine_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Raw YAML -> dict. SafeLoader only -- this is untrusted-on-disk YAML
    per CLAUDE.md's recipe-import security rule, never yaml.load()."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def resolve_config_for_part(
    part_code: str,
    db: Optional["Session"] = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> ResolvedMachineConfig:
    """machine_config.yaml -> validated runtime config for the given part.

    Reads the YAML directly rather than through a Part/CategoryRecipe join --
    that fuller design needs Part-ingestion machinery that's out of scope for
    this slice (see plan.txt). The optional `db` merge below is the seam for
    that later work; it's a no-op today.
    """
    raw = load_machine_config(config_path)

    actual_part_code = raw["machine"]["part_code"]
    if actual_part_code != part_code:
        raise ValueError(
            f"machine_config.yaml is configured for part_code={actual_part_code!r}, "
            f"not {part_code!r}"
        )

    resolved = ResolvedMachineConfig(
        part_code=actual_part_code,
        part_name=raw["machine"]["part_name"],
        indexer=raw["indexer"],
        plc=raw["plc"],
        triggers=raw["triggers"],
        actuators=raw.get("actuators", []),
    )

    if db is not None:
        _merge_part_overrides(resolved, db)

    return resolved


def _merge_part_overrides(resolved: ResolvedMachineConfig, db: "Session") -> None:
    """Seam for later Part-ingestion work: merge a bootstrapped Part row's
    defects/dimensions into `resolved`. No-op today -- the bootstrap-seeded
    Part row (app/db/bootstrap.py) mirrors the YAML's own thresholds, so
    there's nothing to override yet."""
    from app.models.models import Part  # local import: keep config_loader decoupled from db

    db.query(Part).filter(Part.part_code == resolved.part_code).first()