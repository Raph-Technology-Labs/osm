"""Dashboard aggregation + CSV report export.

Endpoint/query conventions -- `time_filter` query param, one base query
reused for every derived stat, a {total,page,limit,data} pagination
envelope -- follow gcm's dashboard router pattern
(/home/thor/rai/gcm-auto-training-rai/backend/app/routers/dashboard/dashboard.py).
The actual endpoint *shapes* are new, built against OSM's own richer
schema: gcm is a parts-counting machine with one verdict per part and no
per-station or per-camera concept at all, so station_breakdown/
defect_breakdown below have no gcm equivalent to copy -- SessionResult
(per station-fire) and CameraResult (per camera, with defect/measurement
detail) support things gcm's schema structurally cannot express.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.auth.dependencies import require_role
from app.db.db import get_db
from app.models.models import CameraResult, PartSession, SessionResult

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_role("operator"))])

# CLAUDE.md Section 11: "CSV/PDF export: ... cap row count server-side even
# if UI requests unbounded."
MAX_REPORT_ROWS = 10_000


def _date_range(time_filter: str, start_date: Optional[str], end_date: Optional[str]):
    now = datetime.now(timezone.utc)
    if time_filter == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    if time_filter == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now + timedelta(seconds=1)
    if time_filter == "range":
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="start_date and end_date required for time_filter=range")
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date) + timedelta(days=1)  # inclusive end date
        return start, end
    if time_filter == "all":
        return None, None
    raise HTTPException(status_code=400, detail=f"unknown time_filter {time_filter!r}")


@router.get("/stats")
def get_stats(
    time_filter: str = Query("all"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    start, end = _date_range(time_filter, start_date, end_date)
    q = db.query(PartSession)
    if start:
        q = q.filter(PartSession.session_start >= start, PartSession.session_start < end)

    total_sessions = q.count()
    total_fired, total_passed, total_failed = q.with_entities(
        func.coalesce(func.sum(PartSession.total_fired), 0),
        func.coalesce(func.sum(PartSession.total_passed), 0),
        func.coalesce(func.sum(PartSession.total_failed), 0),
    ).first()
    return {
        "total_sessions": total_sessions,
        "total_fired": total_fired,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "pass_rate": (total_passed / total_fired) if total_fired else None,
    }


@router.get("/recent-sessions")
def recent_sessions(
    time_filter: str = Query("all"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    start, end = _date_range(time_filter, start_date, end_date)
    q = db.query(PartSession)
    if start:
        q = q.filter(PartSession.session_start >= start, PartSession.session_start < end)

    total = q.count()
    rows = q.order_by(PartSession.session_start.desc()).offset((page - 1) * limit).limit(limit).all()
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "data": [
            {
                "session_id": r.id,
                "part_code": r.part_code,
                "part_name": r.part_name,
                "session_start": r.session_start,
                "session_end": r.session_end,
                "total_fired": r.total_fired,
                "total_passed": r.total_passed,
                "total_failed": r.total_failed,
            }
            for r in rows
        ],
    }


@router.get("/station-breakdown")
def station_breakdown(
    time_filter: str = Query("all"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Reject rate per station -- no gcm equivalent (see module docstring)."""
    start, end = _date_range(time_filter, start_date, end_date)
    q = db.query(
        SessionResult.station_id,
        func.count(SessionResult.id),
        func.sum(case((SessionResult.overall_passed.is_(True), 1), else_=0)),
        func.sum(case((SessionResult.overall_passed.is_(False), 1), else_=0)),
    )
    if start:
        q = q.join(PartSession, SessionResult.session_id == PartSession.id).filter(
            PartSession.session_start >= start, PartSession.session_start < end
        )
    q = q.group_by(SessionResult.station_id)
    return [
        {
            "station_id": station_id,
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": (passed / total) if total else None,
        }
        for station_id, total, passed, failed in q.all()
    ]


@router.get("/defect-breakdown")
def defect_breakdown(
    time_filter: str = Query("all"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Per-defect-label frequency across all cameras -- no gcm equivalent
    (see module docstring). Excludes measurement-pipeline rows: both
    pipelines write their display string into CameraResult.defect_label
    (app/camera/station_registry.py's _run_pipeline(), kept as one field to
    avoid a wire-schema change), so a measurement's "⌀9.44mm oval 0.00mm"
    would otherwise show up here as if it were a defect type.

    Filters on measurement_passed IS NULL (a plain Boolean column, only
    ever set by the measurement path) rather than measurement_data IS NULL
    -- SQLAlchemy's JSON column stores Python None as a literal JSON
    `null` value, not SQL NULL, so `measurement_data IS NULL` silently
    matches nothing (found by testing this against real data: an empty
    result set with real "cat" defect rows sitting right there)."""
    start, end = _date_range(time_filter, start_date, end_date)
    q = db.query(CameraResult.defect_label, func.count(CameraResult.id)).filter(
        CameraResult.defect_label.isnot(None), CameraResult.measurement_passed.is_(None)
    )
    if start:
        q = (
            q.join(SessionResult, CameraResult.session_result_id == SessionResult.id)
            .join(PartSession, SessionResult.session_id == PartSession.id)
            .filter(PartSession.session_start >= start, PartSession.session_start < end)
        )
    q = q.group_by(CameraResult.defect_label).order_by(func.count(CameraResult.id).desc())
    return [{"defect_label": label, "count": count} for label, count in q.all()]


@router.get("/download-report")
def download_report(
    time_filter: str = Query("all"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """CSV export of session rows. gcm's report path is pandas -> CSV/PDF
    with a branded ReportLab layout (logo, header/footer); this uses the
    stdlib csv module instead for the CSV half (avoids adding pandas as a
    real dependency just for this -- it happens to be present in this dev
    environment but isn't in requirements.txt). PDF export is explicitly
    deferred, not silently dropped: it needs an actual Raph logo asset
    this session doesn't have, plus a real design pass so it looks
    "professional" rather than bolted on -- flagging as a follow-up.
    """
    start, end = _date_range(time_filter, start_date, end_date)
    q = db.query(PartSession)
    if start:
        q = q.filter(PartSession.session_start >= start, PartSession.session_start < end)
    rows = q.order_by(PartSession.session_start.desc()).limit(MAX_REPORT_ROWS).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["session_id", "part_code", "part_name", "session_start", "session_end", "total_fired", "total_passed", "total_failed"]
    )
    for r in rows:
        writer.writerow(
            [r.id, r.part_code, r.part_name, r.session_start, r.session_end, r.total_fired, r.total_passed, r.total_failed]
        )
    buf.seek(0)

    # Filename built only from a server-generated timestamp -- no request
    # input reaches it, so there's nothing to sanitize, but keeping the
    # pattern explicit per CLAUDE.md Section 11's export rule.
    filename = f"osm_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
