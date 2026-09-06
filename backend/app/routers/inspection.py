"""Non-realtime REST for the Inspection page -- live frames/results go over
ZMQ (CLAUDE.md Section 9), this only serves the initial camera list + totals
so the frontend isn't hardcoded to "cam1,cam2"."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/inspection", tags=["inspection"])

# Populated by app.main's startup handler once config is resolved.
_state = {"cameras": [], "totals": {"total_fired": 0, "total_passed": 0, "total_failed": 0}}


def set_cameras(camera_ids: list[str]) -> None:
    _state["cameras"] = camera_ids


def bump_totals(passed: bool) -> None:
    _state["totals"]["total_fired"] += 1
    if passed:
        _state["totals"]["total_passed"] += 1
    else:
        _state["totals"]["total_failed"] += 1


@router.get("/config")
def get_config():
    return {"cameras": [{"camera_id": c} for c in _state["cameras"]]}


@router.get("/session/current")
def get_current_session():
    return _state["totals"]


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
    return SessionStartResponse(status="started", part_code=resolved.part_code, cameras=_state["cameras"])


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
