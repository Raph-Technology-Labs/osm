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
Lucid setup before relying on it in production.

Pixel format follows CameraConfig.color: Mono8 by default (the models are
trained on mono), raw 8-bit Bayer debayered to BGR when color is true --
see select_pixel_format() / to_bgr().
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time

import cv2
import numpy as np

from app.camera.camera_driver import CameraConnectionError, CameraDriver

log = logging.getLogger("lucid_camera")

# GigE discovery. system.device_infos broadcasts on EVERY host interface
# (camera NICs, wifi, tailscale, docker bridges...) and waits the full
# DEVICE_INFOS_TIMEOUT_MILLISEC on each one, in turn. This arena_api build
# defaults it to 1000 ms (its docstring says 100), so on this host (9
# interfaces) one scan took ~9.2 s -- once per camera, every session start.
# Lucid cameras answer within 100 ms, so scan at that first (~1 s here), and
# only fall back to the slow timeout if the wanted camera wasn't seen.
DISCOVERY_FAST_TIMEOUT_MS = 100
DISCOVERY_SLOW_TIMEOUT_MS = 1000
# Cameras connected back-to-back in one session start share one scan.
DISCOVERY_CACHE_TTL_S = 5.0

_discovery_lock = threading.Lock()
_discovery_cache: tuple[float, list[dict]] | None = None


def discover_device(system, ip: str, clock=time.monotonic) -> tuple[dict | None, list[dict]]:
    """Find the device_info for `ip`. Returns (match or None, all infos seen).

    Order: recent cached scan -> fresh fast scan -> one slow scan. The slow
    scan only runs when the camera is genuinely missing (or answers late),
    so a camera that's there costs ~1 s, and a second camera in the same
    session start costs nothing."""
    global _discovery_cache

    def find(infos: list[dict]) -> dict | None:
        return next((d for d in infos if d.get("ip") == ip), None)

    with _discovery_lock:
        if _discovery_cache is not None and clock() - _discovery_cache[0] < DISCOVERY_CACHE_TTL_S:
            match = find(_discovery_cache[1])
            if match is not None:
                return match, _discovery_cache[1]

        infos: list[dict] = []
        for timeout_ms in (DISCOVERY_FAST_TIMEOUT_MS, DISCOVERY_SLOW_TIMEOUT_MS):
            system.DEVICE_INFOS_TIMEOUT_MILLISEC = timeout_ms
            t0 = clock()
            infos = list(system.device_infos)
            _discovery_cache = (clock(), infos)
            log.info(
                f"GigE discovery ({timeout_ms} ms timeout) took {clock() - t0:.2f}s, "
                f"found {[d.get('ip') for d in infos]}"
            )
            match = find(infos)
            if match is not None:
                return match, infos
        return None, infos

# GenICam 8-bit Bayer formats -> OpenCV codes. OpenCV names the pattern from
# the second row/column, so GenICam "BayerRG" (RGGB) is OpenCV's BayerBG --
# using the same-named code swaps red and blue (seen on the real TRI023S-C).
_BAYER_TO_BGR = {
    "BayerRG8": cv2.COLOR_BayerBG2BGR,
    "BayerGB8": cv2.COLOR_BayerGR2BGR,
    "BayerGR8": cv2.COLOR_BayerGB2BGR,
    "BayerBG8": cv2.COLOR_BayerRG2BGR,
}
_BAYER_TO_GRAY = {
    "BayerRG8": cv2.COLOR_BayerBG2GRAY,
    "BayerGB8": cv2.COLOR_BayerGR2GRAY,
    "BayerGR8": cv2.COLOR_BayerGB2GRAY,
    "BayerBG8": cv2.COLOR_BayerRG2GRAY,
}


def select_pixel_format(available: list[str], color: bool) -> str:
    """Pick the 8-bit PixelFormat for config.color.

    color=False -> Mono8 (colour Tritons offer it too, converted on-camera);
    raw Bayer only as a fallback on a colour camera without Mono8, turned to
    gray in to_bgr(). color=True -> raw Bayer, debayered in to_bgr(); a mono
    sensor has no Bayer format, so that's a config error, not a fallback.
    """
    bayer = next((f for f in _BAYER_TO_BGR if f in available), None)
    if color:
        if bayer is None:
            raise ValueError(
                f"color: true but the camera has no 8-bit Bayer format (mono sensor?); "
                f"available: {available}"
            )
        return bayer
    if "Mono8" in available:
        return "Mono8"
    if bayer is not None:
        return bayer
    raise ValueError(f"no Mono8 or 8-bit Bayer PixelFormat; available: {available}")


