"""Backend ZMQ PUB, adapted 1:1 from gcm's MessageBroadcaster. One PUB socket,
bound once, per-camera topics so multiple simultaneous feeds don't collide
on a single global topic (gcm hardcodes one camera and doesn't need this)."""

import base64
import logging
import os
import threading

import cv2
import zmq

log = logging.getLogger("zeromq")

_ctx = zmq.Context.instance()
_publisher = _ctx.socket(zmq.PUB)
_ZMQ_PORT = int(os.getenv("ZMQ_PORT", "5558"))
_bound = False
# libzmq sockets aren't safe for concurrent send from multiple threads --
# every station now fires on its own thread (see StationRegistry.fire_trigger),
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


def publish_inspection_result(camera_id: str, trigger_id: str, passed: bool, defect_label: str | None) -> None:
    import json

    payload = json.dumps({
        "camera_id": camera_id,
        "trigger_id": trigger_id,
        "passed": passed,
        "defect_label": defect_label,
    })
    broadcast("MessageType.InspectionResult", payload)
