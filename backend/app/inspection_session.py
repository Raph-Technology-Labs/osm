"""Machine bootstrap (cameras + PLC + indexer tracker -- config-driven,
independent of any specific part) vs. session start (pipeline wiring +
dispatcher, per-part). Split so load_machine() is safe to call at boot if
machine_config.yaml exists, or lazily from start_session() if it didn't
exist yet at boot time -- see CLAUDE.md's "config-driven, not hardcoded"
rule (Section 7 Rule 5).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI

from app.camera.camera_driver import CameraConnectionError
from app.camera.station_registry import get_station_registry, real_frame_provider, sim_frame_provider
from app.config.config_loader import (
    ResolvedMachineConfig,
    load_machine_config,
    resolve_config_for_part,
)
from app.db.db import SessionLocal
from app.indexer.dispatcher import StationDispatcher
from app.indexer.tracker import IndexerSlotTracker
from app.models.models import Part, PartSession
from app.plc.modbus_client import ModbusPLCClient, PLCConnectionError
from app.plc.watchdog import PLCWatchdog
from app.services.results_writer import (
    CameraResultItem,
    ResultItem,
    get_results_writer,
    next_fire_no,
    next_ring_part_id,
)
from app.utils import zeromq

log = logging.getLogger("inspection_session")


def load_machine(app: FastAPI) -> None:
    """Cameras (identities only) + PLC connection + IndexerSlotTracker + ZMQ
    bind. No pipeline wiring, no dispatcher -- those are per-part,
    session-start concerns. Safe to call once, either at boot (config
    already present) or lazily from start_session() (config only appeared
    once a part was picked)."""
    # Read the part code from the raw machine YAML.
    machine_part_code = load_machine_config()["machine"]["part_code"]
    # Validate and convert the raw YAML into a typed runtime configuration.
    resolved = resolve_config_for_part(machine_part_code)
    # actuators/error_registers are machine-level (not per-part), so this
    # makes them available to Device Settings/Health Check immediately at
    # boot -- start_session() overwrites this with the same fields once a
    # part is picked, since today's single-YAML setup only has one part.
    # Make the resolved configuration available to the rest of the app.
    app.state.resolved_config = resolved

    # Bind the ZeroMQ publisher used for camera and inspection messages.
    zeromq.bind()

    # Create camera station objects from the resolved station configuration.
    registry = get_station_registry()
    registry.build_from_config(resolved)
    app.state.station_registry = registry

    # Convert each station's configured pulse distance into a lookup dictionary.
    station_pulse_offsets = {s.id: s.station_offset_pulses for s in resolved.stations}
    # Create the ring tracker using the derived slot count and encoder resolution.
    app.state.indexer_tracker = IndexerSlotTracker(
        n_slots=resolved.indexer.n_slots,
        encoder_cpr=resolved.indexer.encoder_cpr,
        station_pulse_offsets=station_pulse_offsets,
        inspection_station_ids=[s.id for s in resolved.inspection_stations()],
    )
    _seed_sim_if_enabled(app, resolved)

    # Create the PLC client from the PLC settings in the resolved configuration.
    plc_client = ModbusPLCClient(resolved.plc)
    app.state.plc_watchdog = None
    try:
        # Connect to the PLC and verify communication with a heartbeat read.
        plc_client.connect()
        plc_client.read_heartbeat()
        app.state.plc_client = plc_client

        watchdog = PLCWatchdog(plc_client, timeout_ms=resolved.plc.watchdog_timeout_ms)
        watchdog.start()
        app.state.plc_watchdog = watchdog
    except PLCConnectionError:
        # Keep the app running without PLC access so the health state can report the failure.
        log.warning("PLC connect failed during machine load -- continuing without it.", exc_info=True)
        app.state.plc_client = None

    # Mark machine setup as complete for later session-start checks.
    app.state.machine_loaded = True


def _seed_sim_if_enabled(app: FastAPI, resolved: ResolvedMachineConfig) -> None:
    """Randomly seeds IndexerSlotTracker's BLANK (permanently-unfed) slots
    per machine_config.yaml's plc.sim: block. No forced OK/NOK -- every
    other slot runs real defect/measurement inference against its sim
    image, so OK/NOK is decided by the actual pipeline, not this harness.
    Called from both load_machine() (boot) and start_session() (idempotent
    re-seed, since sim config might not have been known/enabled yet at boot
    time -- the tracker itself is a long-lived, boot-time object, not
    recreated per session)."""
    if not resolved.plc.sim.enabled:
        return
    counts = resolved.plc.sim.resolve(resolved.indexer.n_slots)
    app.state.indexer_tracker.seed_sim(blank=counts.blank)
    log.info(
        "Sim harness enabled: %d BLANK slots randomly placed (of %d) -- every "
        "other slot runs real inference, no forced verdict",
        counts.blank, resolved.indexer.n_slots,
    )


def _create_part_session(part_code: str) -> Optional[int]:
    """Creates the PartSession DB row for a new session -- looks up the
    seeded Part (app/seed.py) + its active_config to satisfy the FKs.
    Returns None (not an error) if the part_code isn't seeded yet, since
    machine_config.yaml's part_code is the source of truth for what
    actually runs, not the DB -- a session should still run and inspect,
    just without result persistence, rather than fail to start entirely."""
    db = SessionLocal()
    try:
        part = db.query(Part).filter(Part.part_code == part_code).first()
        if part is None or part.active_config_id is None:
            log.warning(
                "%s: no seeded Part/active PartConfig found -- session will run "
                "without DB result persistence",
                part_code,
            )
            return None
        session = PartSession(
            part_id=part.part_id,
            part_config_id=part.active_config_id,
            part_code=part.part_code,
            part_name=part.part_name,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session.id
    finally:
        db.close()


def start_session(app: FastAPI, part_code: str) -> ResolvedMachineConfig:
    """Resolve part config, wire the pipeline stand-in, (re)start the
    dispatcher. Lazily runs load_machine() first if boot found no config
    file yet."""
    from app.routers import inspection  # local import: avoids a circular
    # import (inspection.py would otherwise need this module at load time)

    # Stop and drain the PREVIOUS session's dispatcher before anything else
    # here, in particular before _seed_sim_if_enabled() below (spec13 #6,
    # found missing in spec12's code review): seed_sim() rewrites which
    # slots are BLANK on the shared, long-lived IndexerSlotTracker, which is
    # only safe once the old dispatcher is confirmed to have fired its last
    # tick -- otherwise a still-ticking old dispatcher can dispatch stations
    # against slots seed_sim() just reseeded out from under it. stop() now
    # blocks until drained (StationDispatcher.stop()), so this is a real
    # guarantee, not just "no new timer scheduled yet".
    old_dispatcher = getattr(app.state, "dispatcher", None)
    if old_dispatcher:
        old_dispatcher.stop()

    if not getattr(app.state, "machine_loaded", False):
        load_machine(app)

    resolved = resolve_config_for_part(part_code)
    app.state.resolved_config = resolved
    _seed_sim_if_enabled(app, resolved)

    app.state.current_session_id = _create_part_session(part_code)
    session_id = app.state.current_session_id
    get_results_writer().start()

    registry = app.state.station_registry
    registry.build_from_config(resolved)

    for station_cfg in resolved.inspection_stations():
        defect_config = station_cfg.pipeline.defect
        measurement_config = station_cfg.pipeline.measurement
        draw_result = station_cfg.pipeline.result.draw_result
        for camera_id, camera_config in station_cfg.cameras.items():
            station = registry.get(camera_id)
            # Only pass a pipeline block through for cameras it actually
            # covers -- defect/measurement can each be scoped to a subset of
            # a station's cameras via allowed_cameras.
            camera_defect_config = (
                defect_config if defect_config and camera_id in defect_config.allowed_cameras else None
            )
            camera_measurement_config = (
                measurement_config
                if measurement_config and camera_id in measurement_config.allowed_cameras
                else None
            )

            if camera_config.sim.enabled:
                station.set_frame_provider(
                    sim_frame_provider(
                        camera_id,
                        image_path=camera_config.sim.image_path,
                        defect_config=camera_defect_config,
                        measurement_config=camera_measurement_config,
                        draw_result=draw_result,
                        indexer_tracker=app.state.indexer_tracker,
                        sim_verdict_enabled=resolved.plc.sim.enabled,
                    )
                )
            else:
                try:
                    provide, driver = real_frame_provider(
                        camera_id,
                        camera_config,
                        defect_config=camera_defect_config,
                        measurement_config=camera_measurement_config,
                        draw_result=draw_result,
                    )
                except CameraConnectionError:
                    log.warning(f"{camera_id}: real camera connect failed -- leaving station unavailable", exc_info=True)
                    continue
                station.set_frame_provider(provide)
                station.set_driver(driver)

            def make_on_result(
                cam_id=camera_id,
                station_id=station_cfg.id,
                is_defect_cam=(camera_defect_config is not None),
                is_measurement_cam=(camera_measurement_config is not None),
                pass_if=station_cfg.pipeline.result.pass_if,
                defect_cameras=frozenset(defect_config.allowed_cameras) if defect_config else frozenset(),
                measurement_cameras=frozenset(measurement_config.allowed_cameras) if measurement_config else frozenset(),
            ):
                def on_result(_cam_id, captured, slot_id=None, part_id=None):
                    zeromq.publish_camera_frame(cam_id, captured.frame)
                    passed = not captured.is_defect

                    # Ring-side bookkeeping: write this camera's result back
                    # onto its physical slot (IndexerSlotTracker), and once
                    # every camera at this station has reported, apply this
                    # station's pending->ok/nok transition. One call for
                    # either pipeline kind -- station_states treats every
                    # inspection station symmetrically; which pipeline block
                    # produced `passed` only matters for which key/expected-
                    # cameras set to aggregate over. part_id here is the
                    # tracker's real assign_part_id (threaded through from
                    # the dispatcher's fire_station call) -- deliberately
                    # NOT used below as the wire/DB part_id (see
                    # wire_part_id) to keep this change scoped to the state
                    # machine; switching ring_part_id over to the real
                    # tracker id is a natural, separate follow-up.
                    tracker = getattr(app.state, "indexer_tracker", None)
                    if tracker is not None and slot_id is not None:
                        if is_defect_cam:
                            key = f"{station_id}:defect"
                            tracker.record_camera_result(slot_id, key, cam_id, passed)
                            agg = tracker.station_aggregate(slot_id, key, defect_cameras, pass_if)
                        elif is_measurement_cam:
                            key = f"{station_id}:measurement"
                            tracker.record_camera_result(slot_id, key, cam_id, passed)
                            agg = tracker.station_aggregate(slot_id, key, measurement_cameras, pass_if)
                        else:
                            agg = None
                        if agg is not None:
                            # part_id passed through (spec13 #1) so a stale
                            # async result for a part that's since left this
                            # slot -- rejected/exited and a different part
                            # rotated in -- is dropped instead of silently
                            # applied to whoever's here now.
                            tracker.apply_station_result(slot_id, station_id, agg, part_id=part_id)

                    # Real tracker-assigned physical part identity (threaded
                    # through from the dispatcher's fire_station call) --
                    # the same part_id shows at every station it visits, so
                    # s1's and s2's cards for the same physical part now
                    # agree, and s2's number is always <= whatever's
                    # currently at s1 (it's downstream, so it's always
                    # showing an equal-or-older part). Falls back to the
                    # placeholder per-session fire counter (results_writer's
                    # next_ring_part_id, see its module docstring) only for
                    # callers with no ring context (e.g. ad-hoc/manual
                    # captures) -- never hit on the live dispatcher path,
                    # since fire_station() only fires when assign_part_id is
                    # already set.
                    wire_part_id = part_id if part_id is not None else next_ring_part_id(session_id if session_id is not None else 0)
                    zeromq.publish_inspection_result(
                        cam_id,
                        station_id,
                        passed,
                        captured.defect_label,
                        defect_confidence=captured.defect_confidence,
                        defect_count=captured.defect_count,
                        measurement_data=captured.measurement_data,
                        part_id=wire_part_id,
                    )
                    inspection.bump_totals(passed)

                    if session_id is not None:
                        fire_no = next_fire_no(session_id, station_id)
                        get_results_writer().enqueue(
                            ResultItem(
                                session_id=session_id,
                                station_id=station_id,
                                ring_part_id=wire_part_id,
                                station_fire_no=fire_no,
                                overall_passed=passed,
                                rejected=None,  # r1 mutates ring state only, no actuator wired yet -- see machine_config.yaml
                                camera_results=[
                                    CameraResultItem(
                                        camera_id=cam_id,
                                        pipeline_name="pipeline1",
                                        is_defective=captured.is_defect,
                                        defect_label=captured.defect_label,
                                        defect_confidence=captured.defect_confidence,
                                        measurement_data=captured.measurement_data,
                                        measurement_passed=(
                                            captured.measurement_data["diameter_mm"]["passed"]
                                            if captured.measurement_data
                                            else None
                                        ),
                                        camera_passed=passed,
                                    )
                                ],
                            )
                        )
                return on_result

            station.on_result = make_on_result()

    inspection.set_cameras(
        [{"camera_id": s.camera_id, "station_id": s.station_id} for s in registry.all_stations()]
    )

    # Wired but NOT started -- session start used to auto-run the motor
    # immediately, leaving no way to look at a loaded, idle ring before
    # parts start moving. Motor start is now a separate, explicit operator
    # action (POST /inspection/motor/start), matching Device Settings'
    # existing "run/stop indexer" framing (CLAUDE.md Section 3, page 4).
    dispatcher = StationDispatcher(resolved, registry, app.state.indexer_tracker)
    app.state.dispatcher = dispatcher
    return resolved
