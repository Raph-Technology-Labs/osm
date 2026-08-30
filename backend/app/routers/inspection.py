"""Non-realtime REST for the Inspection page -- live frames/results go over
ZMQ (CLAUDE.md Section 9), this only serves the initial camera list + totals
so the frontend isn't hardcoded to "cam1,cam2"."""

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
    return SessionStartResponse(status="started", part_code=resolved.part_code, cameras=_state["cameras"])
