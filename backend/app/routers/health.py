"""Health Check page -- camera connectivity/initialization + PLC connection,
heartbeat, and error-register status. All driven by config (CLAUDE.md
Section 6), nothing hardcoded."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.camera.station_registry import get_station_registry

router = APIRouter(prefix="/health", tags=["health"])


class CameraHealth(BaseModel):
    camera_id: str
    station_id: str
    initialized: bool
    connected: bool
    last_capture_ts: float | None


class ErrorRegisterStatus(BaseModel):
    name: str
    reg: int
    value: int


class PLCHealth(BaseModel):
    connected: bool
    heartbeat: int | None
    errors: list[ErrorRegisterStatus]


@router.get("/cameras", response_model=list[CameraHealth])
def get_camera_health():
    registry = get_station_registry()
    return [
        CameraHealth(
            camera_id=s.camera_id,
            station_id=s.station_id,
            initialized=s.is_initialized(),
            connected=s.is_connected(),
            last_capture_ts=s.last_capture_ts,
        )
        for s in registry.all_stations()
    ]


@router.get("/plc", response_model=PLCHealth)
def get_plc_health(request: Request):
    client = getattr(request.app.state, "plc_client", None)
    resolved = getattr(request.app.state, "resolved_config", None)
    error_registers = resolved.plc.error_registers if resolved else []

    if client is None or not client.is_connected():
        return PLCHealth(
            connected=False,
            heartbeat=None,
            errors=[ErrorRegisterStatus(name=e.name, reg=e.reg, value=-1) for e in error_registers],
        )

    heartbeat = client.read_heartbeat()
    errors = [ErrorRegisterStatus(name=e.name, reg=e.reg, value=client.read_register(e.reg)) for e in error_registers]
    return PLCHealth(connected=True, heartbeat=heartbeat, errors=errors)
