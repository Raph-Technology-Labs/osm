import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.camera.station_registry import get_station_registry
from app.config.config_loader import resolve_config_for_part
from app.indexer.dispatcher import StationDispatcher
from app.routers import inspection
from app.routers.routers import router
from app.utils import zeromq

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

DEMO_PART_CODE = "rubber_1"


@app.on_event("startup")
def init_inspection_demo():
    """Floor-scope demo wiring: simulation-triggered capture -> mock
    pipeline -> ZMQ -> Inspection page. See plan.txt -- the real
    IndexerSlotTracker-driven ("plc" source) path is built/tested
    independently (app/indexer/tracker.py) but not live-wired here yet."""
    resolved = resolve_config_for_part(DEMO_PART_CODE)
    app.state.resolved_config = resolved

    zeromq.bind(resolved.zmq.port)

    registry = get_station_registry()
    registry.build_from_config(resolved)

    for trig in resolved.inspection_triggers():
        for camera_id, camera_config in trig.cameras.items():
            if not camera_config.sim.enabled:
                continue
            station = registry.get(camera_id)
            from app.camera.station_registry import sim_frame_provider
            station.set_frame_provider(sim_frame_provider(camera_id))

            def make_on_result(cam_id=camera_id, trig_id=trig.id):
                def on_result(_cam_id, captured):
                    zeromq.publish_camera_frame(cam_id, captured.frame)
                    passed = not captured.is_defect
                    zeromq.publish_inspection_result(cam_id, trig_id, passed, captured.defect_label)
                    inspection.bump_totals(passed)
                return on_result

            station.on_result = make_on_result()

    inspection.set_cameras([s.camera_id for s in registry.all_stations()])

    dispatcher = StationDispatcher(resolved, registry)
    app.state.dispatcher = dispatcher
    dispatcher.start()


@app.on_event("shutdown")
def stop_inspection_demo():
    dispatcher = getattr(app.state, "dispatcher", None)
    if dispatcher:
        dispatcher.stop()


@app.get("/")
def root():
    return {"message": "SCM Backend Running"}