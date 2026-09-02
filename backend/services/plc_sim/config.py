"""Loads backend/app/config/machine_config.yaml and exposes the pieces
plc_sim needs. Deliberately reuses the SAME config file as the backend
(not a separate sim-only file) so the simulator can never drift out of sync
with what the backend expects.

TRANSPORT NOTE: the real controller is an in-house unit ("Integra"), not a
standard PLC -- comms are plain TCP but the exact wire protocol/framing is
not yet known (see plan.txt open items). This simulator speaks Modbus TCP
as an explicitly-labeled stand-in so the rest of the system (tracker,
dispatcher, register map, CMD/ACK handling) can be built and tested now;
swap only main.py's server/registers wiring once the real protocol spec is
available -- nothing above the transport boundary should need to change.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml

CONFIG_PATH = os.getenv(
    "OSM_CONFIG",
    os.path.join(os.path.dirname(__file__), "../../backend/app/config/machine_config.yaml"),
)

# Highest register address used (reject cmd/ack regs) plus generous headroom.
DATASTORE_SIZE = 2000


@dataclass
class RejectStation:
    id: str
    station_offset_pulses: int
    cmd_reg: int
    ack_reg: int
    ack_timeout_ms: int


@dataclass
class ErrorRegister:
    name: str
    reg: int


@dataclass
class Actuator:
    name: str
    reg: int
    type: str


@dataclass
class SimConfig:
    n_slots: int
    encoder_cpr: int
    modbus_host: str
    modbus_port: int
    pulse_count_reg: int
    heartbeat_plc_reg: int
    entry_queue_write_idx_reg: int
    entry_queue_slots_start_reg: int
    entry_queue_size: int
    reject_stations: List[RejectStation]
    error_registers: List[ErrorRegister]
    actuators: List[Actuator]


def load_sim_config(config_path: str = CONFIG_PATH) -> SimConfig:
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    indexer = raw["indexer"]
    plc = raw["plc"]
    regs = plc["registers"]

    return SimConfig(
        n_slots=indexer["n_slots"],
        encoder_cpr=indexer["encoder_cpr"],
        modbus_host=plc["sim"]["host"],
        modbus_port=plc["sim"]["port"],
        pulse_count_reg=regs["pulse_count"],
        heartbeat_plc_reg=regs["heartbeat_plc"],
        entry_queue_write_idx_reg=regs["entry_queue_write_idx"],
        entry_queue_slots_start_reg=regs["entry_queue_slots_start"],
        entry_queue_size=regs["entry_queue_size"],
        reject_stations=[
            RejectStation(
                id=rs["id"],
                station_offset_pulses=rs["station_offset_pulses"],
                cmd_reg=rs["cmd_reg"],
                ack_reg=rs["ack_reg"],
                ack_timeout_ms=rs.get("ack_timeout_ms", 500),
            )
            for rs in plc["reject_stations"]
        ],
        error_registers=[ErrorRegister(name=e["name"], reg=e["reg"]) for e in plc.get("error_registers", [])],
        actuators=[Actuator(name=a["name"], reg=a["reg"], type=a["type"]) for a in raw.get("actuators", [])],
    )
