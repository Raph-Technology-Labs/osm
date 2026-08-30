import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.config_loader import DEFAULT_CONFIG_PATH
from app.routers import actuators, health, inspection, parts
from app.routers.routers import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI()


# React connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(router)
app.include_router(inspection.router, prefix="/api/v1")
app.include_router(parts.router, prefix="/api/v1")
app.include_router(actuators.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1")


@app.on_event("startup")
def bootstrap_machine():
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
    plc_client = getattr(app.state, "plc_client", None)
    if plc_client:
        plc_client.close()


@app.get("/")
def root():
    return {"message": "SCM Backend Running"}