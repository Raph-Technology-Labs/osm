"""Non-realtime REST for the Inspection page -- live frames/results go over
ZMQ (CLAUDE.md Section 9), this only serves the initial camera list + totals
so the frontend isn't hardcoded to "cam1,cam2"."""

import csv
import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.db.db import get_db
from app.services import session_analysis, report_pdf

from app.auth.dependencies import require_role

log = logging.getLogger("inspection")

router = APIRouter(prefix="/inspection", tags=["inspection"], dependencies=[Depends(require_role("operator"))])

# Populated by app.main's startup handler once config is resolved.
_state = {"cameras": [], "totals": {"total_fired": 0, "total_passed": 0, "total_failed": 0}}


def set_cameras(cameras: list[dict]) -> None:
    """cameras: [{"camera_id": ..., "station_id": ...}, ...] -- station_id
    is what the Inspection page groups/paginates camera tiles by."""
    _state["cameras"] = cameras


def bump_totals(passed: bool) -> None:
    _state["totals"]["total_fired"] += 1
    if passed:
        _state["totals"]["total_passed"] += 1
    else:
        _state["totals"]["total_failed"] += 1


@router.get("/config")
def get_config(request: Request):
    resolved = getattr(request.app.state, "resolved_config", None)
    stations = []
    if resolved:
        # Same formula as app.indexer.tracker.IndexerSlotTracker's own
        # station_offsets -- real ring position in slot units, not an
        # evenly-spaced approximation.
        pulses_per_slot = resolved.indexer.pulses_per_slot
        stations = [
            {
                "station_id": s.id,
                "name": s.name,
                "slot_offset": round(s.station_offset_pulses / pulses_per_slot),
                "type": s.type,
                # Only reject stations carry enabled -- the frontend uses
                # its presence/value to render commissioning-mode styling.
                **({"enabled": s.enabled} if s.type == "reject" else {}),
            }
            for s in resolved.stations
        ]
    return {
        "cameras": _state["cameras"],
        "n_slots": resolved.indexer.n_slots if resolved else None,
        "stations": stations,
        # RpmControl's initial/reset value -- the slider must reflect
        # whatever this part's config actually has, not a hardcoded guess.
        "speed_setpoint_rpm": resolved.plc.speed_setpoint_rpm if resolved else None,
    }


@router.get("/session/current")
def get_current_session(request: Request):
    resolved = getattr(request.app.state, "resolved_config", None)
    # Placeholder proxy, not a real pulse-driven count: today's
    # StationDispatcher fires stations on a simulation timer and never
    # feeds IndexerSlotTracker.on_pulse_update() (dispatcher.py's own
    # docstring flags PLC-driven dispatch as not wired yet) -- so there's
    # no real encoder-pulse revolution count to read. n_slots parts firing
    # is what one revolution means physically, so total_fired // n_slots is
    # the closest honest estimate until real pulse tracking is wired.
    revolutions = _state["totals"]["total_fired"] // resolved.indexer.n_slots if resolved else 0
    return {**_state["totals"], "revolutions": revolutions}

def _resolve_session_id(request: Request, session_id: int | None) -> int:
    """An explicit session_id wins (for looking at a finished run); otherwise
    the one currently running. 404 rather than an empty rollup when neither
    exists -- "no session" and "a session with no results yet" are different
    answers, and the page should say which."""
    resolved = session_id if session_id is not None else getattr(
        request.app.state, "current_session_id", None
    )
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No session to analyse -- none is running, and result "
                "persistence may be off for this part (see "
                "inspection_session._create_part_session)"
            ),
        )
    return resolved


@router.get("/session/analysis")
def get_session_analysis(
    request: Request,
    session_id: int | None = Query(default=None),
    db: DbSession = Depends(get_db),
):
    """Per-defect-class, per-parameter and per-station rollups from the
    persisted rows -- survives a page reload, unlike the frontend's live
    tally. Lags the ring by however long results_writer's queue takes to
    drain, which is well under a second."""
    return session_analysis.build_analysis(db, _resolve_session_id(request, session_id))


@router.get("/session/events")
def get_session_events(
    request: Request,
    session_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    only_nok: bool = Query(default=False),
    db: DbSession = Depends(get_db),
):
    """Newest-first station fires for the event log. One row per camera per
    fire; rows sharing a ring_part_id belong to the same physical part."""
    return {
        "events": session_analysis.recent_events(
            db, _resolve_session_id(request, session_id), limit=limit, only_nok=only_nok
        )
    }


_REPORT_COLUMNS = [
    "session_id", "part_code", "part_name", "session_started_at",
    "fired_at", "ring_part_id", "station_id", "station_fire_no", "camera_id",
    "pipeline",
    # defect columns -- blank on a measurement row
    "defect_label", "defect_confidence", "detection_count", "is_defective",
    # measurement columns -- blank on a defect row
    "measurement_name", "measured", "nominal", "lower_limit", "upper_limit",
    "unit", "deviation", "ovality", "max_ovality", "in_tolerance",
    # verdicts
    "camera_passed", "station_passed", "rejected",
]


