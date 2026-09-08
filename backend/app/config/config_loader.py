import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Dict, List, Literal, NamedTuple, Optional, Union

import yaml
from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger("config_loader")


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
    # Selects the driver class from app.camera.driver_registry.CAMERA_DRIVERS
    # -- adding a new camera make is a registry entry + a CameraDriver
    # implementation, never a change here or in station_registry.py.
    vendor: str = "lucid"
    resolution: ResolutionConfig
    fps: int = 30
    roi: ROIConfig
    capture_mode: Literal["single_shot", "continuous"] = "single_shot"
    sim: CameraSimConfig = CameraSimConfig()
    # fire-and-forget CMD, no ACK -- per-camera light, not a global strobe line
    strobe_reg: Optional[int] = None
    # Delay between firing strobe_reg and actually capturing -- the light
    # needs time to reach full brightness first. Required whenever
    # strobe_reg is set (a strobe with no capture delay is a race against
    # the light hardware); meaningless without it. NOT WIRED YET -- like
    # strobe_reg itself, nothing in the codebase actually writes strobe_reg
    # or sleeps this long before capture today (see real_frame_provider()
    # in app/camera/station_registry.py); this is schema only until that
    # sequencing is built.
    strobe_capture_delay_ms: Optional[int] = None

    @model_validator(mode="after")
    def strobe_delay_required_with_strobe(self):
        if self.strobe_reg is not None and self.strobe_capture_delay_ms is None:
            raise ValueError("strobe_capture_delay_ms is required when strobe_reg is set")
        return self


class InspectionStation(BaseModel):
    """A camera station on the ring. No trigger_reg/part_id_reg -- the PC
    self-fires off its own slot math (Rule 1), it never waits on a
    controller trigger register. station_offset_pulses is what makes that
    self-fire possible."""
    id: str
    name: str
    type: Literal["inspection"] = "inspection"
    station_offset_pulses: int
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


class ExitStation(BaseModel):
    """Where OK/NOK is evaluated -- not a physical actuator. The reject
    decision itself now happens at R1 (RejectStation, below), per CLAUDE.md
    Rule 3 -- by the time a part reaches Exit, IndexerSlotTracker.slots[
    slot_id].status is already OK or NOK (or, if R1 is disabled, still
    unresolved and evaluated here instead -- see tracker.transition_exit).
    OK -> result_write.ack_reg fires (dummy ack, result_aggregator
    increments). NOK -> flagged/displayed only, no physical action, so no
    ack is expected on that path."""
    id: str
    name: str
    type: Literal["exit"] = "exit"
    station_offset_pulses: int
    pass_if: Literal["all_stations_pass", "any_station_pass"] = "all_stations_pass"
    result_write: PartAggregationResultWrite


class RejectStation(BaseModel):
    """The reject decision checkpoint (CLAUDE.md Rule 3: evaluated at R1,
    never at Exit). Deliberately has NO cmd_reg/ack_reg yet -- unlike the
    inert app/config/machine_config.example.yaml sketch, this build has no
    wired reject actuator (REJECT_CMD, register 40009, stays unwired).
    Real PLC actuation + ACK/timeout escalation (Rule 4) is separate future
    work; today this only mutates ring state (IndexerSlotTracker
    .transition_r1), nothing physical happens yet.

    enabled=False is commissioning mode: NOK parts ride through R1
    untouched and get resolved at Exit instead -- Exit's "everything past
    here already passed" guarantee only holds when this is True."""
    id: str
    name: str
    type: Literal["reject"] = "reject"
    station_offset_pulses: int
    enabled: bool = True


Station = Annotated[Union[InspectionStation, RejectStation, ExitStation], Field(discriminator="type")]


class SimCounts(NamedTuple):
    ok: int
    blank: int


