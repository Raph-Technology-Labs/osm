# """Read-side rollups over a session's persisted results.

# The Inspection page's live tally (useResultTally) only sees what streams past
# while the page is open -- a reload zeroes it, and it can miss a part if two
# pass the same camera between renders. These functions read the rows
# results_writer actually wrote, so the numbers survive a reload and match what
# a report would say.

# Rows arrive through results_writer's queue, so a just-fired part can lag by a
# fraction of a second. That is expected: this is a summary, not a live feed --
# the live feed is ZMQ (CLAUDE.md Section 9).
# """

# from __future__ import annotations

# from typing import Optional

# from sqlalchemy.orm import Session, joinedload

# from app.models.models import CameraResult, SessionResult


# def _camera_results(db: Session, session_id: int):
#     """Every CameraResult belonging to one session, with its parent row."""
#     return (
#         db.query(CameraResult, SessionResult)
#         .join(SessionResult, CameraResult.session_result_id == SessionResult.id)
#         .filter(SessionResult.session_id == session_id)
#         .all()
#     )


# def defect_totals(db: Session, session_id: int) -> dict:
#     """Per-defect-class counts, over DEFECT rows only.

#     CameraResult.is_defective is set for every failing camera regardless of
#     pipeline -- inspection_session computes `passed = not captured.is_defect`
#     for measurement cameras too, so an out-of-tolerance part sets it exactly
#     like a real defect does. Counting it blind put measurement failures in
#     the Defect card. measurement_data is the discriminator: a measurement row
#     carries it, a defect row never does.

#     `deciding` counts the label that actually made a camera NOK -- the number
#     an operator acts on. `detected` counts every class the model reported,
#     including ones an allowed_defects filter then ignored.
#     """
#     deciding: dict[str, int] = {}
#     detected: dict[str, int] = {}
#     nok_cameras = 0
#     total_cameras = 0

#     for cam, _ in _camera_results(db, session_id):
#         if cam.measurement_data:
#             continue  # a measurement row, not this card's business
#         total_cameras += 1
#         if cam.is_defective:
#             nok_cameras += 1
#         if cam.defect_label:
#             deciding[cam.defect_label] = deciding.get(cam.defect_label, 0) + 1
#         for det in cam.all_detections or []:
#             name = (det or {}).get("class_name")
#             if name:
#                 detected[name] = detected.get(name, 0) + 1

#     return {
#         "deciding": dict(sorted(deciding.items(), key=lambda kv: -kv[1])),
#         "detected": dict(sorted(detected.items(), key=lambda kv: -kv[1])),
#         "nok_cameras": nok_cameras,
#         "total_cameras": total_cameras,
#     }

# def measurement_totals(db: Session, session_id: int) -> dict:
#     """Per-parameter pass/fail plus a simple spread.

#     Keyed by the parameter name as written in measurement_data (diameter_mm,
#     length_mm, ...), so a part measured on two parameters reports both
#     separately rather than collapsing into one pass rate.
#     """
#     params: dict[str, dict] = {}

#     for cam, _ in _camera_results(db, session_id):
#         for name, m in (cam.measurement_data or {}).items():
#             if not isinstance(m, dict):
#                 continue
#             entry = params.setdefault(
#                 name,
#                 {"ok": 0, "nok": 0, "measured": [], "nominal": m.get("nominal"), "unit": m.get("unit") or "mm"},
#             )
#             if m.get("passed"):
#                 entry["ok"] += 1
#             else:
#                 entry["nok"] += 1
#             value = m.get("measured")
#             if isinstance(value, (int, float)):
#                 entry["measured"].append(float(value))

#     out = {}
#     for name, entry in params.items():
#         values = entry.pop("measured")
#         total = entry["ok"] + entry["nok"]
#         mean = sum(values) / len(values) if values else None
#         out[name] = {
#             **entry,
#             "total": total,
#             "mean": round(mean, 4) if mean is not None else None,
#             "min": round(min(values), 4) if values else None,
#             "max": round(max(values), 4) if values else None,
#         }
#     return out


# def station_totals(db: Session, session_id: int) -> dict:
#     """Pass/fail per station id, from the station's own aggregated verdict."""
#     rows = (
#         db.query(SessionResult)
#         .filter(SessionResult.session_id == session_id)
#         .all()
#     )
#     out: dict[str, dict] = {}
#     for r in rows:
#         entry = out.setdefault(r.station_id, {"ok": 0, "nok": 0, "rejected": 0})
#         if r.overall_passed is True:
#             entry["ok"] += 1
#         elif r.overall_passed is False:
#             entry["nok"] += 1
#         if r.rejected:
#             entry["rejected"] += 1
#     return out


# def recent_events(
#     db: Session,
#     session_id: int,
#     limit: int = 200,
#     only_nok: bool = False,
# ) -> list[dict]:
#     """Newest-first station fires, flattened one row per camera.

