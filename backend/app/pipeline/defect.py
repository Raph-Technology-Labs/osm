"""Runs a trigger's configured defect model against one captured frame.

Scope: defect classification only (station 2's "Defect Detection" trigger).
Measurement (station 1's caliper diameter read) is separate work -- see
app/pipeline/measurement.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

import numpy as np

from app.pipeline import draw, model_registry

if TYPE_CHECKING:
    from app.config.config_loader import DefectConfig


def run_defect_inference(
    frame: np.ndarray, defect_config: "DefectConfig", draw_result: bool = True
) -> Tuple[bool, Optional[str], np.ndarray]:
    """Returns (is_defect, defect_label, frame_out). is_defect is True iff at
    least one detection lands in allowed_defects at or above its confidence
    threshold (resolved_classes overrides conf_thresh per-class once
    Part.defects merge is wired -- see config_loader._merge_part_overrides;
    today resolved_classes is always empty, so conf_thresh applies to
    everything). detect_classes not in allowed_defects are detected but
    never flip the verdict -- e.g. a model that also reports "bed" alongside
    "cat" only cares about "cat" per this trigger's allowed_defects.

    frame_out has bounding boxes for every detect_classes detection drawn on
    it (red = triggered allowed_defect, green = detected but not flagged)
    when draw_result is True; otherwise it's the untouched input frame.
    """
    results = model_registry.predict(
        defect_config.model_path, defect_config.model_type, frame, conf=defect_config.conf_thresh
    )
    r = results[0]
    names = r.names

    detect_set = set(defect_config.detect_classes)
    allowed_set = set(defect_config.allowed_defects)
    detected_boxes = [b for b in r.boxes if names[int(b.cls[0])] in detect_set]

    best_label: Optional[str] = None
    best_conf = -1.0
    for box in detected_boxes:
        cls_name = names[int(box.cls[0])]
        conf = float(box.conf[0])
        thresh = defect_config.resolved_classes.get(cls_name, defect_config.conf_thresh)
        if conf < thresh or cls_name not in allowed_set:
            continue
        if conf > best_conf:
            best_conf = conf
            best_label = cls_name

    frame_out = frame
    if draw_result and detected_boxes:
        frame_out = draw.draw_defect_boxes(frame, detected_boxes, names, allowed_set)

    return best_label is not None, best_label, frame_out
