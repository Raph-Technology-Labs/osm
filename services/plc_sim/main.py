# services/plc_sim/main.py
# TCP controller simulator for OSM (stand-in transport: Modbus TCP via
# pymodbus -- see config.py's TRANSPORT NOTE. Swap only this file's
# server/register wiring once Integra's real protocol spec is available).
#
# Simulates: the disc continuously rotating (PULSE_COUNT free-running,
# wraps at encoder_cpr), parts arriving at each slot boundary (pushed into
# the entry-queue ring buffer), a plain heartbeat, and reject CMD -> ACK
# handshakes (with a stall toggle to test watchdog timeout escalation).
#
# Inspect UI: http://localhost:9100/docs

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
# NOTE: pinned to pymodbus==3.7.4 deliberately (see requirements.txt) --
# pymodbus 3.15's datastore API was overhauled around a unified simulator
# model (ModbusDeviceContext, devices= kwarg, ModbusSequentialDataBlock
# address bounds tightened) and isn't a drop-in match for this file's
# gcm-derived pattern. Bump only with a deliberate rewrite of this file.
from pymodbus.server import StartAsyncTcpServer

from config import DATASTORE_SIZE, load_sim_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("plc_sim")

cfg = load_sim_config()
context: ModbusServerContext = None

MODBUS_PORT = int(os.getenv("MODBUS_PORT", cfg.modbus_port))
INSPECT_PORT = int(os.getenv("INSPECT_PORT", "9100"))
PULSES_PER_SEC = int(os.getenv("PLC_SIM_PULSES_PER_SEC", "900"))  # ~4s/revolution at default cfg

_stalled_stations: set[str] = set()      # reject stations currently NOT auto-ACKing
_last_cmd_value: dict[str, int] = {}      # per-station, last-seen cmd_reg value


def make_context() -> ModbusServerContext:
    holding = [0] * DATASTORE_SIZE
    store = ModbusSlaveContext(
        di=ModbusSequentialDataBlock(0, [0] * 8),
        co=ModbusSequentialDataBlock(0, [0] * 8),
        hr=ModbusSequentialDataBlock(0, holding),
        ir=ModbusSequentialDataBlock(0, [0] * 8),
    )
    return ModbusServerContext(slaves=store, single=True)


def _read(addr: int) -> int:
    return context[0x00].getValues(3, addr, count=1)[0]


def _write(addr: int, value: int) -> None:
    context[0x00].setValues(3, addr, [value])


# ---------------------------------------------------------------------------
# Background simulation tasks
# ---------------------------------------------------------------------------

async def pulse_task():
    """Free-running PULSE_COUNT, wraps at encoder_cpr. On every slot-boundary
    crossing, pushes a part-entry capture into the entry-queue ring buffer --
    this is what makes "the disc is rotating and parts are arriving" real."""
    pulses_per_slot = cfg.encoder_cpr // cfg.n_slots
    pulse = 0
    last_slot = -1
    tick_interval = 1.0 / PULSES_PER_SEC
    while True:
        await asyncio.sleep(tick_interval)
        pulse = (pulse + 1) % cfg.encoder_cpr
        _write(cfg.pulse_count_reg, pulse)

        current_slot = pulse // pulses_per_slot
        if current_slot != last_slot:
            last_slot = current_slot
            _push_entry_queue(pulse)


def _push_entry_queue(captured_pulse: int) -> None:
    write_idx = _read(cfg.entry_queue_write_idx_reg)
    slot = write_idx % cfg.entry_queue_size
    _write(cfg.entry_queue_slots_start_reg + slot, captured_pulse)
    _write(cfg.entry_queue_write_idx_reg, write_idx + 1)
    log.info("Entry queue: pushed pulse=%d at write_idx=%d (ring slot %d)", captured_pulse, write_idx, slot)


async def heartbeat_task():
    """Plain periodic alive signal -- not tied to slot math."""
    beat = 0
    while True:
        await asyncio.sleep(0.5)
        beat = (beat + 1) % 65536
        _write(cfg.heartbeat_plc_reg, beat)


async def reject_ack_task():
    """Watches each reject station's CMD register; when the PC writes a new
    value, auto-ACKs after a short delay -- unless that station is stalled
    (see /simulate/stall), to let the watchdog's missed-ACK escalation be
    tested on demand."""
    for rs in cfg.reject_stations:
        _last_cmd_value[rs.id] = _read(rs.cmd_reg)

    while True:
        await asyncio.sleep(0.02)
        for rs in cfg.reject_stations:
            current = _read(rs.cmd_reg)
            if current != _last_cmd_value[rs.id]:
                _last_cmd_value[rs.id] = current
                if rs.id in _stalled_stations:
                    log.warning("Reject station %s is STALLED -- withholding ACK for cmd=%d", rs.id, current)
                    continue
                asyncio.create_task(_delayed_ack(rs, current))


async def _delayed_ack(rs, cmd_value: int) -> None:
    await asyncio.sleep(rs.ack_timeout_ms / 1000 / 3)  # comfortably inside the real timeout
    _write(rs.ack_reg, cmd_value)
    log.info("Reject station %s: ACKed cmd=%d", rs.id, cmd_value)


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global context
    context = make_context()
    log.info("Controller simulator (Modbus TCP stand-in) on 0.0.0.0:%d", MODBUS_PORT)
    log.info("Inspect UI on http://0.0.0.0:%d/docs", INSPECT_PORT)
    server_task = asyncio.create_task(StartAsyncTcpServer(context=context, address=("0.0.0.0", MODBUS_PORT)))
    sim_tasks = [
        asyncio.create_task(pulse_task()),
        asyncio.create_task(heartbeat_task()),
        asyncio.create_task(reject_ack_task()),
    ]
    yield
    server_task.cancel()
    for t in sim_tasks:
        t.cancel()


app = FastAPI(
    title="OSM Controller Simulator",
    description="Modbus-TCP stand-in for the Integra in-house controller (dev/demo only)",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/status", summary="Rotation + entry-queue snapshot")
def status():
    return {
        "pulse_count": _read(cfg.pulse_count_reg),
        "heartbeat_plc": _read(cfg.heartbeat_plc_reg),
        "entry_queue_write_idx": _read(cfg.entry_queue_write_idx_reg),
        "n_slots": cfg.n_slots,
        "encoder_cpr": cfg.encoder_cpr,
        "reject_stations": [
            {
                "id": rs.id,
                "cmd": _read(rs.cmd_reg),
                "ack": _read(rs.ack_reg),
                "stalled": rs.id in _stalled_stations,
            }
            for rs in cfg.reject_stations
        ],
    }


@app.get("/registers/{address}", summary="Single register by address")
def get_register(address: int):
    return {"address": address, "value": _read(address)}


@app.post("/registers/{address}", summary="Force write a holding register")
def write_register(address: int, value: int):
    _write(address, value)
    log.info("Force write HR[%d] = %d", address, value)
    return {"address": address, "value": value}


@app.post("/simulate/stall/{station_id}/{on}", summary="Toggle withholding reject ACKs for a station")
def simulate_stall(station_id: str, on: bool):
    known = {rs.id for rs in cfg.reject_stations}
    if station_id not in known:
        return {"error": f"unknown reject station {station_id!r} (known: {sorted(known)})"}
    if on:
        _stalled_stations.add(station_id)
    else:
        _stalled_stations.discard(station_id)
    log.info("Reject station %s stall = %s", station_id, on)
    return {"station_id": station_id, "stalled": on}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=INSPECT_PORT, log_level="info")
