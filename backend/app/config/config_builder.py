"""Builds a per-part machine_config.yaml from the PartConfigPage form.

Two shapes are in play and must not be confused:

  FORM   flat, one nesting level per UI section (indexer / plc / s1 / s2 /
         r1 / exit1). This is what the page edits. It is never stored --
         it is derived from the YAML on read and merged over FORM_DEFAULTS
         on write.

  CONFIG the real machine_config.yaml: stations is a LIST discriminated by
         `type`, cameras are a mapping keyed by camera id, and the part's
         own values (measurement parameters, defect classes) are injected
         here rather than typed by hand.

Part-owned values are NEVER taken from the form:
  Part.dimensions -> stations[s1].pipeline.measurement.parameters
  Part.defects    -> stations[s2].pipeline.defect.{detect,allowed}_classes
Editing them happens on the part, not here.

A part with no config starts from empty_form(), NOT from another part's
values: these numbers decide what the machine physically does, and an
unreviewed copy of someone else's station offsets is a fault waiting to
happen. Blank therefore means "not answered yet" and is rejected by
validate_form -- it must never silently resolve to a default.

The final gate is config_loader's own Pydantic models (_validate_with_loader):
whatever this module builds must satisfy the exact same schema the machine
loads at session start, or the error belongs to the person typing, not to an
operator pressing Start Session.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent

# Machine-level, never per part, never in the form.
REDIS = {
    "keys": {
        "result": "rv_inspection_result",
        "trigger": "rv_trigger_event",
    }
}

REGISTER_KEYS = (
    "pulse_count",
    "encoder_indexer_ppr",
    "encoder_count",
    "part_sensor",
    "heartbeat",
    "indexing_pulse",
    "heartbeat_per_slot",
    "indexing_pulse_per_slot",
    "reject_cmd",
    "stop_cmd",
    "speed_setpoint",
    "fault",
)


def _camera_defaults(ip: str, strobe_reg: int, image_path: str) -> dict:
    return {
        "ip": ip,
        "vendor": "lucid",
        "fps": 30,
        "resolution": {"x": 1920, "y": 1080},
        "roi": {"x1": 0, "y1": 0, "x2": 1920, "y2": 1080},
        "capture_mode": "single_shot",
        "strobe_reg": strobe_reg,
        "strobe_capture_delay_ms": 50,
        "sim": {"enabled": False, "image_path": image_path},
    }


# Not on the form -- the page renders no fields for these, so they always
# come from here. Lives at pipeline.result in the YAML (PipelineResultConfig),
# NOT at station level, where Pydantic would silently ignore it.
_RESULT_DEFAULTS = {
    "pass_if": "all_cameras_pass",
    "save_result": True,
    "draw_result": True,
}

# The form's SHAPE. The values here are the type template used for
# coercion and the fallback for keys the page never sends -- they are not
# offered to a superadmin configuring a new part.
FORM_DEFAULTS: dict[str, Any] = {
    "indexer": {
        "diameter_mm": 450.0,
        "part_size_mm": 18.0,
        "tolerance_pct": 4,
        "encoder_cpr": 4800,
        "entry_sensor_mid_offset_pulses": 40,
    },
    "plc": {
        "ip": "192.168.7.71",
        "port": 502,
        "vendor": "integra",
        "real_poll_interval_ms": 50.0,
        "speed_setpoint_rpm": 45.0,
        "watchdog_timeout_ms": 3000.0,
        "sim": {
            "enabled": True,
            "host": "localhost",
            "port": 5502,
            "tick_interval_ms": 1000,
            "blank": 5,
            "entry_sensor_response_delay_ms": 0,
            "reject_actuator_response_delay_ms": 0,
        },
        # Literal 40001-40012 exactly as the instrumentation sheet gives
        # them -- the 40001 offset is subtracted at the point of use, not
        # here.
        "registers": {
            "pulse_count": 40001,
            "encoder_indexer_ppr": 40002,
            "encoder_count": 40003,
            "part_sensor": 40004,
            "heartbeat": 40005,
            "indexing_pulse": 40006,
            "heartbeat_per_slot": 40007,
            "indexing_pulse_per_slot": 40008,
            "reject_cmd": 40009,
            "stop_cmd": 40010,
            "speed_setpoint": 40011,
            "fault": 40012,
        },
    },
    "s1": {
        "name": "Station 1 - Dimension Measurement",
        "station_offset_pulses": 540,
        "camera_id": "cam1",
        "camera": _camera_defaults("192.168.6.41", 18, "/data/sim/circles/"),
        "measurement": {
            "method": "caliper",
            "max_ovality": 0.3,
            # Blank means the AI-locator stage stays off and measurement.py
            # falls back to whole-frame contour measurement.
            "model_path": "",
            "model_type": "yolo",
        },
        "result": dict(_RESULT_DEFAULTS),
    },
    "s2": {
        "name": "Station 2 - Defect Detection",
        "station_offset_pulses": 1080,
        "camera_id": "cam2",
        "camera": _camera_defaults("192.168.5.42", 19, "/data/sim/defects/"),
        "defect": {
            "model_path": "/models/pt/osm.pt",
            "model_type": "yolo",
            "conf_thresh": 0.3,
        },
        "result": dict(_RESULT_DEFAULTS),
    },
    "r1": {
        "name": "Reject Station 1",
        "station_offset_pulses": 1440,
        "enabled": True,
    },
    "exit1": {
        "name": "Exit Station - Result Check",
        "station_offset_pulses": 1800,
        # config_loader.ExitStation accepts exactly "all_stations_pass" or
        # "any_station_pass" -- no trailing s.
        "pass_if": "all_stations_pass",
        "result_write": {"part_id_reg": 100, "result_reg": 101, "ack_reg": 102},
    },
}

# Optional by design: a blank measurement model_path disables the locator
# stage, which is a real configuration, not an omission. Keep in step with
# OPTIONAL_PATHS in PartConfigPage.jsx, which decides which labels get a *.
OPTIONAL_PATHS = {
    "s1.measurement.model_path",
    "s1.measurement.model_type",
    "s1.camera.sim.image_path",
    "s2.camera.sim.image_path",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def config_filename(part_code: str) -> str:
    slug = _SLUG_RE.sub("_", (part_code or "part").strip().lower()).strip("_")
    return f"machine_config_{slug or 'part'}.yaml"


def config_path_for(part_code: str) -> Path:
    return CONFIG_DIR / config_filename(part_code)


def default_form() -> dict:
    """The type template, values included. Not used for new parts."""
    return deepcopy(FORM_DEFAULTS)


def _blank(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _blank(v) for k, v in node.items()}
    # Switches stay boolean -- a tri-state toggle is worse than a default.
    return node if isinstance(node, bool) else ""


def empty_form() -> dict:
    """Every text/number field blank -- what an unconfigured part starts from."""
    form = _blank(deepcopy(FORM_DEFAULTS))
    # The page renders no fields for these, so leaving them blank would
    # produce a config the loader rejects for reasons nobody can see.
    form["s1"]["result"] = dict(_RESULT_DEFAULTS)
    form["s2"]["result"] = dict(_RESULT_DEFAULTS)
    form["s1"]["camera"]["capture_mode"] = "single_shot"
    form["s2"]["camera"]["capture_mode"] = "single_shot"
    form["s1"]["camera"]["vendor"] = "lucid"
    form["s2"]["camera"]["vendor"] = "lucid"
    form["s1"]["measurement"]["model_type"] = "yolo"
    form["s2"]["defect"]["model_type"] = "yolo"
    return form


# ═════════════════════════════════════════════════════════════════
# form merge
# ═════════════════════════════════════════════════════════════════
def _coerce(template: Any, value: Any) -> Any:
    if isinstance(template, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(template, int) and not isinstance(template, bool):
        return int(float(value))
    if isinstance(template, float):
        return float(value)
    return str(value)


def _prune(node: Any) -> Any:
    """Drop None values so a key the source doesn't carry keeps its default."""
    if not isinstance(node, dict):
        return node
    return {k: _prune(v) for k, v in node.items() if v is not None}


