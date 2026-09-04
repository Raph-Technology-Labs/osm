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

Point = Tuple[int, int]
# ((center_x, center_y), (axis1, axis2), angle_degrees) -- cv2.fitEllipse's
# return shape; axis1/axis2 are full diameter lengths, not radii.
Ellipse = Tuple[Tuple[float, float], Tuple[float, float], float]


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
    ellipse: Ellipse,
    diameter_mm: float,
    ovality_mm: float,
    roi_offset: Point = (0, 0),
) -> np.ndarray:
    drawn = frame.copy()
    ox, oy = roi_offset
    (cx, cy), axes, angle = ellipse
    shifted_ellipse = ((cx + ox, cy + oy), axes, angle)

    cv2.ellipse(drawn, shifted_ellipse, MEASURE_COLOR, 2)
    cv2.circle(drawn, (int(cx + ox), int(cy + oy)), 3, MEASURE_COLOR, -1)
    cv2.putText(
        drawn, f"dia {diameter_mm:.2f}mm  oval {ovality_mm:.2f}mm", (ox + 10, oy + 25),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, MEASURE_COLOR, 2, cv2.LINE_AA,
    )
    return drawn