@router.get("/session/report")
def download_session_report(
    request: Request,
    session_id: int | None = Query(default=None),
    format: str = Query(default="csv", pattern="^(csv|pdf)$"),
    db: DbSession = Depends(get_db),
):
    """One session's results, as CSV or PDF.

    One route with ?format= rather than two paths, matching the dashboard's
    /download-report: both formats answer the same question from the same rows
    (session_analysis.report_rows), so they are one resource in two
    representations, not two resources.

    CSV splits defect and measurement into their own columns -- a blank cell
    says "this row is not that kind of result", which a spreadsheet can filter
    on. PDF composes them into one readable detail cell, because a printed page
    has no filter box.

    Deliberately finer-grained than the dashboard's own export (one row per
    SESSION, for "what did we run this week"): the question on the Inspection
    page is "what happened to the parts in this run".
    """
    resolved = _resolve_session_id(request, session_id)
    rows = session_analysis.report_rows(db, resolved)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # Server-generated timestamp only -- no request input reaches the filename
    # (CLAUDE.md Section 11's export rule).
    filename = f"osm_session_{resolved}_{stamp}.{format}"

    if format == "pdf":
        buf = io.BytesIO()
        report_pdf.build_session_pdf(rows, session_analysis.build_analysis(db, resolved), buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=_REPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        # DictWriter fills missing keys with "" -- exactly the blank-cell
        # behaviour the column split depends on.
        writer.writerow(row)
    return StreamingResponse(
        iter([text.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

class SessionStartRequest(BaseModel):
    part_code: str


class SessionStartResponse(BaseModel):
    status: str
    part_code: str
    cameras: list[str]


@router.post("/session/start", response_model=SessionStartResponse)
def start_session_endpoint(body: SessionStartRequest, request: Request):
    from app.inspection_session import start_session  # local import: avoids
    # a circular import (inspection_session.py imports this module for
    # set_cameras/bump_totals)
    try:
        resolved = start_session(request.app, body.part_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _state["totals"] = {"total_fired": 0, "total_passed": 0, "total_failed": 0}
    return SessionStartResponse(
        status="started",
        part_code=resolved.part_code,
        cameras=[c["camera_id"] for c in _state["cameras"]],
    )


class SessionStopResponse(BaseModel):
    status: str
    session_id: int | None
    totals: dict


@router.post("/session/stop", response_model=SessionStopResponse)
def stop_session_endpoint(request: Request):
    """Stops the dispatcher and finalizes the active PartSession row (if
    result persistence is on -- see inspection_session._create_part_session
    for why it can be None). Does NOT tear down cameras/PLC -- those stay up
    for Health Check/Device Settings per CLAUDE.md Section 9, only the
    per-part pipeline/dispatcher stops."""
    from app.db.db import SessionLocal
    from app.models.models import PartSession

    app = request.app
    dispatcher = getattr(app.state, "dispatcher", None)
    if dispatcher:
        dispatcher.stop()

    session_id = getattr(app.state, "current_session_id", None)
    if session_id is not None:
        from app.services.results_writer import get_results_writer

        get_results_writer().stop()  # flush anything still queued before finalizing session_end
        db = SessionLocal()
        try:
            db.query(PartSession).filter(PartSession.id == session_id).update(
                {PartSession.session_end: datetime.now(timezone.utc)}
            )
            db.commit()
        finally:
            db.close()
        app.state.current_session_id = None

    return SessionStopResponse(status="stopped", session_id=session_id, totals=_state["totals"])


class MotorCommandResponse(BaseModel):
    status: str
    running: bool
    plc_updated: bool


def _write_stop_cmd(request: Request, run: bool) -> bool:
    """Writes stop_cmd (machine_config.yaml plc.registers.stop_cmd) as a
    combined run/stop command: write 1 = run, write 0 = halt -- per
    explicit operator instruction (2026-09-07), NOT the instrumentation
    sheet's own label for this register ("halt execution", i.e. a pure
    one-directional halt bit). Flag with the instrumentation team before
    this reaches real hardware -- also note stop_cmd has no paired _ACK
    register in the sheet (already called out in machine_config.yaml),
    a real gap against CLAUDE.md Rule 4 that predates this change."""
    resolved = getattr(request.app.state, "resolved_config", None)
    client = getattr(request.app.state, "plc_client", None)
    if resolved is None or client is None or not client.is_connected():
        return False
    from app.plc.modbus_client import PLCConnectionError

    try:
        client.write_register(resolved.plc.registers.stop_cmd, 1 if run else 0)
        return True
    except PLCConnectionError:
        log.warning("motor: PLC stop_cmd write failed", exc_info=True)
        return False


def _write_speed_setpoint(request: Request, rpm: float) -> bool:
    """Writes the configured speed_setpoint_rpm as a raw register value (no
    *10 scaling -- per 2026-09-16 live hardware confirmation, see /speed's
    docstring). Called from start_motor(), before stop_cmd, so Start
    actually applies the part's configured speed instead of leaving
    whatever value was last left in the register (re-adding the
    session/start speed write CLAUDE.md's history notes was previously
    reverted -- see that section if this needs re-litigating again)."""
    resolved = getattr(request.app.state, "resolved_config", None)
    client = getattr(request.app.state, "plc_client", None)
    if resolved is None or client is None or not client.is_connected():
        return False
    from app.plc.modbus_client import PLCConnectionError

    try:
        client.write_register(resolved.plc.registers.speed_setpoint, round(rpm))
        return True
    except PLCConnectionError:
        log.warning("motor: PLC speed_setpoint write failed", exc_info=True)
        return False


@router.post("/motor/start", response_model=MotorCommandResponse)
def start_motor(request: Request):
    """Starts the ring turning -- separate from session start, which only
    wires cameras/pipeline/dispatcher without running them (see
    inspection_session.start_session). Requires an active session."""
    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is None:
        raise HTTPException(status_code=400, detail="No active session -- start a session first")
    dispatcher.start()
    resolved = getattr(request.app.state, "resolved_config", None)
    if resolved is not None:
        # Write speed before stop_cmd's 0->1 edge -- the PLC appears to
        # latch speed_setpoint at that transition rather than reading it
        # continuously (see /speed's docstring history).
        _write_speed_setpoint(request, resolved.plc.speed_setpoint_rpm)
    plc_updated = _write_stop_cmd(request, run=True)
    return MotorCommandResponse(status="ok", running=True, plc_updated=plc_updated)


@router.post("/motor/stop", response_model=MotorCommandResponse)
def stop_motor(request: Request):
    """Stops the ring without ending the session/DB persistence -- session
    stop (POST /inspection/session/stop) already calls dispatcher.stop()
    too, so this is for pausing mid-session."""
    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is None:
        raise HTTPException(status_code=400, detail="No active session")
    dispatcher.stop()
    plc_updated = _write_stop_cmd(request, run=False)
    return MotorCommandResponse(status="ok", running=False, plc_updated=plc_updated)


class SpeedSetpointRequest(BaseModel):
    rpm: float


@router.post("/speed")
def set_speed(body: SpeedSetpointRequest, request: Request):
    """Sets motor speed two ways, independently:
    1. Real PLC register write, raw RPM value (no scaling) -- only if a PLC
       is actually connected. Switched back to raw (2026-09-16) per live
       hardware confirmation: writing 15 directly to the register ran the
       motor fast, while this endpoint's prior rpm*10 write (150 for
       rpm=15) ran it slow -- the opposite of what's wanted. Note this
       conflicts with an earlier hardware observation (2026-09-15) that a
       raw write of 15 stalled the motor on start; the two haven't been
       reconciled, so revisit if raw values misbehave again.
    2. Scales StationDispatcher's simulation-timer fire interval, relative
       to the configured speed_setpoint_rpm baseline -- so changing speed
       has a visible effect (stations fire faster/slower) even with no
       PLC connected at all, which is the common case in this sim-only
       demo build. Previously this endpoint only did (1) and 503'd
       whenever there was no PLC, meaning the control did nothing at all
       in the far more common no-hardware case.

    Placed on the Inspection page (not gated to administrator like the
    Device Settings actuator toggle) since adjusting motor speed live
    during a run is an operator task on the floor, not an admin-only
    device setting -- judgment call, flag if that's wrong."""
    resolved = getattr(request.app.state, "resolved_config", None)
    if resolved is None:
        raise HTTPException(status_code=400, detail="No machine loaded")

    sim_updated = False
    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is not None:
        baseline_rpm = resolved.plc.speed_setpoint_rpm
        scale = (body.rpm / baseline_rpm) if baseline_rpm else 1.0
        dispatcher.set_speed_scale(scale)
        sim_updated = True

    plc_updated = False
    client = getattr(request.app.state, "plc_client", None)
    if client is not None and client.is_connected():
        from app.plc.modbus_client import PLCConnectionError

        speed_value = round(body.rpm)
        try:
            client.write_register(resolved.plc.registers.speed_setpoint, speed_value)
            plc_updated = True
        except PLCConnectionError:
            log.warning("speed: PLC register write failed, sim scaling still applied", exc_info=True)

    if not sim_updated and not plc_updated:
        raise HTTPException(status_code=503, detail="No active session and no PLC connected -- nothing to change")

    return {"status": "ok", "rpm": body.rpm, "plc_updated": plc_updated, "sim_updated": sim_updated}