class IndexerConfig(BaseModel):
    # PLACEHOLDER values live in machine_config.yaml until the PLC-program
    # owner confirms the real disc's slot count / encoder resolution.
    diameter_mm: float
    part_size_mm: float
    tolerance_pct: float
    encoder_cpr: int

    @property
    def _requested_n_slots(self) -> int:
        """Slot count implied by tolerance_pct alone, before reconciling
        against encoder_cpr divisibility. Floored (never rounded up) so
        every slot keeps at least tolerance_pct clearance -- see n_slots."""
        circumference_mm = math.pi * self.diameter_mm
        effective_spacing_mm = self.part_size_mm * (1 + self.tolerance_pct / 100)
        return math.floor(circumference_mm / effective_spacing_mm)

    @property
    def n_slots(self) -> int:
        """Derived from the disc's physical size, not configured directly
        (indexer-ring-math skill: "n_slots is part-size dependent, computed
        per recipe, not fixed"), then reconciled against encoder_cpr.

        pulses_per_slot = encoder_cpr // n_slots must be exact -- a
        fractional pulses_per_slot silently corrupts slot-boundary math. The
        requested tolerance_pct (including 0) only sets a *minimum*
        clearance floor; if it doesn't happen to land on a slot count that
        divides encoder_cpr evenly, search downward for the nearest slot
        count that does. Decreasing n_slots only ever *increases* physical
        spacing per slot, so this can never give less clearance than
        tolerance_pct asked for -- only ever more. Searching upward instead
        would shrink spacing below the requested tolerance, which is unsafe.
        """
        requested = self._requested_n_slots
        if requested < 1:
            raise ValueError(
                f"derived n_slots ({requested}) from diameter_mm="
                f"{self.diameter_mm}, part_size_mm={self.part_size_mm}, "
                f"tolerance_pct={self.tolerance_pct} is not a positive slot "
                f"count"
            )
        n = requested
        while n > 1 and self.encoder_cpr % n != 0:
            n -= 1
        if n != requested:
            actual_tolerance_pct = (
                math.pi * self.diameter_mm / (n * self.part_size_mm) - 1
            ) * 100
            log.warning(
                "indexer n_slots adjusted from %d (requested via "
                "tolerance_pct=%.3f%%) to %d so encoder_cpr (%d) divides "
                "evenly -- effective tolerance is now %.3f%%. Confirm "
                "tolerance_pct with whoever owns the mechanical clearance "
                "spec.",
                requested, self.tolerance_pct, n, self.encoder_cpr,
                actual_tolerance_pct,
            )
        return n

    @property
    def pulses_per_slot(self) -> int:
        return self.encoder_cpr // self.n_slots


class RegisterMapConfig(BaseModel):
    """Register numbers are literal Modicon 4xxxx addresses, exactly as
    given by the instrumentation team's sheet -- not 0-based pymodbus
    protocol addresses. Whatever code actually issues a pymodbus read/write
    must subtract 40001 at the point of use."""
    pulse_count: int
    encoder_indexer_ppr: int
    encoder_count: int
    part_sensor: int
    heartbeat: int
    indexing_pulse: int
    heartbeat_per_slot: int
    indexing_pulse_per_slot: int
    reject_cmd: int
    stop_cmd: int
    speed_setpoint: int
    fault: int