def _merge(template: dict, override: Any) -> dict:
    """Merge a submitted form over the type template.

    A key the form did NOT send keeps the template value (fields the page
    renders no input for). A key the form sent as "" stays EMPTY and is
    caught by validate_form -- it must never silently become a value the
    person never typed.
    """
    out = deepcopy(template)
    if not isinstance(override, dict):
        return out
    for key, val in override.items():
        if key not in out:
            continue
        if isinstance(out[key], dict):
            out[key] = _merge(out[key], val)
        elif val is None or val == "":
            out[key] = ""
        else:
            try:
                out[key] = _coerce(out[key], val)
            except (TypeError, ValueError):
                out[key] = ""
    return out


# ═════════════════════════════════════════════════════════════════
# required-field check -- runs before anything is built or written
# ═════════════════════════════════════════════════════════════════
REQUIRED_FIELDS: list[tuple[str, str]] = [
    ("indexer.diameter_mm", "Disc diameter"),
    ("indexer.part_size_mm", "Part size"),
    ("indexer.tolerance_pct", "Clearance tolerance"),
    ("indexer.encoder_cpr", "Encoder CPR"),
    ("indexer.entry_sensor_mid_offset_pulses", "Entry sensor mid-offset"),
    ("plc.ip", "PLC IP"),
    ("plc.port", "PLC port"),
    ("plc.vendor", "PLC vendor"),
    ("plc.real_poll_interval_ms", "Real poll interval"),
    ("plc.speed_setpoint_rpm", "Speed setpoint"),
    ("plc.watchdog_timeout_ms", "Watchdog timeout"),
    ("plc.sim.host", "Sim host"),
    ("plc.sim.port", "Sim port"),
    ("plc.sim.tick_interval_ms", "Tick interval"),
    ("plc.sim.blank", "Blank slots"),
    ("plc.sim.entry_sensor_response_delay_ms", "Entry sensor delay"),
    ("plc.sim.reject_actuator_response_delay_ms", "Reject actuator delay"),
    ("s1.name", "Station 1 name"),
    ("s1.station_offset_pulses", "Station 1 offset"),
    ("s1.camera_id", "Station 1 camera id"),
    ("s1.camera.ip", "Station 1 camera IP"),
    ("s1.camera.fps", "Station 1 camera FPS"),
    ("s1.camera.strobe_reg", "Station 1 strobe register"),
    ("s1.camera.strobe_capture_delay_ms", "Station 1 strobe delay"),
    ("s1.measurement.method", "Measurement method"),
    ("s1.measurement.max_ovality", "Max ovality"),
    ("s2.name", "Station 2 name"),
    ("s2.station_offset_pulses", "Station 2 offset"),
    ("s2.camera_id", "Station 2 camera id"),
    ("s2.camera.ip", "Station 2 camera IP"),
    ("s2.camera.fps", "Station 2 camera FPS"),
    ("s2.camera.strobe_reg", "Station 2 strobe register"),
    ("s2.camera.strobe_capture_delay_ms", "Station 2 strobe delay"),
    ("s2.defect.model_path", "Defect model path"),
    ("s2.defect.model_type", "Defect model type"),
    ("s2.defect.conf_thresh", "Defect confidence threshold"),
    ("r1.name", "Reject station name"),
    ("r1.station_offset_pulses", "Reject station offset"),
    ("exit1.name", "Exit station name"),
    ("exit1.station_offset_pulses", "Exit station offset"),
    ("exit1.pass_if", "Exit pass condition"),
    ("exit1.result_write.part_id_reg", "Exit part_id register"),
    ("exit1.result_write.result_reg", "Exit result register"),
    ("exit1.result_write.ack_reg", "Exit ack register"),
]


