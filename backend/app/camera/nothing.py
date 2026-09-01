# def start_session(app: FastAPI, part_code: str) -> ResolvedMachineConfig:
#     """Resolve part config, wire the pipeline stand-in, (re)start the
#     dispatcher. Lazily runs load_machine() first if boot found no config
#     file yet."""
#     from app.routers import inspection  # local import: avoids a circular
#     # import (inspection.py would otherwise need this module at load time)

#     if not getattr(app.state, "machine_loaded", False):
#         load_machine(app)

#     resolved = resolve_config_for_part(part_code)
#     app.state.resolved_config = resolved

#     registry = app.state.station_registry
#     registry.build_from_config(resolved)

#     for trig in resolved.inspection_triggers():
#         for camera_id, camera_config in trig.cameras.items():
#             if not camera_config.sim.enabled:
#                 continue
#             station = registry.get(camera_id)
#             station.set_frame_provider(sim_frame_provider(camera_id))

#             def make_on_result(cam_id=camera_id, trig_id=trig.id):
#                 def on_result(_cam_id, captured):
#                     zeromq.publish_camera_frame(cam_id, captured.frame)
#                     passed = not captured.is_defect
#                     zeromq.publish_inspection_result(cam_id, trig_id, passed, captured.defect_label)
#                     inspection.bump_totals(passed)
#                 return on_result

#             station.on_result = make_on_result()

#     inspection.set_cameras([s.camera_id for s in registry.all_stations()])

#     old_dispatcher = getattr(app.state, "dispatcher", None)
#     if old_dispatcher:
#         old_dispatcher.stop()

"""
The above function imports inspection from routers
Function of inspection.py is :-

1. load_machine config if not present
2. use the build config to build the station registry present in the station_registry.py in the cameras module
3. we use the load_machine(app) where app is the entire FastAPI Session keeps record of the entire state fo the application and the state is used to store the resolved config and the station registry 
4. app.state.resolved_config = resolved stores the necessary YAML Configs for that session
5. register = app.state.station_registry = get_station_registry() loaded in the load_machine function call above
6. then we do step 1 here at step 6
7. At this stage we have Registry [StationRegistry -> [build_from_config(), stations_for_trigger(), fire_trigger()]],
8. we iterate over triggers from resolved.inspection_triggers() which is a List of InspectionTrigger objects 
9. InspectionTrigger refers it own slot match rule and triggers the camera stations based on the trigger_id and the camera_id
10. the nested function make_on_result is used to publish the camera frame and the inspection result over zeromq
11. F
"""