"""Non-realtime REST for the Inspection page -- live frames/results go over
ZMQ (CLAUDE.md Section 9), this only serves the initial camera list + totals
so the frontend isn't hardcoded to "cam1,cam2"."""

from fastapi import APIRouter

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
