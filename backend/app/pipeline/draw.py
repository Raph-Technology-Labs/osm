"""Draws inference results onto a frame copy for the live preview -- gated
by each station's pipeline.result.draw_result in machine_config.yaml.
"""

from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np

DEFECT_COLOR = (0, 0, 255)  # red (BGR) -- a detection that's a triggered allowed_defect
DETECT_COLOR = (0, 200, 0)  # green -- detected but not in allowed_defects
MEASURE_COLOR = (255, 128, 0)  # orange -- measurement ellipse overlay
IN_TOLERANCE_COLOR = (0, 200, 0)  # green -- this contour point's local diameter is in-spec
OUT_OF_TOLERANCE_COLOR = (255, 255, 0)  # cyan -- out of the tolerance band; not red, kept distinct from DEFECT_COLOR's red boxes elsewhere

Point = Tuple[int, int]
# (leftmost, rightmost, topmost, bottommost) contour points, ROI-local --
# matches pipeline.measurement.measure_diameter_px's Extremes shape.
Extremes = Tuple[Point, Point, Point, Point]


def draw_defect_boxes(frame: np.ndarray, boxes, names, allowed_defects: set) -> np.ndarray:
    drawn = frame.copy()
    for box in boxes:
        cls_name = names[int(box.cls[0])]
        conf = float(box.conf[0])
        x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
        color = DEFECT_COLOR if cls_name in allowed_defects else DETECT_COLOR
        cv2.rectangle(drawn, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            drawn, f"{cls_name} {conf:.2f}", (x1, max(y1 - 8, 0)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA,
        )
    return drawn


def draw_measurement(
    frame: np.ndarray,
    contour: np.ndarray,
    centroid: Point,
    out_of_tolerance,  # np.ndarray[bool], same length/order as contour's points
    extremes: Extremes,
    diameter_mm: float,
    ovality_mm: float,
    roi_offset: Point = (0, 0),
) -> np.ndarray:
    """Caliper + full-profile overlay. Draws:
    - the horizontal (leftmost<->rightmost) and vertical (topmost<->bottommost)
      calipers actually used for the diameter measurement
    - a spoke from the centroid to every contour point, green if that
      point's own local diameter is within the tolerance band and red if
      not -- makes it possible to see exactly where on the part a demold
      defect is, not just that ovality/size failed somewhere."""
    drawn = frame.copy()
    ox, oy = roi_offset
    cx, cy = int(centroid[0] + ox), int(centroid[1] + oy)

    points = contour.reshape(-1, 2)
    for (px, py), bad in zip(points, out_of_tolerance):
        color = OUT_OF_TOLERANCE_COLOR if bad else IN_TOLERANCE_COLOR
        cv2.line(drawn, (cx, cy), (int(px + ox), int(py + oy)), color, 1, cv2.LINE_AA)

    leftmost, rightmost, topmost, bottommost = (
        (int(x + ox), int(y + oy)) for x, y in extremes
    )
    cv2.line(drawn, leftmost, rightmost, MEASURE_COLOR, 2)
    cv2.line(drawn, topmost, bottommost, MEASURE_COLOR, 2)
    for pt in (leftmost, rightmost, topmost, bottommost):
        cv2.circle(drawn, pt, 4, MEASURE_COLOR, -1)
    cv2.circle(drawn, (cx, cy), 3, MEASURE_COLOR, -1)

    cv2.putText(
        drawn, f"dia {diameter_mm:.2f}mm  oval {ovality_mm:.2f}mm", (ox + 10, oy + 25),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, MEASURE_COLOR, 2, cv2.LINE_AA,
    )
    return drawn
