"""Lucid Vision Labs camera driver (their Arena SDK under the hood) -- the
one Lucid-specific file in this package. Everything else
(station_registry.py, inspection_session.py, driver_registry.py) only ever
sees the vendor-agnostic CameraDriver contract (camera_driver.py); this file
is the only place that knows arena_api exists.

Built from /home/thor/rai/gcm-auto-training-rai/backend/app's working Lucid
integration (scripts/standalone_lucid.py, routers/camera/camera.py) -- a
sibling repo already referenced elsewhere in this codebase's own comments
("gcm's CameraManager", "gcm's InferenceEngine pattern") -- not invented
from memory, since arena_api's real API shape doesn't match the more
"modern-looking" BufferFactory-style API a first pass at this guessed.

Requires the `arena_api` Python package plus the ArenaSDK runtime installed
on the host. Lucid distributes both directly (not via PyPI) -- see
https://thinklucid.com/downloads-hub/ -- so this is NOT in requirements.txt
as a normal dependency; the import is deferred into connect() so the rest of
the app (sim-only towers, dev machines, CI) runs fine without it installed.
Only a camera actually configured with vendor: lucid (or arena) and
sim.enabled: false ever touches this code path.

GOTCHA (confirmed by gcm's routers/camera/camera.py:9-21 comment): arena_api
raises BaseException, not ImportError, when the underlying ArenaC .so is
missing -- a plain `except ImportError` does NOT catch it.

NOT fully verified against real hardware -- read_frame()/configure()/close()
mirror gcm's tested code closely. The one piece gcm's code never needed
(it hardcodes a single camera via system.create_device() with no filter):
selecting a specific camera by IP out of multiple discovered devices, in
connect() below. Smoke-test that specifically against a real multi-camera
Lucid setup before relying on it in production, and confirm the PixelFormat
= "Mono8" assumption matches the real cameras (a color camera needs a
different buffer reshape + cv2.cvtColor Bayer demosaic instead of
COLOR_GRAY2BGR).
"""

from __future__ import annotations

import ctypes
import logging

import cv2
import numpy as np

from app.camera.camera_driver import CameraConnectionError, CameraDriver

log = logging.getLogger("lucid_camera")


class LucidCamera(CameraDriver):
    def __init__(self, camera_id, config):
        super().__init__(camera_id, config)
        self._device = None

    def connect(self) -> None:
        try:
            from arena_api.system import system
        except BaseException as e:  # noqa: BLE001 -- arena_api raises non-ImportError
            # BaseException when its native .so is missing (confirmed by gcm)
            raise CameraConnectionError(
                f"{self.camera_id}: arena_api not available ({e!r}) -- install Lucid's "
                f"Arena SDK + arena_api Python bindings to use vendor: lucid cameras"
            ) from e

        # NOT verified against gcm's code -- gcm always grabs device 0 with
        # no filtering (single-camera setup). Fails loudly rather than
        # silently connecting to the wrong physical camera if this lookup
        # is off; confirm the 'ip' key name against real device_infos output.
        matches = [d for d in system.device_infos if d.get("ip") == self.config.ip]
        if not matches:
            seen = [d.get("ip") for d in system.device_infos]
            raise CameraConnectionError(
                f"{self.camera_id}: no Lucid device found at ip={self.config.ip} (seen: {seen})"
            )

        try:
            devices = system.create_device(device_infos=[matches[0]])
            self._device = devices[0]
            self._configure(self._device)
            self._device.start_stream()
        except Exception as e:
            self._device = None
            raise CameraConnectionError(f"{self.camera_id}: Lucid connect failed: {e}") from e

    def _configure(self, device) -> None:
        """Nodemap setup -- mirrors gcm's routers/camera/camera.py:60-93."""
        nodemap = device.nodemap
        nodes = nodemap.get_node(
            [
                "Width", "Height", "OffsetX", "OffsetY", "WidthMax", "HeightMax",
                "PixelFormat", "AcquisitionFrameRateEnable", "AcquisitionFrameRate",
            ]
        )

        nodes["Width"].value = min(self.config.resolution.x, nodes["WidthMax"].value)
        nodes["Height"].value = min(self.config.resolution.y, nodes["HeightMax"].value)
        nodes["OffsetX"].value = self.config.roi.x1
        nodes["OffsetY"].value = self.config.roi.y1
        # Assumes a monochrome sensor (matches gcm's configured cameras) --
        # a color camera needs a different PixelFormat + read_frame() reshape.
        nodes["PixelFormat"].value = "Mono8"
        # No exposure/gain fields exist on CameraConfig -- left on the
        # device's own default/auto rather than inventing fixed values with
        # no config backing (CLAUDE.md Rule 5: config-driven, not hardcoded).
        nodes["AcquisitionFrameRateEnable"].value = True
        nodes["AcquisitionFrameRate"].value = float(self.config.fps)

        stream_map = device.tl_stream_nodemap
        # "NewestOnly" (not gcm's "OldestFirst") -- matches this project's
        # own drop-old-frames convention for live feeds (CLAUDE.md Sec. 5.3).
        stream_map["StreamBufferHandlingMode"].value = "NewestOnly"
        stream_map["StreamAutoNegotiatePacketSize"].value = True
        stream_map["StreamPacketResendEnable"].value = True

    def read_frame(self) -> np.ndarray:
        """gcm's proven ctypes buffer->numpy pattern (standalone_lucid.py:233-250)."""
        if self._device is None:
            raise CameraConnectionError(
                f"{self.camera_id}: read_frame() called before a successful connect()"
            )

        try:
            buffer = self._device.get_buffer(timeout=2000)
        except Exception as e:
            raise CameraConnectionError(f"{self.camera_id}: get_buffer() failed: {e}") from e

        try:
            arr = (ctypes.c_ubyte * (buffer.width * buffer.height)).from_address(
                ctypes.addressof(buffer.pbytes)
            )
            gray = np.ndarray(buffer=arr, dtype=np.uint8, shape=(buffer.height, buffer.width)).copy()
        finally:
            self._device.requeue_buffer(buffer)

        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def close(self) -> None:
        if self._device is None:
            return
        from arena_api.system import system

        try:
            self._device.stop_stream()
        except Exception:
            log.warning(f"{self.camera_id}: stop_stream() failed during close()", exc_info=True)
        finally:
            system.destroy_device(self._device)
            self._device = None

    def is_connected(self) -> bool:
        """Mirrors gcm's CameraManager.is_initialized() liveness probe."""
        if self._device is None:
            return False
        try:
            _ = self._device.nodemap
            return True
        except Exception:
            log.warning(f"{self.camera_id}: device exists but not accessible", exc_info=True)
            self._device = None
            return False
