#!/usr/bin/env python3
"""Smoke test for app.camera.lucid_camera.LucidCamera against a real Lucid
(Arena SDK) camera. Connects, pulls a few frames, closes, and reports
shape/dtype/basic stats -- no pipeline, no FastAPI app, just the driver.

Requires arena_api + the ArenaSDK runtime on the host (see requirements.txt's
note on this -- neither is pip-installable). If you don't have that locally,
run this inside an environment that does: this project's own dev machine had
it in a running `gcm-backend-hw` Docker container, verified like:

    docker cp backend/app/camera/camera_driver.py gcm-backend-hw:/tmp/smoke/app/camera/
    docker cp backend/app/camera/lucid_camera.py   gcm-backend-hw:/tmp/smoke/app/camera/
    docker cp backend/scripts/smoke_test_lucid_camera.py gcm-backend-hw:/tmp/
    docker exec gcm-backend-hw python3 /tmp/smoke_test_lucid_camera.py --ip <camera ip>

(plus empty __init__.py files under /tmp/smoke/app/ and /tmp/smoke/app/camera/,
and /tmp/smoke on sys.path -- see this script's own sys.path handling below
for the equivalent when running it in-place against a full checkout instead).

Known result from the first run on this project's dev machine: device
discovery (system.device_infos) matched this driver's 'ip' key assumption
correctly, but connect() itself hit SC_ERR_ACCESS_DENIED -- the only camera
reachable at the time was already held open by another running process on
that shared machine, not a code issue. Re-run against an actually-idle
camera to get past connect() and confirm read_frame()/close() too.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Allow running this script directly (python3 backend/scripts/smoke_test_lucid_camera.py)
# without needing the repo installed as a package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.camera.camera_driver import CameraConnectionError  # noqa: E402
from app.camera.lucid_camera import LucidCamera  # noqa: E402
from app.config.config_loader import CameraConfig  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True, help="IP of the real Lucid camera to test")
    parser.add_argument("--camera-id", default="smoke_cam")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--frames", type=int, default=3, help="number of read_frame() calls")
    args = parser.parse_args()

    config = CameraConfig(
        ip=args.ip,
        vendor="lucid",
        resolution={"x": args.width, "y": args.height},
        roi={"x1": 0, "y1": 0, "x2": args.width, "y2": args.height},
        fps=args.fps,
    )
    camera = LucidCamera(args.camera_id, config)

    print(f"--- connect() to {args.ip} ---")
    try:
        camera.connect()
    except CameraConnectionError as e:
        print("CONNECT FAILED:", e)
        sys.exit(1)
    print("connect() OK, is_connected():", camera.is_connected())

    print(f"--- read_frame() x{args.frames} ---")
    try:
        for i in range(args.frames):
            t0 = time.time()
            frame = camera.read_frame()
            dt = time.time() - t0
            print(
                f"frame {i}: shape={frame.shape} dtype={frame.dtype} "
                f"min={frame.min()} max={frame.max()} mean={frame.mean():.2f} took={dt * 1000:.1f}ms"
            )
    except CameraConnectionError as e:
        print("READ_FRAME FAILED:", e)
    finally:
        print("--- close() ---")
        camera.close()
        print("is_connected() after close():", camera.is_connected())


if __name__ == "__main__":
    main()