def _get_path(node: Any, path: str) -> Any:
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def validate_form(form: dict) -> None:
    """Reject a form with blanks, naming the fields the page shows."""
    missing = [
        label
        for path, label in REQUIRED_FIELDS
        if path not in OPTIONAL_PATHS and _get_path(form, path) in (None, "")
    ]

    # Register numbers are all-or-nothing -- a partial map is unusable.
    regs = (form.get("plc") or {}).get("registers") or {}
    blank_regs = [k for k in REGISTER_KEYS if regs.get(k) in (None, "")]
    if blank_regs:
        missing.append(f"Modbus registers ({', '.join(blank_regs)})")

    for section, label in (("s1", "Station 1"), ("s2", "Station 2")):
        cam = ((form.get(section) or {}).get("camera")) or {}
        for group, keys in (
            ("resolution", ("x", "y")),
            ("roi", ("x1", "y1", "x2", "y2")),
        ):
            blanks = [k for k in keys if (cam.get(group) or {}).get(k) in (None, "")]
            if blanks:
                missing.append(f"{label} camera {group} ({', '.join(blanks)})")
        sim = cam.get("sim") or {}
        if sim.get("enabled") and not sim.get("image_path"):
            missing.append(f"{label} sim image path")

    if missing:
        raise ValueError("These fields are required: " + ", ".join(missing) + ".")