class PLCSimConfig(BaseModel):
    """The single top-level 'is this machine running in simulation' switch --
    consolidates what used to be three separate config locations: this
    connection target (host/port, mock Modbus server vs real PLC), the
    dispatcher's own tick cadence (was per-station source.sim_interval_ms --
    every station on one physical ring shares one rotation speed, so that
    was already flagged in dispatcher.py as a config-schema smell), and the
    ring-wide BLANK-slot harness (was a standalone top-level sim: block).
    Distinct from CameraSimConfig, which stays per-camera on purpose (mixed
    real/sim commissioning, one camera real while others simulated).

    Deliberately has NO nok field (per explicit instruction 2026-09-07,
    removing what was here before): OK/NOK is never forced by config --
    every non-blank slot runs real defect/measurement inference against its
    sim image (which already includes both good and defective photos), and
    that real result is what decides. Only which slots are permanently
    unfed (blank) is a sim-harness knob."""
    enabled: bool = False
    host: str = "localhost"
    port: int = 5502
    # Replaces per-station source.sim_interval_ms -- single shared cadence
    # at which StationDispatcher's own tick loop advances the ring by one
    # slot when there is no real PLC pulse source.
    tick_interval_ms: int = 3000
    # Which physical slot indices (chosen randomly, see
    # IndexerSlotTracker.seed_sim) are permanently unfed by the feeder.
    blank: int = 0

    def resolve(self, total: int) -> SimCounts:
        if self.blank > total:
            raise ValueError(
                f"plc.sim.blank ({self.blank}) exceeds the indexer's actual slot "
                f"count ({total}) -- total is derived from indexer.diameter_mm/"
                f"part_size_mm/tolerance_pct, not something plc.sim can override"
            )
        return SimCounts(ok=total - self.blank, blank=self.blank)


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
    # Written to the speed_setpoint register once at session start
    # (CLAUDE.md Rule 5: config-driven, never hardcoded).
    speed_setpoint_rpm: float
    # PLACEHOLDER -- app/plc/watchdog.py's heartbeat-staleness timeout.
    # Deliberately not tuned yet; real value comes once the indexer/PLC
    # hardware is actually connected (explicit instruction, not guessed).
    watchdog_timeout_ms: float = 5000.0
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
    stations: List[Station]
    actuators: List[ActuatorConfig] = []

    @model_validator(mode="after")
    def unique_station_ids(self):
        ids = [s.id for s in self.stations]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate stations[].id: {ids}")
        return self

    @model_validator(mode="after")
    def exactly_one_exit_station(self):
        exits = [s for s in self.stations if s.type == "exit"]
        if len(exits) != 1:
            raise ValueError(f"stations[] must contain exactly one type: exit entry, found {len(exits)}")
        return self

    @model_validator(mode="after")
    def at_most_one_reject_station(self):
        rejects = [s for s in self.stations if s.type == "reject"]
        if len(rejects) > 1:
            raise ValueError(f"stations[] must contain at most one type: reject entry, found {len(rejects)}")
        return self

    @model_validator(mode="after")
    def reject_before_exit(self):
        """CLAUDE.md Critical Rule 3: the reject decision is evaluated at
        R1, never at Exit -- that guarantee only holds if R1 physically
        sits before Exit on the ring. Nothing previously checked this;
        found in spec12's code review as a config typo that would load and
        validate cleanly while silently violating Rule 3 at runtime."""
        reject = self.reject_station()
        if reject is None:
            return self
        exit_st = self.exit_station()
        if reject.station_offset_pulses >= exit_st.station_offset_pulses:
            raise ValueError(
                f"reject station {reject.id!r} (station_offset_pulses="
                f"{reject.station_offset_pulses}) must be strictly before the exit "
                f"station {exit_st.id!r} (station_offset_pulses="
                f"{exit_st.station_offset_pulses}) in ring order -- CLAUDE.md Rule 3 "
                f"requires the reject decision to be evaluated before Exit"
            )
        return self

    def inspection_stations(self) -> List[InspectionStation]:
        return [s for s in self.stations if s.type == "inspection"]

    def exit_station(self) -> ExitStation:
        for s in self.stations:
            if s.type == "exit":
                return s
        raise ValueError("no type: exit station found")  # unreachable, exactly_one_exit_station enforces this

    def reject_station(self) -> Optional[RejectStation]:
        for s in self.stations:
            if s.type == "reject":
                return s
        return None

    def cameras(self) -> Dict[str, CameraConfig]:
        """All cameras across all inspection stations, keyed by camera_id --
        what the N-camera-ready station registry is built from."""
        out: Dict[str, CameraConfig] = {}
        for station in self.inspection_stations():
            out.update(station.cameras)
        return out


DEFAULT_CONFIG_PATH = Path(__file__).parent / "machine_config.yaml"


def load_machine_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Raw YAML -> dict. SafeLoader only -- this is untrusted-on-disk YAML
    per CLAUDE.md's recipe-import security rule, never yaml.load()."""
    with open(config_path) as f:
        return yaml.safe_load(f)


_resolved_config_cache: Dict[str, ResolvedMachineConfig] = {}


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

    Cached by (config_path, part_code) when db is None -- this is called
    again on every session start / part reselect, and re-parsing the same
    YAML into an identical ResolvedMachineConfig each time is wasted work
    the caller (inspection_session.start_session) then uses to rebuild the
    whole camera registry. Not cached when db is given: a future real
    per-part DB override (_merge_part_overrides) could vary the result
    between calls even for the same part_code, so that path always resolves
    fresh.
    """
    cache_key = f"{config_path}:{part_code}"
    if db is None and cache_key in _resolved_config_cache:
        return _resolved_config_cache[cache_key]

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
        stations=raw["stations"],
        actuators=raw.get("actuators", []),
    )

    if db is not None:
        _merge_part_overrides(resolved, db)
    else:
        _resolved_config_cache[cache_key] = resolved

    return resolved


def _merge_part_overrides(resolved: ResolvedMachineConfig, db: "Session") -> None:
    """Seam for later Part-ingestion work: merge a bootstrapped Part row's
    defects/dimensions into `resolved`. No-op today -- the bootstrap-seeded
    Part row (app/db/bootstrap.py) mirrors the YAML's own thresholds, so
    there's nothing to override yet."""
    from app.models.models import Part  # local import: keep config_loader decoupled from db

    db.query(Part).filter(Part.part_code == resolved.part_code).first()