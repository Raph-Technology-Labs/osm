"""_run_pipeline() unit tests -- app.pipeline.defect and app.pipeline.measurement
are replaced with fake modules in sys.modules (not imported for real: they
pull in torch/ultralytics, unneeded for these dispatch/combination-logic-only
tests, and not installed in every dev environment this repo runs in).
_run_pipeline()'s deferred `from app.pipeline.defect import
run_defect_inference` (etc.) picks up the fake module because it looks the
import up in sys.modules at call time, not at station_registry.py's own
import time.

Covers spec13 #5: a "cmd" camera (in both defect.allowed_cameras and
measurement.allowed_cameras -- config_loader.InspectionPipeline.cmd_cameras())
must run BOTH pipeline blocks, not just defect."""

import sys
import types
from dataclasses import dataclass

import numpy as np
import pytest

from app.camera import station_registry
from app.config.config_loader import DefectConfig, MeasurementConfig


@dataclass
class FakeMeasurementResult:
    diameter_mm: float
    ovality_mm: float
    passed: bool
    frame_out: np.ndarray


FRAME = np.zeros((4, 4, 3), dtype=np.uint8)
DEFECT_FRAME_OUT = np.ones((4, 4, 3), dtype=np.uint8)  # distinct identity from FRAME
MEASUREMENT_FRAME_OUT = np.full((4, 4, 3), 2, dtype=np.uint8)


@pytest.fixture(autouse=True)
def fake_pipeline_modules(monkeypatch):
    """Installs empty fake app.pipeline.defect / app.pipeline.measurement
    modules for the duration of each test; each test sets
    .run_defect_inference / .run_measurement_inference on them as needed.
    Calling either without setting it first is a test bug -- left unset so
    it raises AttributeError loudly rather than silently no-op-ing."""
    fake_defect = types.ModuleType("app.pipeline.defect")
    fake_measurement = types.ModuleType("app.pipeline.measurement")
    monkeypatch.setitem(sys.modules, "app.pipeline.defect", fake_defect)
    monkeypatch.setitem(sys.modules, "app.pipeline.measurement", fake_measurement)
    return fake_defect, fake_measurement


def make_defect_config(**overrides):
    kwargs = dict(
        model_path="fake.pt",
        model_type="yolo",
        allowed_cameras=["cam1"],
        detect_classes=["scratch"],
        allowed_defects=["scratch"],
    )
    kwargs.update(overrides)
    return DefectConfig(**kwargs)


def make_measurement_config(**overrides):
    kwargs = dict(allowed_cameras=["cam1"], allowed_classes=["part"])
    kwargs.update(overrides)
    return MeasurementConfig(**kwargs)


def defect_fn(is_defect=False, label="scratch", confidence=0.9, count=1):
    def _fake(frame, defect_config, draw_result):
        return is_defect, label, confidence, count, DEFECT_FRAME_OUT
    return _fake


def measurement_fn(passed=True, received_frames=None):
    def _fake(frame, measurement_config, draw_result):
        if received_frames is not None:
            received_frames.append(frame)
        return FakeMeasurementResult(diameter_mm=10.0, ovality_mm=0.1, passed=passed, frame_out=MEASUREMENT_FRAME_OUT)
    return _fake


def test_defect_only_camera_never_calls_measurement(fake_pipeline_modules):
    fake_defect, fake_measurement = fake_pipeline_modules
    fake_defect.run_defect_inference = defect_fn(is_defect=False)
    fake_measurement.run_measurement_inference = lambda *a, **k: pytest.fail("measurement should not run")

    result = station_registry._run_pipeline(FRAME, make_defect_config(), None, draw_result=True)

    assert result.is_defect is False
    assert result.measurement_data is None


def test_measurement_only_camera_never_calls_defect(fake_pipeline_modules):
    fake_defect, fake_measurement = fake_pipeline_modules
    fake_defect.run_defect_inference = lambda *a, **k: pytest.fail("defect should not run")
    fake_measurement.run_measurement_inference = measurement_fn(passed=True)

    result = station_registry._run_pipeline(FRAME, None, make_measurement_config(), draw_result=True)

    assert result.is_defect is False
    assert result.measurement_data is not None


def test_shared_camera_runs_both_and_combines_ok(fake_pipeline_modules):
    fake_defect, fake_measurement = fake_pipeline_modules
    fake_defect.run_defect_inference = defect_fn(is_defect=False)
    fake_measurement.run_measurement_inference = measurement_fn(passed=True)

    result = station_registry._run_pipeline(FRAME, make_defect_config(), make_measurement_config(), draw_result=True)

    assert result.is_defect is False
    assert result.measurement_data is not None
    assert result.defect_label is not None and "|" in result.defect_label


def test_shared_camera_nok_if_defect_fails_even_when_measurement_passes(fake_pipeline_modules):
    fake_defect, fake_measurement = fake_pipeline_modules
    fake_defect.run_defect_inference = defect_fn(is_defect=True)
    fake_measurement.run_measurement_inference = measurement_fn(passed=True)

    result = station_registry._run_pipeline(FRAME, make_defect_config(), make_measurement_config(), draw_result=True)

    assert result.is_defect is True


def test_shared_camera_nok_if_measurement_fails_even_when_defect_passes(fake_pipeline_modules):
    fake_defect, fake_measurement = fake_pipeline_modules
    fake_defect.run_defect_inference = defect_fn(is_defect=False)
    fake_measurement.run_measurement_inference = measurement_fn(passed=False)

    result = station_registry._run_pipeline(FRAME, make_defect_config(), make_measurement_config(), draw_result=True)

    assert result.is_defect is True


def test_shared_camera_measurement_runs_against_defects_output_frame(fake_pipeline_modules):
    # So drawn defect boxes and the measurement ellipse both land on the one
    # returned frame instead of two independent copies of the raw capture.
    fake_defect, fake_measurement = fake_pipeline_modules
    received_frames = []
    fake_defect.run_defect_inference = defect_fn(is_defect=False)
    fake_measurement.run_measurement_inference = measurement_fn(passed=True, received_frames=received_frames)

    result = station_registry._run_pipeline(FRAME, make_defect_config(), make_measurement_config(), draw_result=True)

    assert received_frames[0] is DEFECT_FRAME_OUT
    assert result.frame is MEASUREMENT_FRAME_OUT


def test_shared_camera_with_forced_verdict_still_runs_real_measurement(fake_pipeline_modules):
    # forced_verdict (sim harness) is only ever consulted on the defect
    # path -- measurement always runs for real, even on a shared camera.
    _fake_defect, fake_measurement = fake_pipeline_modules
    received_frames = []
    fake_measurement.run_measurement_inference = measurement_fn(passed=True, received_frames=received_frames)

    result = station_registry._run_pipeline(
        FRAME, make_defect_config(), make_measurement_config(), draw_result=True, forced_verdict="NOK"
    )

    assert len(received_frames) == 1  # measurement genuinely ran, not skipped
    assert result.is_defect is True  # forced NOK from defect side wins the OR


def test_neither_config_is_plain_passthrough(fake_pipeline_modules):
    result = station_registry._run_pipeline(FRAME, None, None, draw_result=True)
    assert result.is_defect is False
    assert result.frame is FRAME
