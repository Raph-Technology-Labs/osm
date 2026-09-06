"""Non-realtime REST for the Inspection page -- live frames/results go over
ZMQ (CLAUDE.md Section 9), this only serves the initial camera list + totals
so the frontend isn't hardcoded to "cam1,cam2"."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth.dependencies import require_role

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
            {"station_id": s.id, "name": s.name, "slot_offset": round(s.station_offset_pulses / pulses_per_slot)}
            for s in resolved.stations
        ]
    return {
        "cameras": _state["cameras"],
        "n_slots": resolved.indexer.n_slots if resolved else None,
        "stations": stations,
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


class SpeedSetpointRequest(BaseModel):
    rpm: float


@router.post("/speed")
def set_speed(body: SpeedSetpointRequest, request: Request):
    """Writes the PLC's speed_setpoint register. Placed on the Inspection
    page (not gated to administrator like the Device Settings actuator
    toggle) since adjusting motor speed live during a run is an operator
    task on the floor, not an admin-only device setting -- judgment call,
    flag if that's wrong.

    rpm*10 -> 0-1000 scale matches app/plc/poller.py's write_speed_setpoint()
    -- same UNCONFIRMED-against-the-instrumentation-sheet caveat as that
    function, not inventing a second, different conversion here."""
    client = getattr(request.app.state, "plc_client", None)
    if client is None or not client.is_connected():
        raise HTTPException(status_code=503, detail="PLC not connected")
    resolved = getattr(request.app.state, "resolved_config", None)
    if resolved is None:
        raise HTTPException(status_code=400, detail="No machine loaded")

    rpm_x10 = round(body.rpm * 10)
    client.write_register(resolved.plc.registers.speed_setpoint, rpm_x10)
    return {"status": "ok", "rpm": body.rpm}
