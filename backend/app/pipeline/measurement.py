"""Runs a station's configured measurement (caliper method only, per
config_loader.MeasurementConfig.method) against one captured frame.

Pure OpenCV, no AI locator model: threshold the whole frame to isolate the
dark part against a light background, take the largest contour, caliper it
for diameter (leftmost/rightmost + topmost/bottommost extremes), and check
roundness via centroid-to-contour radial spread for ovality -- see
measure_diameter_px's docstring for why ovality isn't just the difference
between the two caliper diameters. (The AI-model ROI-crop stage that used
to precede this is commented out in run_measurement_inference -- no
part-trained locator model exists yet anyway, so it was always falling
through to whole-frame measurement in practice.)
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
# (leftmost, rightmost, topmost, bottommost) contour points -- the four
# calipered extremes used for the diameter measurement below.
Extremes = Tuple[Point, Point, Point, Point]


@dataclass
class MeasurementResult:
    diameter_mm: float
    ovality_mm: float
    passed: bool
    frame_out: np.ndarray


@dataclass
class ContourMeasurement:
    avg_diameter_px: float
    ovality_px: float
    contour: np.ndarray
    extremes: Extremes
    centroid: Point
    # 2*radius at every contour point, in the same order as contour's own
    # points -- a per-angle "diameter as measured from the centroid at that
    # point," for the full-profile tolerance-band check + spoke drawing
    # below (both need per-point diameter and its point location together).
    point_diameters_px: np.ndarray


def measure_diameter_px(roi: np.ndarray) -> ContourMeasurement:
    """Finds the largest dark blob in roi and returns a ContourMeasurement.

    Diameter, radii method: distance from the contour's centroid to every
    contour point (that point's radius, at its own angle), doubled to a
    per-point diameter, then averaged over all of them -- not just the
    2-axis caliper (leftmost/rightmost + topmost/bottommost extremes, still
    computed and returned for the drawn overlay's caliper cross, but no
    longer what avg_diameter_px is derived from). Averaging over hundreds of
    points is inherently more noise-robust than 4 extreme points, since
    per-pixel edge jitter on any single point barely moves the mean.

    Ovality (informational only -- see run_measurement_inference, not a
    pass/fail gate): max(radii)-min(radii), doubled to the same diameter
    scale. Kept for display/diagnostics -- a real demold defect anywhere on
    the perimeter still shows up here even though it no longer fails the
    part on its own.

    Raises ValueError if nothing dark enough is found, or the contour is
    degenerate (zero area, no centroid) -- a fail-safe caller should treat
    as NOK, not crash."""
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    _, mask = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("no contour found -- nothing dark enough against the background")
    contour = max(contours, key=cv2.contourArea)
    points = contour.reshape(-1, 2).astype(np.float64)

    leftmost = tuple(points[points[:, 0].argmin()])
    rightmost = tuple(points[points[:, 0].argmax()])
    topmost = tuple(points[points[:, 1].argmin()])
    bottommost = tuple(points[points[:, 1].argmax()])

    moments = cv2.moments(contour)
    if moments["m00"] == 0:
        raise ValueError("degenerate contour -- zero area, cannot locate centroid")
    centroid_x, centroid_y = moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]
    radii = np.hypot(points[:, 0] - centroid_x, points[:, 1] - centroid_y)
    point_diameters_px = 2 * radii

    # Size, radii method: mean of every contour point's own diameter
    # (2*radius from the centroid), not just the 2-axis caliper -- averaging
    # over hundreds of points is naturally more noise-robust than 4 extreme
    # points, so this also doubles as the fix for real-camera edge jitter
    # nudging the reported size around. ovality_px kept only as an informational
    # roundness readout (not a pass/fail gate) -- see run_measurement_inference.
    avg_diameter_px = point_diameters_px.mean()
    ovality_px = 2 * (radii.max() - radii.min())

    extremes = tuple((int(x), int(y)) for x, y in (leftmost, rightmost, topmost, bottommost))
    return ContourMeasurement(
        avg_diameter_px=avg_diameter_px,
        ovality_px=ovality_px,
        contour=contour,
        extremes=extremes,
        centroid=(int(centroid_x), int(centroid_y)),
        point_diameters_px=point_diameters_px,
    )


def run_measurement_inference(
    frame: np.ndarray, measurement_config: "MeasurementConfig", draw_result: bool = True
) -> MeasurementResult:
    roi = frame
    roi_offset: Point = (0, 0)

    # AI locator model disabled -- pure OpenCV caliper measurement against
    # the whole frame (config's method: caliper). No part-trained locator
    # model exists yet anyway (stock yolo11n.pt has no "rubber_part" class),
    # so this was always falling through to whole-frame measurement in
    # practice; skipping the model call outright avoids the wasted
    # inference. Re-enable by uncommenting once a real locator model
    # exists and cropping to its ROI is actually wanted.
    # if measurement_config.uses_own_model():
    #     results = model_registry.predict(
    #         measurement_config.model_path, measurement_config.model_type, frame, conf=0.25
    #     )
    #     r = results[0]
    #     names = r.names
    #     allowed = set(measurement_config.allowed_classes)
    #     box = next((b for b in r.boxes if names[int(b.cls[0])] in allowed), None)
    #     if box is not None:
    #         x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
    #         roi = frame[y1:y2, x1:x2]
    #         roi_offset = (x1, y1)
    #     else:
    #         log.info(
    #             "No %s detection in frame (stock model isn't part-trained) -- "
    #             "measuring the whole frame instead of a cropped ROI",
    #             sorted(allowed),
    #         )

    cm = measure_diameter_px(roi)

    param = measurement_config.parameters.get("diameter_mm")
    # mm-per-pixel: diameter_mm = diameter_px * calibration_factor. Derive
    # it from a real capture as (known_mm / measured_px) -- e.g. 18.0mm
    # part / 443.0px measured = 0.0406mm/px -- not (px/mm).
    calibration_factor = param.calibration_factor if param else 0.1
    # float()'d immediately -- cm's fields are numpy float64 (they come out
    # of array ops in measure_diameter_px), and a comparison chain like
    # `lo <= diameter_mm <= hi` against a numpy float64 can return numpy's
    # bool_ instead of a real Python bool when it short-circuits False.
    # numpy.bool_ isn't JSON-serializable, and this result eventually goes
    # through zeromq.publish_inspection_result's json.dumps -- plain floats
    # here keep every comparison/bool derived from them native Python types.
    ovality_mm = float(cm.ovality_px * calibration_factor)
    point_diameters_mm = cm.point_diameters_px * calibration_factor

    # upper_limit/lower_limit are tolerances (+/- from nominal_value), not
    # absolute bounds -- nominal=18, upper_limit=0.5, lower_limit=0.5 means
    # the pass window is 17.5-18.5, not "diameter must be between 0.5 and 18.5".
    resolved_upper = resolved_lower = None
    if param and param.nominal_value is not None and param.upper_limit is not None and param.lower_limit is not None:
        resolved_upper = param.nominal_value + param.upper_limit
        resolved_lower = param.nominal_value - param.lower_limit

    # Per-point gate, NOT the overall/average diameter: every contour
    # point's own local diameter (radii method, see measure_diameter_px)
    # is checked against the tolerance band individually. A single point
    # outside the band fails the whole part -- an averaged reading can hide
    # a local demold defect that only affects part of the perimeter.
    out_of_tolerance = np.zeros(len(point_diameters_mm), dtype=bool)
    passed = True
    if resolved_upper is not None:
        out_of_tolerance = (point_diameters_mm < resolved_lower) | (point_diameters_mm > resolved_upper)
        passed = not out_of_tolerance.any()

    # Reported "measured" diameter is the single point that deviates the
    # most from nominal_value (the worst offender), not an average -- on a
    # NOK part this is the actual out-of-tolerance value that caused the
    # rejection; on an OK part it's still the closest call, i.e. the point
    # tightest against the tolerance edge.
    if param and param.nominal_value is not None:
        worst_idx = np.argmax(np.abs(point_diameters_mm - param.nominal_value))
    else:
        worst_idx = np.argmax(point_diameters_mm)
    diameter_mm = float(point_diameters_mm[worst_idx])

    frame_out = frame
    if draw_result:
        frame_out = draw.draw_measurement(
            frame, cm.contour, cm.centroid, out_of_tolerance, cm.extremes, diameter_mm, ovality_mm, roi_offset
        )

    return MeasurementResult(diameter_mm=diameter_mm, ovality_mm=ovality_mm, passed=passed, frame_out=frame_out)