#     A part crossing s1 -> s2 -> exit1 produces several rows; they share
#     ring_part_id, which is what ties them to one physical part.
#     """
#     query = (
#         db.query(SessionResult)
#         .options(joinedload(SessionResult.camera_results))
#         .filter(SessionResult.session_id == session_id)
#     )
#     if only_nok:
#         query = query.filter(SessionResult.overall_passed.is_(False))

#     rows = query.order_by(SessionResult.id.desc()).limit(limit).all()

#     events: list[dict] = []
#     for r in rows:
#         base = {
#             "session_result_id": r.id,
#             "fired_at": r.fired_at,
#             "station_id": r.station_id,
#             "ring_part_id": r.ring_part_id,
#             "station_fire_no": r.station_fire_no,
#             "overall_passed": r.overall_passed,
#             "rejected": r.rejected,
#         }
#         if not r.camera_results:
#             events.append({**base, "camera_id": None, "pipeline": "aggregation", "detail": None})
#             continue
#         for cam in r.camera_results:
#             if cam.measurement_data:
#                 pipeline = "measurement"
#                 detail = ", ".join(
#                     f"{name} {m.get('measured')}{m.get('unit') or ''}"
#                     for name, m in cam.measurement_data.items()
#                     if isinstance(m, dict)
#                 )
#             elif cam.defect_label:
#                 pipeline = "defect"
#                 detail = cam.defect_label
#                 if cam.defect_confidence is not None:
#                     detail += f" ({cam.defect_confidence:.2f})"
#             else:
#                 pipeline = "defect" if cam.is_defective is not None else "—"
#                 detail = "clean" if cam.is_defective is False else None
#             events.append(
#                 {
#                     **base,
#                     "camera_id": cam.camera_id,
#                     "pipeline": pipeline,
#                     "detail": detail,
#                     "camera_passed": cam.camera_passed,
#                 }
#             )
#     return events


# def build_analysis(db: Session, session_id: int) -> dict:
#     return {
#         "session_id": session_id,
#         "defects": defect_totals(db, session_id),
#         "measurements": measurement_totals(db, session_id),
#         "stations": station_totals(db, session_id),
#     }


"""Read-side rollups over a session's persisted results.

The Inspection page's live tally (useResultTally) only sees what streams past
while the page is open -- a reload zeroes it, and it can miss a part if two
pass the same camera between renders. These functions read the rows
results_writer actually wrote, so the numbers survive a reload and match what
a report would say.

Rows arrive through results_writer's queue, so a just-fired part can lag by a
fraction of a second. That is expected: this is a summary, not a live feed --
the live feed is ZMQ (CLAUDE.md Section 9).
"""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models.models import CameraResult, SessionResult


def _camera_results(db: Session, session_id: int):
    """Every CameraResult belonging to one session, with its parent row."""
    return (
        db.query(CameraResult, SessionResult)
        .join(SessionResult, CameraResult.session_result_id == SessionResult.id)
        .filter(SessionResult.session_id == session_id)
        .all()
    )


# --- which card does a row belong to? ---------------------------------------
#
# CameraResult.is_defective is set for every failing camera regardless of
# pipeline -- inspection_session computes `passed = not captured.is_defect`
# for measurement cameras too, so an out-of-tolerance part sets it exactly
# like a real defect does. Counting it blind put measurement failures in the
# Defect card.
#
# The earlier fix -- "skip any row with measurement_data" -- overcorrected: a
# camera running BOTH pipelines vanished from the Defect card entirely, and so
# did any defect row that happened to carry an empty measurement payload.
#
# So classify on evidence, and let a row count toward both cards when it
# genuinely carries both. pipeline_name is trusted FIRST when it says
# something real: today it is hardcoded "pipeline1" at the writer, which is
# why it can't be relied on alone yet. Set it to "defect"/"measurement" in
# CameraResultItem and this degrades to a single unambiguous check.

_KNOWN_PIPELINES = {"defect", "measurement"}


def _declared_pipeline(cam: CameraResult) -> str | None:
    name = (cam.pipeline_name or "").strip().lower()
    return name if name in _KNOWN_PIPELINES else None


def _has_measurement(cam: CameraResult) -> bool:
    data = cam.measurement_data or {}
    return any(isinstance(v, dict) for v in data.values())


def _has_defect_evidence(cam: CameraResult) -> bool:
    return bool(cam.defect_label) or bool(cam.all_detections)


def _is_defect_row(cam: CameraResult) -> bool:
    declared = _declared_pipeline(cam)
    if declared:
        return declared == "defect"
    # No usable declaration: a row is the Defect card's business unless it is
    # purely a measurement row -- measurement payload and nothing a defect
    # model produced.
    return not (_has_measurement(cam) and not _has_defect_evidence(cam))