def to_bgr(raw: np.ndarray, pixel_format: str, color: bool) -> np.ndarray:
    """(H, W) uint8 sensor data -> (H, W, 3) BGR, the shape every pipeline
    stage expects. Mono output stays 3-channel gray, as before."""
    if pixel_format in _BAYER_TO_BGR:
        if color:
            return cv2.cvtColor(raw, _BAYER_TO_BGR[pixel_format])
        raw = cv2.cvtColor(raw, _BAYER_TO_GRAY[pixel_format])
    return cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)


# Triggered capture (capture_mode: single_shot). The camera must report
# TriggerArmed (ready for the next trigger) within this long before we give
# up -- normally it's immediate; longer means it's still exposing/reading
# out a previous frame or is wedged.
TRIGGER_ARMED_TIMEOUT_S = 0.5
# Max wait for a frame after the trigger: exposure + readout + transfer.
FRAME_TIMEOUT_MS = 2000
# Per-poll wait while draining leftover buffers before a trigger.
DRAIN_TIMEOUT_MS = 1
DRAIN_MAX_BUFFERS = 8


class LucidCamera(CameraDriver):
    def __init__(self, camera_id, config):
        super().__init__(camera_id, config)
        self._device = None
        self._pixel_format = "Mono8"
        # One capture at a time per camera: station fires run on their own
        # threads, and two overlapping trigger->get_buffer sequences on the
        # same device could each collect the other's frame.
        self._capture_lock = threading.Lock()
        self._trigger_armed = None
        self._trigger_software = None

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
        match, infos = discover_device(system, self.config.ip)
        if match is None:
            seen = [d.get("ip") for d in infos]
            raise CameraConnectionError(
                f"{self.camera_id}: no Lucid device found at ip={self.config.ip} (seen: {seen})"
            )

        try:
            devices = system.create_device(device_infos=[match])
            self._device = devices[0]
            self._configure(self._device)
            self._device.start_stream()
        except Exception as e:
            # Release the handle system.create_device() opened -- Arena SDK
            # holds an exclusive lock on the physical camera until
            # destroy_device() is called (its own docs: "if not called, the
            # system will call it when the module unloads," i.e. it stays
            # locked for the life of this process otherwise). Without this,
            # a failed connect() here permanently locks the camera out for
            # every later connect() attempt in the same run, surfacing as
            # SC_ERR_ACCESS_DENIED on a config that's otherwise fine.
            if self._device is not None:
                try:
                    system.destroy_device(self._device)
                except Exception:
                    log.warning(f"{self.camera_id}: destroy_device() cleanup failed", exc_info=True)
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

        # Zero the offsets before touching Width/Height: GenICam clamps
        # Width/Height's writable max to (WidthMax/HeightMax - current
        # offset), so a nonzero offset left over from a previous session
        # silently shrinks the max we can set below the sensor's true max
        # (confirmed against a real TRT023S-M: OffsetY=200 left Height's
        # max at 1000 instead of HeightMax=1200, so setting Height=1080
        # failed with SC_ERR_ERROR -1001). Apply the configured ROI offsets
        # after Width/Height are set to their final values.
        nodes["OffsetX"].value = 0
        nodes["OffsetY"].value = 0

        # Also reserve room for the offset here: OffsetX/OffsetY's own
        # writable max is symmetrically clamped to (WidthMax/HeightMax -
        # current Width/Height), so setting Width/Height to the sensor's
        # full max leaves no room for a nonzero roi.x1/y1 and the OffsetX/
        # OffsetY writes below fail with the same SC_ERR_ERROR -1001 this
        # function already works around for Width/Height above.
        nodes["Width"].value = min(
            self.config.resolution.x, nodes["WidthMax"].value - self.config.roi.x1
        )
        nodes["Height"].value = min(
            self.config.resolution.y, nodes["HeightMax"].value - self.config.roi.y1
        )
        nodes["OffsetX"].value = self.config.roi.x1
        nodes["OffsetY"].value = self.config.roi.y1
        self._pixel_format = select_pixel_format(
            nodes["PixelFormat"].enumentry_names, self.config.color
        )
        nodes["PixelFormat"].value = self._pixel_format
        # Order matters: throughput limit caps the max fps, and fps caps the
        # max exposure (ExposureTime can't exceed the frame period).
        nodes["AcquisitionFrameRateEnable"].value = True
        self._configure_throughput(nodemap)
        nodes["AcquisitionFrameRate"].value = float(self.config.fps)

        self._configure_exposure_gain(nodemap)
        self._configure_strobe(nodemap)
        self._configure_trigger(nodemap)

        stream_map = device.tl_stream_nodemap
        # "NewestOnly" (not gcm's "OldestFirst") -- matches this project's
        # own drop-old-frames convention for live feeds (CLAUDE.md Sec. 5.3).
        # In single_shot mode each frame belongs to one trigger, and
        # read_frame() drains anything left over before triggering, so
        # NewestOnly can't hand back a previous part's frame either.
        stream_map["StreamBufferHandlingMode"].value = "NewestOnly"
        stream_map["StreamAutoNegotiatePacketSize"].value = True
        stream_map["StreamPacketResendEnable"].value = True

    def _configure_throughput(self, nodemap) -> None:
        """Apply config.throughput_limit_mbps (None -> leave the camera's
        setting). DeviceLinkThroughputLimit is in bytes/s, and its max is the
        camera's current Ethernet link speed.

        A cap above the link speed is lowered to the link speed with a
        warning -- the link can't carry more anyway, so the cap's purpose
        (never exceed N) still holds. A cap below the camera's minimum is a
        config error. Then checks that the configured fps still fits, since
        the camera would otherwise reject the AcquisitionFrameRate write with
        a bare SDK error that doesn't say why."""
        mbps = self.config.throughput_limit_mbps
        if mbps is None:
            return
        nodemap.get_node("DeviceLinkThroughputLimitMode").value = "On"
        limit = nodemap.get_node("DeviceLinkThroughputLimit")
        link_mbps = limit.max * 8 / 1e6
        bytes_per_s = int(mbps * 1e6 / 8)
        if bytes_per_s < limit.min:
            raise ValueError(
                f"throughput_limit_mbps={mbps:g} is below this camera's minimum "
                f"{limit.min * 8 / 1e6:g} Mbit/s"
            )
        if bytes_per_s > limit.max:
            log.warning(
                f"{self.camera_id}: throughput_limit_mbps={mbps:g} is above the camera's "
                f"network link speed ({link_mbps:g} Mbit/s) -- capping at {link_mbps:g}. "
                f"If the link should be faster, check the cable and switch port."
            )
            bytes_per_s = int(limit.max)
        limit.value = bytes_per_s

        max_fps = nodemap.get_node("AcquisitionFrameRate").max
        if self.config.fps > max_fps:
            raise ValueError(
                f"fps={self.config.fps} doesn't fit through "
                f"{bytes_per_s * 8 / 1e6:g} Mbit/s (max {max_fps:.1f} fps at this "
                f"resolution; camera link is {link_mbps:g} Mbit/s) -- lower fps, shrink "
                f"the ROI, or get the camera onto a faster link (1 Gbit switch port/cable)"
            )
        log.info(f"{self.camera_id}: throughput limit {mbps:g} Mbit/s (max {max_fps:.1f} fps)")

    def _configure_exposure_gain(self, nodemap) -> None:
        """Apply config.exposure_us / gain_db with auto turned off. None ->
        leave the camera's current value. Out of the camera's range -> raise
        (connect() wraps it) rather than silently clamping, since a clamped
        exposure changes brightness and strobe pulse length behind the
        config's back."""
        for auto_name, node_name, value, unit in (
            ("ExposureAuto", "ExposureTime", self.config.exposure_us, "us"),
            ("GainAuto", "Gain", self.config.gain_db, "dB"),
        ):
            if value is None:
                continue
            nodemap.get_node(auto_name).value = "Off"
            node = nodemap.get_node(node_name)
            if not node.min <= value <= node.max:
                raise ValueError(
                    f"{node_name}={value}{unit} is outside this camera's range "
                    f"{node.min:g}-{node.max:g}{unit} at fps={self.config.fps}"
                )
            node.value = float(value)
            log.info(f"{self.camera_id}: {node_name} = {value}{unit}")

    def _configure_strobe(self, nodemap) -> None:
        """Drive the light from the camera's output line: one pulse per
        frame, lasting exactly the exposure time (LineSource =
        ExposureActive). The camera does the timing in hardware, so the
        light can't drift out of sync with the exposure and read_frame()
        needs no extra work. Checked against a real TRI023S-C with its
        strobe controller on Line1 (scripts/focus_live.py --strobe).

        Disabled -> line settings are left untouched. Enabled but the camera
        rejects a write -> raises, so connect() fails loudly instead of
        silently inspecting with the light dark.
        """
        strobe = self.config.strobe
        if not strobe.enabled:
            return

        nodemap.get_node("LineSelector").value = strobe.line
        line_mode = nodemap.get_node("LineMode")
        # Fixed-direction output lines expose LineMode read-only (already
        # "Output") -- only write it where the camera allows it.
        if line_mode.is_writable:
            line_mode.value = "Output"
        nodemap.get_node("LineSource").value = "ExposureActive"
        nodemap.get_node("LineInverter").value = strobe.inverted
        log.info(
            f"{self.camera_id}: strobe on {strobe.line} = ExposureActive"
            f"{' (inverted)' if strobe.inverted else ''}"
        )

    def _configure_trigger(self, nodemap) -> None:
        """capture_mode -> camera trigger setup.

        single_shot: the camera waits for a software trigger and exposes
        exactly one frame per read_frame() -- the picture is taken when the
        station fires, not up to a frame period earlier, and the strobe
        (ExposureActive) flashes once per part instead of at the free-run
        fps. continuous: free-run at fps, read_frame() returns the newest
        frame (the old behavior); TriggerMode is set Off explicitly so a
        camera left in trigger mode by another tool doesn't hang it.
        """
        nodemap.get_node("TriggerSelector").value = "FrameStart"
        trigger_mode = nodemap.get_node("TriggerMode")
        # TriggerSource is only guaranteed writable with the trigger off.
        trigger_mode.value = "Off"
        if self.config.capture_mode == "single_shot":
            nodemap.get_node("TriggerSource").value = "Software"
            trigger_mode.value = "On"
            self._trigger_armed = nodemap.get_node("TriggerArmed")
            self._trigger_software = nodemap.get_node("TriggerSoftware")
            log.info(f"{self.camera_id}: triggered capture (software trigger, 1 frame per read)")
        else:
            self._trigger_armed = self._trigger_software = None
            log.info(f"{self.camera_id}: continuous capture (free-run at {self.config.fps} fps)")

    def _drain_stale_buffers(self) -> None:
        """Requeue any frame already waiting (a late frame from a previous
        trigger whose read timed out) so this trigger's get_buffer() can't
        return it. Costs ~DRAIN_TIMEOUT_MS when the queue is empty."""
        for _ in range(DRAIN_MAX_BUFFERS):
            try:
                stale = self._device.get_buffer(timeout=DRAIN_TIMEOUT_MS)
            except Exception:  # noqa: BLE001 -- timeout = queue empty, the normal case
                return
            self._device.requeue_buffer(stale)
            log.warning(f"{self.camera_id}: discarded a stale frame before triggering")

    def _fire_software_trigger(self) -> None:
        self._drain_stale_buffers()
        deadline = time.monotonic() + TRIGGER_ARMED_TIMEOUT_S
        while not self._trigger_armed.value:
            if time.monotonic() > deadline:
                raise CameraConnectionError(
                    f"{self.camera_id}: camera not armed for a trigger within "
                    f"{TRIGGER_ARMED_TIMEOUT_S * 1000:.0f} ms (still busy with the previous frame?)"
                )
            time.sleep(0.0005)
        self._trigger_software.execute()

    def read_frame(self) -> np.ndarray:
        """single_shot: trigger one exposure now and return it.
        continuous: return the newest free-run frame.
        Buffer -> numpy is gcm's proven ctypes pattern (standalone_lucid.py:233-250)."""
        if self._device is None:
            raise CameraConnectionError(
                f"{self.camera_id}: read_frame() called before a successful connect()"
            )

        with self._capture_lock:
            if self._trigger_software is not None:
                try:
                    self._fire_software_trigger()
                except CameraConnectionError:
                    raise
                except Exception as e:
                    raise CameraConnectionError(f"{self.camera_id}: software trigger failed: {e}") from e

            try:
                buffer = self._device.get_buffer(timeout=FRAME_TIMEOUT_MS)
            except Exception as e:
                raise CameraConnectionError(f"{self.camera_id}: get_buffer() failed: {e}") from e

            try:
                arr = (ctypes.c_ubyte * (buffer.width * buffer.height)).from_address(
                    ctypes.addressof(buffer.pbytes)
                )
                raw = np.ndarray(buffer=arr, dtype=np.uint8, shape=(buffer.height, buffer.width)).copy()
            finally:
                self._device.requeue_buffer(buffer)

        return to_bgr(raw, self._pixel_format, self.config.color)

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