# ═════════════════════════════════════════════════════════════════
# part-owned values
# ═════════════════════════════════════════════════════════════════
def _defect_names(part) -> list[str]:
    return sorted((part.defects or {}).keys())


def _defect_conf_thresh(part, form_value: Any) -> float:
    """The station gate must sit at or below every per-defect threshold.

    There is one conf_thresh per defect pipeline, so a gate above any
    individual defect's threshold would filter that defect out before its
    own threshold is ever applied.
    """
    vals: list[float] = []
    for cfg in (part.defects or {}).values():
        try:
            vals.append(float((cfg or {}).get("conf_thresh")))
        except (TypeError, ValueError):
            continue
    gate = float(form_value)
    return round(min(vals + [gate]), 4) if vals else gate


def _measurement_parameters(part, max_ovality: Any) -> dict:
    """Part.dimensions -> measurement.parameters.

    lower_limit/upper_limit stay as TOLERANCES (+/- from nominal_value),
    which is what both the part form and the loader mean by them -- do not
    convert to absolute bounds here.
    """
    out: dict[str, dict] = {}
    for name, cfg in (part.dimensions or {}).items():
        cfg = cfg or {}

        def _f(key, default=None):
            try:
                return float(cfg.get(key))
            except (TypeError, ValueError):
                return default

        nominal = _f("nominal")
        if nominal is None:
            continue

        cal = _f("calibration_factor")
        out[str(name)] = {
            "calibration_factor": cal if cal and cal > 0 else 1.0,
            "nominal_value": nominal,
            "upper_limit": _f("upper_limit", 0.0),
            "lower_limit": _f("lower_limit", 0.0),
            "max_ovality": float(max_ovality),
            "unit": cfg.get("unit") or "mm",
        }
    return out