def defect_totals(db: Session, session_id: int) -> dict:
    """Per-defect-class counts, over DEFECT rows only.

    `deciding` counts the label that actually made a camera NOK -- the number
    an operator acts on. `detected` counts every class the model reported,
    including ones an allowed_defects filter then ignored.
    """
    deciding: dict[str, int] = {}
    detected: dict[str, int] = {}
    nok_cameras = 0
    total_cameras = 0

    for cam, _ in _camera_results(db, session_id):
        if not _is_defect_row(cam):
            continue

        total_cameras += 1
        if cam.is_defective:
            nok_cameras += 1
            # A NOK with no label still has to appear. Silently dropping it
            # made the card read "no defects" while the counter said NOK --
            # the most confusing possible state for an operator.
            label = cam.defect_label or "unlabelled"
            deciding[label] = deciding.get(label, 0) + 1

        for det in cam.all_detections or []:
            name = (det or {}).get("class_name") or (det or {}).get("label")
            if name:
                detected[name] = detected.get(name, 0) + 1

    return {
        "deciding": dict(sorted(deciding.items(), key=lambda kv: -kv[1])),
        "detected": dict(sorted(detected.items(), key=lambda kv: -kv[1])),
        "nok_cameras": nok_cameras,
        "total_cameras": total_cameras,
    }


def measurement_totals(db: Session, session_id: int) -> dict:
    """Per-parameter pass/fail plus a simple spread.

    Keyed by the parameter name as written in measurement_data (diameter_mm,
    length_mm, ...), so a part measured on two parameters reports both
    separately rather than collapsing into one pass rate.

    Driven by the payload rather than by pipeline_name: a row with no
    measurement_data contributes nothing here whatever it claims to be.
    """
    params: dict[str, dict] = {}

    for cam, _ in _camera_results(db, session_id):
        for name, m in (cam.measurement_data or {}).items():
            if not isinstance(m, dict):
                continue
            entry = params.setdefault(
                name,
                {
                    "ok": 0,
                    "nok": 0,
                    "measured": [],
                    "nominal": m.get("nominal"),
                    "unit": m.get("unit") or "mm",
                },
            )
            if m.get("passed"):
                entry["ok"] += 1
            else:
                entry["nok"] += 1
            value = m.get("measured")
            if isinstance(value, (int, float)):
                entry["measured"].append(float(value))

    out = {}
    for name, entry in params.items():
        values = entry.pop("measured")
        total = entry["ok"] + entry["nok"]
        mean = sum(values) / len(values) if values else None
        out[name] = {
            **entry,
            "total": total,
            "mean": round(mean, 4) if mean is not None else None,
            "min": round(min(values), 4) if values else None,
            "max": round(max(values), 4) if values else None,
        }
    return out


def station_totals(db: Session, session_id: int) -> dict:
    """Pass/fail per station id, from the station's own aggregated verdict."""
    rows = db.query(SessionResult).filter(SessionResult.session_id == session_id).all()
    out: dict[str, dict] = {}
    for r in rows:
        entry = out.setdefault(r.station_id, {"ok": 0, "nok": 0, "rejected": 0})
        if r.overall_passed is True:
            entry["ok"] += 1
        elif r.overall_passed is False:
            entry["nok"] += 1
        if r.rejected:
            entry["rejected"] += 1
    return out


def recent_events(
    db: Session,
    session_id: int,
    limit: int = 200,
    only_nok: bool = False,
) -> list[dict]:
    """Newest-first station fires, flattened one row per camera.

    A part crossing s1 -> s2 -> exit1 produces several rows; they share
    ring_part_id, which is what ties them to one physical part.
    """
    query = (
        db.query(SessionResult)
        .options(joinedload(SessionResult.camera_results))
        .filter(SessionResult.session_id == session_id)
    )
    if only_nok:
        query = query.filter(SessionResult.overall_passed.is_(False))

    rows = query.order_by(SessionResult.id.desc()).limit(limit).all()

    events: list[dict] = []
    for r in rows:
        base = {
            "session_result_id": r.id,
            "fired_at": r.fired_at,
            "station_id": r.station_id,
            "ring_part_id": r.ring_part_id,
            "station_fire_no": r.station_fire_no,
            "overall_passed": r.overall_passed,
            "rejected": r.rejected,
        }
        if not r.camera_results:
            events.append({**base, "camera_id": None, "pipeline": "aggregation", "detail": None})
            continue
        for cam in r.camera_results:
            # Same classification the cards use, so the log and the cards can
            # never label the same row differently.
            if _has_measurement(cam):
                pipeline = "measurement"
                detail = ", ".join(
                    f"{name} {m.get('measured')}{m.get('unit') or ''}"
                    for name, m in cam.measurement_data.items()
                    if isinstance(m, dict)
                )
            elif cam.defect_label:
                pipeline = "defect"
                detail = cam.defect_label
                if cam.defect_confidence is not None:
                    detail += f" ({cam.defect_confidence:.2f})"
            else:
                pipeline = "defect" if cam.is_defective is not None else "—"
                detail = "clean" if cam.is_defective is False else None
            events.append(
                {
                    **base,
                    "camera_id": cam.camera_id,
                    "pipeline": pipeline,
                    "detail": detail,
                    "camera_passed": cam.camera_passed,
                }
            )
    return events


def build_analysis(db: Session, session_id: int) -> dict:
    return {
        "session_id": session_id,
        "defects": defect_totals(db, session_id),
        "measurements": measurement_totals(db, session_id),
        "stations": station_totals(db, session_id),
    }