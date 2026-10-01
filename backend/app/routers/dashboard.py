"""Dashboard aggregation + CSV/PDF report export.

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

The PDF's page furniture (rule, page number, "Powered by" mark) comes from
the inspection report module rather than a second copy here: one logo path,
one footer, so the two reports cannot drift apart.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table as RLTable, TableStyle

from app.auth.dependencies import require_role
from app.db.db import get_db
from app.models.models import CameraResult, PartSession, SessionResult
from functools import lru_cache
from pathlib import Path
from reportlab.lib.utils import ImageReader
# from app.reports.session_pdf import FOOTER_HEIGHT, draw_report_footer  # ← adjust to the real module path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_role("operator"))])

# CLAUDE.md Section 11: "CSV/PDF export: ... cap row count server-side even
# if UI requests unbounded."
MAX_REPORT_ROWS = 10_000

# Reports are read on the factory floor, so timestamps are shown in local
# time, not the UTC the DB stores. Override with OSM_REPORT_TZ if this is
# ever deployed outside India.
REPORT_TZ = ZoneInfo(os.getenv("OSM_REPORT_TZ", "Asia/Kolkata"))


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

    # Per-station pass/fail for just this page's sessions -- one grouped query,
    # not one per row.
    per_station: dict = {}
    session_ids = [r.id for r in rows]
    if session_ids:
        breakdown = (
            db.query(
                SessionResult.session_id,
                SessionResult.station_id,
                func.count(SessionResult.id),
                func.sum(case((SessionResult.overall_passed.is_(True), 1), else_=0)),
                func.sum(case((SessionResult.overall_passed.is_(False), 1), else_=0)),
            )
            .filter(SessionResult.session_id.in_(session_ids))
            .group_by(SessionResult.session_id, SessionResult.station_id)
            .order_by(SessionResult.session_id, SessionResult.station_id)
            .all()
        )
        for sid, station_id, total_fires, passed, failed in breakdown:
            per_station.setdefault(sid, []).append({
                "station_id": station_id,
                "total": total_fires,
                "passed": passed or 0,
                "failed": failed or 0,
            })

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
                "stations": per_station.get(r.id, []),
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


# ─────────────────────────────────────────────────────────────────
# Report export
# ─────────────────────────────────────────────────────────────────
HEADERS = ["Sr. No.", "Session", "Part code", "Part name", "Start", "End", "Fired", "Passed", "Failed"]


def _report_rows(db, time_filter, start_date, end_date):
    start, end = _date_range(time_filter, start_date, end_date)
    q = db.query(PartSession)
    if start:
        q = q.filter(PartSession.session_start >= start, PartSession.session_start < end)
    return q.order_by(PartSession.session_start.desc()).limit(MAX_REPORT_ROWS).all()


def _fmt(dt):
    """UTC in the DB -> local 12-hour time in the report. Shared by both
    formats so CSV and PDF can never disagree about a timestamp."""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(REPORT_TZ).strftime("%Y-%m-%d %I:%M %p")


FOOTER_HEIGHT = 16 * mm

# app/ is the anchor, found by name so this survives the module moving.
_APP_DIR = next((p for p in Path(__file__).resolve().parents if p.name == "app"),
                Path(__file__).resolve().parent)
LOGO_PATH = Path(os.getenv("OSM_REPORT_LOGO") or _APP_DIR / "assets" / "raph-logo.png")


@lru_cache(maxsize=1)
def _logo():
    """A missing logo degrades to a text footer -- it never fails the report."""
    if LOGO_PATH.is_file():
        return ImageReader(str(LOGO_PATH))
    logger.warning("Report logo not found at %s", LOGO_PATH)
    return None


def _page_footer(canvas, doc):
    """Page number bottom left, 'Powered by <logo>' bottom right, every page."""
    canvas.saveState()
    width = doc.pagesize[0]

    canvas.setStrokeColor(colors.HexColor("#d7dce3"))
    canvas.setLineWidth(0.5)
    canvas.line(15 * mm, FOOTER_HEIGHT, width - 15 * mm, FOOTER_HEIGHT)

    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#7b8794"))
    canvas.drawString(15 * mm, FOOTER_HEIGHT - 9, f"Page {canvas.getPageNumber()}")

    right = width - 15 * mm
    logo = _logo()
    if logo:
        iw, ih = logo.getSize()
        h = 9 * mm
        w = h * (iw / ih)
        canvas.drawImage(logo, right - w, FOOTER_HEIGHT - h - 1 * mm,
                         width=w, height=h, mask="auto", preserveAspectRatio=True)
        right -= w + 3 * mm
        canvas.drawRightString(right, FOOTER_HEIGHT - 9, "Powered by")
    else:
        canvas.drawRightString(right, FOOTER_HEIGHT - 9, "Powered by Raph Technology Labs")
    canvas.restoreState()

@router.get("/download-report")
def download_report(
    time_filter: str = Query("all"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    db: Session = Depends(get_db),
):
    """Session-level export in CSV or PDF.

    The pattern on `format` is deliberate: an unconstrained param would be
    silently ignored on a typo and hand the caller the wrong format under
    the right filename.
    """
    rows = _report_rows(db, time_filter, start_date, end_date)
    stamp = datetime.now(REPORT_TZ).strftime("%Y%m%d_%H%M%S")

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(HEADERS)
        for i, r in enumerate(rows, 1):
            writer.writerow([i, r.id, r.part_code, r.part_name, _fmt(r.session_start),
                             _fmt(r.session_end), r.total_fired, r.total_passed, r.total_failed])
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="osm_report_{stamp}.csv"'},
        )

    # ---- PDF ----
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
        bottomMargin=FOOTER_HEIGHT + 4 * mm,  # clears the shared footer band
        title="OSM Session Report",
    )
    styles = getSampleStyleSheet()
    period = f"{start_date} to {end_date}" if time_filter == "range" else time_filter
    story = [
        Paragraph("OSM Session Report", styles["Title"]),
        Paragraph(
            f"Period: {period} &nbsp;|&nbsp; Sessions: {len(rows)} &nbsp;|&nbsp; "
            f"Generated: {datetime.now(REPORT_TZ).strftime('%Y-%m-%d %I:%M %p %Z')}",
            styles["Normal"],
        ),
        Spacer(1, 6 * mm),
    ]

    data = [HEADERS] + [
        [i, r.id, r.part_code, r.part_name, _fmt(r.session_start), _fmt(r.session_end),
         r.total_fired, r.total_passed, r.total_failed]
        for i, r in enumerate(rows, 1)
    ]
    table = RLTable(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1976d2")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (6, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table if rows else Paragraph("No sessions in this period.", styles["Normal"]))

    try:
        doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    except Exception as e:
        logger.exception("PDF report build failed")
        raise HTTPException(status_code=500, detail=f"PDF build failed: {type(e).__name__}: {e}")

    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="osm_report_{stamp}.pdf"'},
    )