# ═════════════════════════════════════════════════════════════════
# build
# ═════════════════════════════════════════════════════════════════
def build_config(part, form: dict) -> dict:
    f = _merge(FORM_DEFAULTS, form or {})

    defects = _defect_names(part)
    params = _measurement_parameters(part, f["s1"]["measurement"]["max_ovality"])

    stations: list[dict] = []

    # ── s1: measurement ──────────────────────────────────────────
    if params:
        s1, cam_id = f["s1"], f["s1"]["camera_id"]
        measurement = {
            "allowed_cameras": [cam_id],
            # Required by MeasurementConfig even while the locator model is
            # off; unused in that state.
            "allowed_classes": defects,
            "method": s1["measurement"]["method"],
            "parameters": params,
        }
        if s1["measurement"]["model_path"]:
            measurement["model_path"] = s1["measurement"]["model_path"]
            measurement["model_type"] = s1["measurement"]["model_type"] or "yolo"

        stations.append(
            {
                "id": "s1",
                "name": s1["name"],
                "type": "inspection",
                "station_offset_pulses": s1["station_offset_pulses"],
                "cameras": {cam_id: deepcopy(s1["camera"])},
                # result belongs INSIDE pipeline (InspectionPipeline.result).
                # At station level Pydantic ignores it and the defaults win.
                "pipeline": {
                    "measurement": measurement,
                    "result": deepcopy(s1["result"]),
                },
            }
        )

    # ── s2: defect detection ─────────────────────────────────────
    if defects:
        s2, cam_id = f["s2"], f["s2"]["camera_id"]
        stations.append(
            {
                "id": "s2",
                "name": s2["name"],
                "type": "inspection",
                "station_offset_pulses": s2["station_offset_pulses"],
                "cameras": {cam_id: deepcopy(s2["camera"])},
                "pipeline": {
                    "defect": {
                        "model_path": s2["defect"]["model_path"],
                        "model_type": s2["defect"]["model_type"] or "yolo",
                        "conf_thresh": _defect_conf_thresh(
                            part, s2["defect"]["conf_thresh"]
                        ),
                        "allowed_cameras": [cam_id],
                        "detect_classes": defects,
                        "allowed_defects": defects,
                    },
                    "result": deepcopy(s2["result"]),
                },
            }
        )

    # ── r1 + exit1: always present ───────────────────────────────
    stations.append(
        {
            "id": "r1",
            "name": f["r1"]["name"],
            "type": "reject",
            "station_offset_pulses": f["r1"]["station_offset_pulses"],
            "enabled": f["r1"]["enabled"],
        }
    )
    stations.append(
        {
            "id": "exit1",
            "name": f["exit1"]["name"],
            "type": "exit",
            "station_offset_pulses": f["exit1"]["station_offset_pulses"],
            "pass_if": f["exit1"]["pass_if"],
            "result_write": deepcopy(f["exit1"]["result_write"]),
        }
    )

    return {
        "machine": {"part_code": part.part_code, "part_name": part.part_name},
        "indexer": deepcopy(f["indexer"]),
        "plc": {
            "ip": f["plc"]["ip"],
            "port": f["plc"]["port"],
            "vendor": f["plc"]["vendor"],
            "sim": deepcopy(f["plc"]["sim"]),
            "real_poll_interval_ms": f["plc"]["real_poll_interval_ms"],
            "speed_setpoint_rpm": f["plc"]["speed_setpoint_rpm"],
            "watchdog_timeout_ms": f["plc"]["watchdog_timeout_ms"],
            "registers": deepcopy(f["plc"]["registers"]),
        },
        "redis": deepcopy(REDIS),
        "stations": stations,
    }


# ═════════════════════════════════════════════════════════════════
# yaml <-> form
# ═════════════════════════════════════════════════════════════════
def render_yaml(cfg: dict) -> str:
    return yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False, width=100)


def parse_yaml(text: str) -> dict:
    data = yaml.safe_load(text or "") or {}
    if not isinstance(data, dict):
        raise ValueError("Config YAML must be a mapping at the top level.")
    return data


def _station(cfg: dict, station_id: str) -> dict:
    for s in cfg.get("stations") or []:
        if s.get("id") == station_id:
            return s
    return {}


def _first_camera(station: dict) -> tuple[str, dict]:
    for cam_id, cam in (station.get("cameras") or {}).items():
        return cam_id, cam
    return "", {}


