"""Device Settings page -- one row per config-driven actuators[] entry
(CLAUDE.md Section 6/Rule 5, never hardcoded). Reads/writes go through the
ModbusPLCClient set up by app.inspection_session.load_machine()."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/actuators", tags=["actuators"])


class ActuatorState(BaseModel):
    name: str
    state: bool


class ToggleRequest(BaseModel):
    state: bool


def _get_actuator(request: Request, name: str):
    resolved = getattr(request.app.state, "resolved_config", None)
    actuators = resolved.actuators if resolved else []
    for a in actuators:
        if a.name == name:
            return a
    raise HTTPException(status_code=404, detail=f"unknown actuator: {name}")


def _plc_client(request: Request):
    client = getattr(request.app.state, "plc_client", None)
    if client is None or not client.is_connected():
        raise HTTPException(status_code=503, detail="PLC not connected")
    return client


@router.get("", response_model=list[ActuatorState])
def list_actuators(request: Request):
    resolved = getattr(request.app.state, "resolved_config", None)
    actuators = resolved.actuators if resolved else []
    client = getattr(request.app.state, "plc_client", None)
    if client is None or not client.is_connected():
        return [ActuatorState(name=a.name, state=False) for a in actuators]
    return [ActuatorState(name=a.name, state=bool(client.read_register(a.reg))) for a in actuators]


@router.post("/{name}/toggle", response_model=ActuatorState)
def toggle_actuator(name: str, body: ToggleRequest, request: Request):
    actuator = _get_actuator(request, name)
    client = _plc_client(request)
    client.write_register(actuator.reg, 1 if body.state else 0)
    return ActuatorState(name=name, state=body.state)
