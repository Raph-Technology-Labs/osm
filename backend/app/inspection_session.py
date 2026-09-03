"""Machine bootstrap (cameras + PLC + indexer tracker -- config-driven,
independent of any specific part) vs. session start (pipeline wiring +
dispatcher, per-part). Split so load_machine() is safe to call at boot if
machine_config.yaml exists, or lazily from start_session() if it didn't
exist yet at boot time -- see CLAUDE.md's "config-driven, not hardcoded"
rule (Section 7 Rule 5).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.camera.station_registry import get_station_registry, sim_frame_provider
from app.config.config_loader import (
    ResolvedMachineConfig,
    load_machine_config,
    resolve_config_for_part,
)
from app.indexer.dispatcher import StationDispatcher
from app.indexer.tracker import IndexerSlotTracker
from app.plc.modbus_client import ModbusPLCClient, PLCConnectionError
from app.utils import zeromq

log = logging.getLogger("inspection_session")


def load_machine(app: FastAPI) -> None:
    """Cameras (identities only) + PLC connection + IndexerSlotTracker + ZMQ
    bind. No pipeline wiring, no dispatcher -- those are per-part,
    session-start concerns. Safe to call once, either at boot (config
    already present) or lazily from start_session() (config only appeared
    once a part was picked)."""
    machine_part_code = load_machine_config()["machine"]["part_code"]
    resolved = resolve_config_for_part(machine_part_code)
    # actuators/error_registers are machine-level (not per-part), so this
    # makes them available to Device Settings/Health Check immediately at
    # boot -- start_session() overwrites this with the same fields once a
    # part is picked, since today's single-YAML setup only has one part.
    app.state.resolved_config = resolved

    zeromq.bind()

    registry = get_station_registry()
    registry.build_from_config(resolved)
    app.state.station_registry = registry

    station_pulse_offsets = {t.id: t.station_offset_pulses for t in resolved.triggers}
    app.state.indexer_tracker = IndexerSlotTracker(
        n_slots=resolved.indexer.n_slots,
        encoder_cpr=resolved.indexer.encoder_cpr,
        station_pulse_offsets=station_pulse_offsets,
    )

    plc_client = ModbusPLCClient(resolved.plc)
    try:
        plc_client.connect()
        plc_client.read_heartbeat()
        app.state.plc_client = plc_client
    except PLCConnectionError:
        log.warning("PLC connect failed during machine load -- continuing without it.", exc_info=True)
        app.state.plc_client = None

    app.state.machine_loaded = True


def start_session(app: FastAPI, part_code: str) -> ResolvedMachineConfig:
    """Resolve part config, wire the pipeline stand-in, (re)start the
    dispatcher. Lazily runs load_machine() first if boot found no config
    file yet."""
    from app.routers import inspection  # local import: avoids a circular
    # import (inspection.py would otherwise need this module at load time)

    if not getattr(app.state, "machine_loaded", False):
        load_machine(app)

    resolved = resolve_config_for_part(part_code)
    app.state.resolved_config = resolved

    registry = app.state.station_registry
    registry.build_from_config(resolved)

    for trig in resolved.inspection_triggers():
        defect_config = trig.pipeline.defect
        measurement_config = trig.pipeline.measurement
        draw_result = trig.pipeline.result.draw_result
        for camera_id, camera_config in trig.cameras.items():
            if not camera_config.sim.enabled:
                continue
            station = registry.get(camera_id)
            # Only pass a pipeline block through for cameras it actually
            # covers -- defect/measurement can each be scoped to a subset of
            # a trigger's cameras via allowed_cameras.
            camera_defect_config = (
                defect_config if defect_config and camera_id in defect_config.allowed_cameras else None
            )
            camera_measurement_config = (
                measurement_config
                if measurement_config and camera_id in measurement_config.allowed_cameras
                else None
            )
            station.set_frame_provider(
                sim_frame_provider(
                    camera_id,
                    image_path=camera_config.sim.image_path,
                    defect_config=camera_defect_config,
                    measurement_config=camera_measurement_config,
                    draw_result=draw_result,
                )
            )

            def make_on_result(cam_id=camera_id, trig_id=trig.id):
                def on_result(_cam_id, captured):
                    zeromq.publish_camera_frame(cam_id, captured.frame)
                    passed = not captured.is_defect
                    zeromq.publish_inspection_result(cam_id, trig_id, passed, captured.defect_label)
                    inspection.bump_totals(passed)
                return on_result

            station.on_result = make_on_result()

    inspection.set_cameras([s.camera_id for s in registry.all_stations()])

    old_dispatcher = getattr(app.state, "dispatcher", None)
    if old_dispatcher:
        old_dispatcher.stop()

    dispatcher = StationDispatcher(resolved, registry)
    app.state.dispatcher = dispatcher
    dispatcher.start()
    return resolved
