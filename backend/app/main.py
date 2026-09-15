import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.config_loader import DEFAULT_CONFIG_PATH
from app.routers import actuators, auth, dashboard, health, inspection, part_config, parts, parts_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
# DEBUG was only ever needed for the pulse_count/encoder_indexer_ppr register
# investigation (now resolved) -- at DEBUG, pymodbus's own logger dumps a
# raw SEND/RECV trace per Modbus transaction and the dispatcher logs its own
# per-tick pulse/gap trace, both of which drown out the signal that actually
# matters day to day: camera capture+inference timing
# (app/camera/station_registry.py's "capture+inference took Xms" line) and
# genuine warnings/errors. Quieted dispatcher's routine per-event INFO
# chatter (home calibrated, station fired, reject armed/fired) down to
# WARNING+ too -- still surfaces anything that actually needs attention
# (missed ACKs, faults, dropped detections), just not every normal tick.
logging.getLogger("pymodbus.logging").setLevel(logging.WARNING)
logging.getLogger("dispatcher").setLevel(logging.WARNING)

app = FastAPI()


# React connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth.router, prefix="/api/v1")
app.include_router(inspection.router, prefix="/api/v1")
app.include_router(parts_admin.router, prefix="/api/v1")
app.include_router(part_config.router, prefix="/api/v1")
app.include_router(parts.router, prefix="/api/v1")
app.include_router(actuators.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")


@app.on_event("startup")
def bootstrap_machine():
    # import pdb;
    # pdb.set_trace()
    """Config-driven boot: if machine_config.yaml exists, load cameras + PLC
    connection + indexer tracker immediately (no pipeline wiring, no
    dispatcher yet -- those are per-part, session-start concerns, see
    app/inspection_session.py). If the config file is absent, do nothing and
    wait idle for a part to be selected (POST /inspection/session/start
    triggers the same load lazily at that point)."""
    app.state.machine_loaded = False
    app.state.station_registry = None
    app.state.plc_client = None
    app.state.indexer_tracker = None
    app.state.dispatcher = None
    app.state.current_session_id = None
    app.state.plc_watchdog = None

    if not DEFAULT_CONFIG_PATH.exists():
        logging.getLogger("main").info(
            "No machine_config.yaml found at %s -- idle, waiting for part selection.",
            DEFAULT_CONFIG_PATH,
        )
        return

    from app.inspection_session import load_machine
    load_machine(app)


@app.on_event("shutdown")
def stop_inspection_demo():
    dispatcher = getattr(app.state, "dispatcher", None)
    if dispatcher:
        dispatcher.stop()
    plc_watchdog = getattr(app.state, "plc_watchdog", None)
    if plc_watchdog:
        plc_watchdog.stop()
    plc_client = getattr(app.state, "plc_client", None)
    if plc_client:
        plc_client.close()
    station_registry = getattr(app.state, "station_registry", None)
    if station_registry:
        station_registry.close_all()
    from app.services.results_writer import get_results_writer

    get_results_writer().stop()  # flush anything still queued, never drop silently


@app.get("/")
def root():
    return {"message": "OSM Backend Running"}