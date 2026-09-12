"""Backend ZMQ PUB, adapted 1:1 from gcm's MessageBroadcaster. One PUB socket,
bound once, per-camera topics so multiple simultaneous feeds don't collide
on a single global topic (gcm hardcodes one camera and doesn't need this)."""

import base64
import json
import logging
import os
import threading
import time

import cv2
import zmq

log = logging.getLogger("zeromq")

_ctx = zmq.Context.instance()
_publisher = _ctx.socket(zmq.PUB)
_ZMQ_PORT = int(os.getenv("ZMQ_PORT", "5558"))
_bound = False
# libzmq sockets aren't safe for concurrent send from multiple threads --
# every station now fires on its own thread (see StationRegistry.fire_station),
# so publish calls need to be serialized here.
_send_lock = threading.Lock()


def bind(port: int = _ZMQ_PORT) -> None:
    global _bound
    if _bound:
        return
    _publisher.bind(f"tcp://*:{port}")
    _bound = True
    log.info("ZMQ PUB bound on tcp://*:%d", port)


def broadcast(topic: str, message: str) -> None:
    with _send_lock:
        _publisher.send_multipart([topic.encode("utf-8"), message.encode("utf-8")])


def camera_feed_topic(camera_id: str) -> str:
    return f"MessageType.CameraFeed.{camera_id}"


def publish_camera_frame(camera_id: str, frame) -> None:
    """JPEG-encode + base64 into a data URL, same as gcm -- cheap to render
    directly as <img src=...> in React, no canvas needed."""
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        log.warning("Failed to JPEG-encode frame for %s", camera_id)
        return
    data_url = "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")
    broadcast(camera_feed_topic(camera_id), data_url)


def publish_inspection_result(
    camera_id: str,
    station_id: str,
    passed: bool,
    defect_label: str | None,
    defect_confidence: float | None = None,
    defect_count: int = 0,
    measurement_data: dict | None = None,
    part_id: int | None = None,
) -> None:
    payload = json.dumps({
        "camera_id": camera_id,
        "station_id": station_id,
        "passed": passed,
        "defect_label": defect_label,
        "defect_confidence": defect_confidence,
        "defect_count": defect_count,
        "measurement_data": measurement_data,
        "part_id": part_id,
    })
    broadcast("MessageType.InspectionResult", payload)


def publish_dispatcher_event(event: str, **fields) -> None:
    """Verbose, human-debuggable ring events (home calibrated, part admitted
    at the presence sensor, a station firing/marking a slot, reject
    armed/fired) -- for the Inspection page's live debug log panel, NOT for
    any ring-state rendering (that stays RingState/DigitalTwin's job). Each
    call mirrors a log.info/.warning already emitted server-side (see
    app/indexer/dispatcher.py) so the same event is visible both in the
    backend logs and live in the UI, without needing to tail a log file
    during commissioning. Best-effort: same fail-open behavior as
    publish_ring_state -- a bad event must never take down dispatch."""
    try:
        payload = json.dumps({"ts": time.time(), "event": event, **fields})
    except (TypeError, ValueError):
        log.error("publish_dispatcher_event: failed to serialize event %r -- skipping", event, exc_info=True)
        return
    broadcast("MessageType.DispatcherLog", payload)


def publish_ring_state(tracker, revolutions: int) -> None:
    """Full per-slot ring snapshot, once per dispatcher tick -- the digital
    twin's single source of truth for slot.status (DigitalTwin.jsx no
    longer reconstructs this client-side from the per-camera
    InspectionResult stream). Cheap at today's sim tick cadence; profile
    before assuming a per-tick full-ring broadcast is still fine at 900 PPM
    (CLAUDE.md Section 5).

    Called from StationDispatcher's tick, itself run from a
    threading.Timer callback -- an uncaught exception here would propagate
    into that callback, kill the timer thread, and never call
    _schedule_tick() (which runs after this in the tick), silently halting
    all future ticks with no error surfaced anywhere else (spec13 #7,
    found missing in spec12's code review). Caught and logged instead,
    skipping just this tick's publish, so a bad snapshot never takes down
    dispatch itself."""
    try:
        payload = json.dumps({
            "slots": {
                str(slot_id): {
                    "status": record.status.value,
                    "part_id": record.assign_part_id,
                    # station_id -> "unreached"|"pending"|"ok"|"nok", one entry
                    # per inspection station -- DigitalTwin.jsx renders one
                    # radial band per entry, in this dict's key order.
                    "station_states": record.station_states,
                }
                for slot_id, record in tracker.slots.items()
            },
            "entry_slot_id": tracker._entry_slot_id,
            "ok_total": tracker.ok_total,
            "nok_total": tracker.nok_total,
            "reject_removed": tracker.reject_removed,
            "revolutions": revolutions,
        })
    except (TypeError, ValueError):
        log.error("publish_ring_state: failed to serialize ring state -- skipping this tick's publish", exc_info=True)
        return
    broadcast("MessageType.RingState", payload)
