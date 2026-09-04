"""Runs a station's configured measurement (caliper method only, per
config_loader.MeasurementConfig.method) against one captured frame.

Two stages:
1. Model detection (allowed_classes), if a model_path is configured, locates
   the part's bounding box, used as the region of interest for stage 2. When
   no model_path is set (uses_own_model() is False), stage 1 is skipped
   entirely and stage 2 runs on the whole frame -- that's the expected mode
   until a real part-trained detector exists (stock yolo11n.pt is
   COCO-pretrained, it doesn't know a "rubber_part" class).
2. Within the ROI: threshold to isolate the dark part against a light
   background, take the largest contour, and fit an ellipse to it
   (cv2.fitEllipse) -- a least-squares fit over every contour point, not
   just a few extremes, so it's robust to local noise and correctly reports
   ovality (major - minor) even when the part's actual long axis isn't
   aligned to any particular sampled angle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Tuple

import cv2
import numpy as np

from app.pipeline import draw, model_registry

if TYPE_CHECKING:
    from app.config.config_loader import MeasurementConfig

log = logging.getLogger("pipeline.measurement")

Point = Tuple[int, int]
# ((center_x, center_y), (axis1, axis2), angle_degrees) -- cv2.fitEllipse's
# return shape; axis1/axis2 are full diameter lengths, not radii.
Ellipse = Tuple[Tuple[float, float], Tuple[float, float], float]


@dataclass
class MeasurementResult:
    diameter_mm: float
    ovality_mm: float
    passed: bool
    frame_out: np.ndarray


def measure_diameter_px(roi: np.ndarray) -> Tuple[float, float, np.ndarray, Ellipse]:
    """Returns (avg_diameter_px, ovality_px, largest_contour, ellipse) for
    the largest dark blob in roi. Raises ValueError if nothing dark enough
    is found, or the contour is too small to fit an ellipse to (cv2.fitEllipse
    needs >= 5 points) -- a fail-safe caller should treat as NOK, not crash."""
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    _, mask = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("no contour found -- nothing dark enough against the background")
    contour = max(contours, key=cv2.contourArea)
    if len(contour) < 5:
        raise ValueError(f"largest contour has only {len(contour)} points -- fitEllipse needs >= 5")

    ellipse = cv2.fitEllipse(contour)
    (_cx, _cy), (axis1, axis2), _angle = ellipse
    major_px, minor_px = max(axis1, axis2), min(axis1, axis2)
    avg_diameter_px = (major_px + minor_px) / 2
    ovality_px = major_px - minor_px
    return avg_diameter_px, ovality_px, contour, ellipse


def run_measurement_inference(
    frame: np.ndarray, measurement_config: "MeasurementConfig", draw_result: bool = True
) -> MeasurementResult:
    roi = frame
    roi_offset: Point = (0, 0)

    if measurement_config.uses_own_model():
        results = model_registry.predict(
            measurement_config.model_path, measurement_config.model_type, frame, conf=0.25
        )
        r = results[0]
        names = r.names
        allowed = set(measurement_config.allowed_classes)
        box = next((b for b in r.boxes if names[int(b.cls[0])] in allowed), None)
        if box is not None:
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
            roi = frame[y1:y2, x1:x2]
            roi_offset = (x1, y1)
        else:
            log.info(
                "No %s detection in frame (stock model isn't part-trained) -- "
                "measuring the whole frame instead of a cropped ROI",
                sorted(allowed),
            )

    diameter_px, ovality_px, _contour, ellipse = measure_diameter_px(roi)

    param = measurement_config.parameters.get("diameter_mm")
    calibration_factor = param.calibration_factor if param else 10.0
    diameter_mm = diameter_px / calibration_factor
    ovality_mm = ovality_px / calibration_factor

    passed = True
    if param and param.upper_limit is not None and param.lower_limit is not None:
        passed = param.lower_limit <= diameter_mm <= param.upper_limit

    frame_out = frame
    if draw_result:
        frame_out = draw.draw_measurement(frame, ellipse, diameter_mm, ovality_mm, roi_offset)

    return MeasurementResult(diameter_mm=diameter_mm, ovality_mm=ovality_mm, passed=passed, frame_out=frame_out)