def form_from_config(cfg: dict) -> dict:
    """Strip the derived and machine-level parts back out.

    Keys absent from the YAML keep the template value, so a config written
    before a field existed still loads into the page.
    """
    form = deepcopy(FORM_DEFAULTS)

    form["indexer"] = _merge(FORM_DEFAULTS["indexer"], _prune(cfg.get("indexer") or {}))

    plc = cfg.get("plc") or {}
    form["plc"] = _merge(
        FORM_DEFAULTS["plc"],
        _prune(
            {
                **{k: v for k, v in plc.items() if k not in ("sim", "registers")},
                "sim": plc.get("sim"),
                "registers": plc.get("registers"),
            }
        ),
    )

    s1 = _station(cfg, "s1")
    if s1:
        cam_id, cam = _first_camera(s1)
        pipeline = s1.get("pipeline") or {}
        measurement = pipeline.get("measurement") or {}
        # max_ovality lives per parameter in the YAML but is one field on
        # the form -- take the first, they are written identically.
        ovality = next(
            (
                p.get("max_ovality")
                for p in (measurement.get("parameters") or {}).values()
                if p.get("max_ovality") is not None
            ),
            None,
        )
        form["s1"] = _merge(
            FORM_DEFAULTS["s1"],
            _prune(
                {
                    "name": s1.get("name"),
                    "station_offset_pulses": s1.get("station_offset_pulses"),
                    "camera_id": cam_id or None,
                    "camera": cam,
                    "measurement": {
                        "method": measurement.get("method"),
                        "max_ovality": ovality,
                        "model_path": measurement.get("model_path", ""),
                        "model_type": measurement.get("model_type"),
                    },
                    "result": pipeline.get("result"),
                }
            ),
        )

    s2 = _station(cfg, "s2")
    if s2:
        cam_id, cam = _first_camera(s2)
        pipeline = s2.get("pipeline") or {}
        defect = pipeline.get("defect") or {}
        form["s2"] = _merge(
            FORM_DEFAULTS["s2"],
            _prune(
                {
                    "name": s2.get("name"),
                    "station_offset_pulses": s2.get("station_offset_pulses"),
                    "camera_id": cam_id or None,
                    "camera": cam,
                    "defect": {
                        "model_path": defect.get("model_path"),
                        "model_type": defect.get("model_type"),
                        "conf_thresh": defect.get("conf_thresh"),
                    },
                    "result": pipeline.get("result"),
                }
            ),
        )

    r1 = _station(cfg, "r1")
    if r1:
        form["r1"] = _merge(FORM_DEFAULTS["r1"], _prune(r1))

    exit1 = _station(cfg, "exit1")
    if exit1:
        form["exit1"] = _merge(FORM_DEFAULTS["exit1"], _prune(exit1))

    return form


# ═════════════════════════════════════════════════════════════════
# structural validation -- raises, so the router's except ValueError works
# ═════════════════════════════════════════════════════════════════
def _derived_n_slots(indexer: dict) -> int:
    try:
        part_slot = float(indexer["part_size_mm"]) * (
            1 + float(indexer["tolerance_pct"]) / 100
        )
        if part_slot <= 0:
            return 0
        return math.floor(math.pi * float(indexer["diameter_mm"]) / part_slot)
    except (TypeError, ValueError, KeyError):
        return 0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _validate_with_loader(cfg: dict) -> list[str]:
    """Build the real runtime model, so a bad config fails for the person
    typing it rather than for an operator at Start Session.

    This is the authoritative check -- it runs config_loader's own Pydantic
    models and every validator on them (reject_before_exit,
    exactly_one_terminal_station, validate_camera_refs, the n_slots /
    encoder_cpr reconciliation). The hand-written rules above only exist to
    produce friendlier messages for the mistakes people actually make.
    """
    try:
        from app.config.config_loader import ResolvedMachineConfig
    except Exception:  # noqa: BLE001 -- never block a save on an import problem
        return []

    try:
        ResolvedMachineConfig(
            part_code=cfg["machine"]["part_code"],
            part_name=cfg["machine"]["part_name"],
            indexer=cfg["indexer"],
            plc=cfg["plc"],
            stations=cfg["stations"],
            actuators=cfg.get("actuators", []),
        )
    except Exception as exc:  # noqa: BLE001 -- pydantic raises its own type
        return [f"Runtime config check failed: {exc}"]
    return []


def _collect_errors(cfg: dict) -> list[str]:
    errors: list[str] = []

    for key in ("machine", "indexer", "plc", "redis", "stations"):
        if key not in cfg:
            errors.append(f"Missing top-level section '{key}'.")
    if errors:
        return errors

    ind = cfg["indexer"]
    for key in ("diameter_mm", "part_size_mm", "encoder_cpr"):
        if _num(ind.get(key)) <= 0:
            errors.append(f"indexer.{key} must be greater than 0.")

    if not errors:
        n_slots = _derived_n_slots(ind)
        if n_slots <= 0:
            errors.append(
                "The indexer geometry derives 0 slots — check disc diameter, "
                "part size and clearance tolerance."
            )
        elif _num(cfg["plc"]["sim"].get("blank")) > n_slots:
            errors.append(
                f"Blank slots ({cfg['plc']['sim']['blank']}) exceeds the "
                f"{n_slots} slots this geometry derives."
            )

    plc = cfg["plc"]
    if not (0 < int(_num(plc.get("port"))) < 65536):
        errors.append("PLC port must be a valid TCP port.")
    regs = plc.get("registers") or {}
    absent = [k for k in REGISTER_KEYS if k not in regs]
    if absent:
        errors.append(f"Missing Modbus registers: {', '.join(absent)}.")
    elif len(set(regs.values())) != len(regs):
        errors.append("Modbus register numbers must be unique.")

    stations = cfg["stations"]
    ids = [s.get("id") for s in stations]
    if "exit1" not in ids:
        errors.append("The exit station is required.")
    if len(set(ids)) != len(ids):
        errors.append("Station ids must be unique.")

    # A part must be measured, inspected for defects, or both -- a config
    # with neither would pass every part unconditionally.
    if not any(s.get("type") == "inspection" for s in stations):
        errors.append(
            "This part has no dimensions and no defects, so there is nothing "
            "to inspect. Add them on the part first."
        )

    # Physical order around the ring.
    offsets = [
        (s["id"], _num(s.get("station_offset_pulses")))
        for s in stations
        if s.get("id") in ("s1", "s2", "r1", "exit1")
    ]
    for (prev_id, prev), (cur_id, cur) in zip(offsets, offsets[1:]):
        if cur <= prev:
            errors.append(
                f"{cur_id} offset ({cur:g}) must be greater than {prev_id}'s "
                f"({prev:g}) — stations are passed in ring order."
            )

    for s in stations:
        pipeline = s.get("pipeline") or {}

        defect = pipeline.get("defect")
        if defect:
            if not (0.0 < _num(defect.get("conf_thresh")) <= 1.0):
                errors.append("Defect confidence threshold must be between 0 and 1.")
            if not defect.get("allowed_defects"):
                errors.append("The defect station has no defect classes.")
            if not defect.get("model_path"):
                errors.append("A defect model path is required.")

        measurement = pipeline.get("measurement")
        if measurement:
            params = measurement.get("parameters") or {}
            if not params:
                errors.append("The measurement station has no parameters.")
            for name, p in params.items():
                if _num(p.get("calibration_factor")) <= 0:
                    errors.append(f"{name}: calibration factor must be greater than 0.")
                if _num(p.get("lower_limit")) < 0 or _num(p.get("upper_limit")) < 0:
                    errors.append(
                        f"{name}: limits are tolerances (± from nominal) and "
                        "cannot be negative."
                    )
                if _num(p.get("lower_limit")) == 0 and _num(p.get("upper_limit")) == 0:
                    errors.append(f"{name}: both tolerances are 0, so every part fails.")
                if _num(p.get("max_ovality")) < 0:
                    errors.append(f"{name}: max ovality cannot be negative.")

        for cam_id, cam in (s.get("cameras") or {}).items():
            roi = cam.get("roi") or {}
            res = cam.get("resolution") or {}
            if _num(roi.get("x2")) <= _num(roi.get("x1")) or _num(roi.get("y2")) <= _num(
                roi.get("y1")
            ):
                errors.append(f"{cam_id}: ROI x2/y2 must be greater than x1/y1.")
            if _num(roi.get("x2")) > _num(res.get("x")) or _num(roi.get("y2")) > _num(
                res.get("y")
            ):
                errors.append(f"{cam_id}: ROI extends beyond the sensor resolution.")
            sim = cam.get("sim") or {}
            if sim.get("enabled") and not sim.get("image_path"):
                errors.append(f"{cam_id}: simulation is on but no image path is set.")

    # The real schema has the last word.
    return errors + _validate_with_loader(cfg)


def validate_config(cfg: dict) -> None:
    """Raise ValueError listing everything wrong, or return silently."""
    errors = _collect_errors(cfg)
    if errors:
        raise ValueError(" ".join(errors))


def write_config_file(part_code: str, yaml_text: str) -> str:
    path = config_path_for(part_code)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")
    return str(path)