"""Live view with the light on -- for setting up the lens (aperture, focus) by hand.

Opens one Lucid camera and shows a live feed next to a control panel:

  * Light     -- STEADY: the output line (Line1) is held on like a normal lamp.
                 STROBE: the line pulses with every exposure, exactly like
                 production (use this if the light controller only reacts to
                 pulses). Switch with the "Mode" button or start with --strobe.
  * Exposure / Gain -- labelled sliders with -/+ buttons (auto is turned off).
  * Focus     -- sharpness score of the yellow centre box and the best value
                 seen; sweep the focus ring through the peak and go back to it.
  * Aperture  -- brightness (mean 0-255) and % of pure white / pure black pixels.

Hover over any button, slider or value in the panel to see what it does.

On exit (Quit button / q / Esc / Ctrl+C / closing the window) the line,
trigger, frame-rate, bandwidth and pixel-format settings are put back, so the
strobe fires with ExposureActive again. Exposure and gain are LEFT at the
values you chose (printed on exit); they are not saved to a UserSet, so a
camera reboot reverts them.

Nothing else may hold the camera while this runs: close ArenaView, stop the
osm backend / any old scripts first (only one process can control a camera).

WARNING: some strobe lights are only rated for pulsed (overdrive) use. With
such a light use --strobe, or don't leave STEADY on for long.

Usage:
    python focus_live.py                        # 192.168.7.41, Line1, steady light
    python focus_live.py --strobe               # light pulses with each exposure
    python focus_live.py --ip 192.168.6.41 --fps 15 --throughput 0
    python focus_live.py --exposure 200 --gain 0

Keys:
    q / Esc  quit          l  light on/off     m  steady/strobe
    c  clipping overlay    z  zoom 1x/2x/4x    r  reset best focus
    [ / ]  exposure -/+10% s  save full-resolution PNG
"""

from __future__ import annotations

import argparse
import ctypes
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# OpenCV's bundled Qt looks for fonts inside the wheel and warns when it finds
# none; point it at the system fonts before cv2 is imported.
for _fontdir in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype"):
    if Path(_fontdir).is_dir():
        os.environ.setdefault("QT_QPA_FONTDIR", _fontdir)
        break

import cv2  # noqa: E402
import numpy as np  # noqa: E402

WINDOW = "focus_live - lens setup"
SNAP_DIR = Path.home() / "Documents" / "luciddesk" / "focus"
MAX_VIEW = (1280, 800)  # live image area (w, h); panel goes to the right
PANEL_W = 400
MIN_H = 800
EXPOSURE_SLIDER_CAP_US = 200_000

# OpenCV names Bayer patterns from the second row/column, so GenICam
# "BayerRG" (RGGB) is OpenCV's BayerBG. Using the same-named code swaps R/B.
BAYER_CODES = {
    "BayerRG8": cv2.COLOR_BayerBG2BGR,
    "BayerGB8": cv2.COLOR_BayerGR2BGR,
    "BayerGR8": cv2.COLOR_BayerGB2BGR,
    "BayerBG8": cv2.COLOR_BayerRG2BGR,
}

# Colours (BGR)
BG = (32, 32, 32)
FG = (230, 230, 230)
DIM = (150, 150, 150)
GREEN = (80, 200, 80)
AMBER = (0, 190, 255)
RED = (60, 60, 230)
ACCENT = (230, 160, 40)
BTN = (70, 70, 70)
BTN_HOVER = (100, 100, 100)
FONT = cv2.FONT_HERSHEY_SIMPLEX


# --------------------------------------------------------------------------- #
# Node helpers
# --------------------------------------------------------------------------- #
def node(nodemap, name):
    """Return the node or None if this camera model doesn't have it."""
    try:
        return nodemap.get_node(name)
    except (KeyError, ValueError):
        return None


def read(nodemap, name):
    n = node(nodemap, name)
    if n is None or not n.is_readable:
        return None
    return n.value


def write(nodemap, name, value, quiet=False) -> bool:
    """Write a node if it exists and is writable. Numbers are clamped."""
    n = node(nodemap, name)
    if n is None:
        if not quiet:
            print(f"  [skip] {name}: not on this camera")
        return False
    if not n.is_writable:
        if not quiet:
            print(f"  [skip] {name}: not writable right now")
        return False
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = type(n.value)(min(max(value, n.min), n.max))
        n.value = value
        return True
    except Exception as e:  # noqa: BLE001 -- arena raises generic errors
        if not quiet:
            print(f"  [fail] {name} = {value!r}: {e}")
        return False


# --------------------------------------------------------------------------- #
# Camera setup / restore
# --------------------------------------------------------------------------- #
class Session:
    def __init__(self, device, line: str, strobe: bool):
        self.device = device
        self.nm = device.nodemap
        self.line = line
        self.strobe = strobe
        self.light_on = True
        self.saved: dict[str, object] = {}

    def _save(self, key: str, name: str) -> None:
        val = read(self.nm, name)
        if val is not None:
            self.saved[key] = val

    def configure(
        self, fps: float, exposure: float | None, gain: float | None, throughput_mbps: float
    ) -> None:
        nm = self.nm

        # Pixel format: raw 8-bit Bayer on colour sensors (debayered here),
        # Mono8 on mono sensors.
        self._save("PixelFormat", "PixelFormat")
        entries = node(nm, "PixelFormat").enumentry_names
        fmt = next((f for f in (*BAYER_CODES, "Mono8") if f in entries), None)
        if fmt is None:
            raise RuntimeError(f"no 8-bit Bayer or Mono8 pixel format (have: {entries})")
        write(nm, "PixelFormat", fmt)

        # Bandwidth cap so frames aren't lost on a slow host link (e.g. a
        # 100 Mb/s NIC): the camera spreads packets out to this rate.
        if throughput_mbps > 0:
            self._save("DeviceLinkThroughputLimitMode", "DeviceLinkThroughputLimitMode")
            self._save("DeviceLinkThroughputLimit", "DeviceLinkThroughputLimit")
            write(nm, "DeviceLinkThroughputLimitMode", "On")
            write(nm, "DeviceLinkThroughputLimit", int(throughput_mbps * 1e6 / 8))  # bytes/s

        # Free-run: a hardware trigger from the PLC would freeze the feed.
        write(nm, "TriggerSelector", "FrameStart", quiet=True)
        self._save("TriggerMode", "TriggerMode")
        write(nm, "TriggerMode", "Off")

        # Frame rate first -- it limits the maximum exposure.
        self._save("AcquisitionFrameRateEnable", "AcquisitionFrameRateEnable")
        self._save("AcquisitionFrameRate", "AcquisitionFrameRate")
        write(nm, "AcquisitionFrameRateEnable", True)
        write(nm, "AcquisitionFrameRate", float(fps))

        write(nm, "ExposureAuto", "Off")
        write(nm, "GainAuto", "Off")
        if exposure is not None:
            write(nm, "ExposureTime", float(exposure))
        if gain is not None:
            write(nm, "Gain", float(gain))

        write(nm, "LineSelector", self.line)
        self._save("LineMode", "LineMode")
        self._save("LineSource", "LineSource")
        write(nm, "UserOutputSelector", "UserOutput0", quiet=True)
        self._save("UserOutputValue", "UserOutputValue")
        write(nm, "LineMode", "Output", quiet=True)  # read-only on fixed outputs
        if not self.apply_light():
            raise RuntimeError(f"cannot drive {self.line} (LineSource not writable)")

        tl = self.device.tl_stream_nodemap
        tl["StreamBufferHandlingMode"].value = "NewestOnly"
        tl["StreamAutoNegotiatePacketSize"].value = True
        tl["StreamPacketResendEnable"].value = True

    def apply_light(self) -> bool:
        """Drive the output line from the current mode + on/off state."""
        nm = self.nm
        write(nm, "LineSelector", self.line, quiet=True)
        sources = node(nm, "LineSource").enumentry_names
        if self.strobe and self.light_on:
            return write(nm, "LineSource", "ExposureActive")
        if self.strobe and "Off" in sources:
            return write(nm, "LineSource", "Off")
        # Steady mode (or strobe-off on a model without "Off"): user output.
        ok = write(nm, "LineSource", "UserOutput0")
        write(nm, "UserOutputSelector", "UserOutput0", quiet=True)
        return ok and write(nm, "UserOutputValue", self.light_on and not self.strobe)

    def toggle_light(self) -> None:
        self.light_on = not self.light_on
        self.apply_light()

    def toggle_mode(self) -> None:
        self.strobe = not self.strobe
        self.apply_light()

    def restore(self) -> None:
        """Put back everything we changed except exposure/gain."""
        nm, s = self.nm, self.saved
        print("Restoring camera settings...")
        write(nm, "LineSelector", self.line, quiet=True)
        if "LineSource" in s:
            write(nm, "LineSource", s["LineSource"])
        if "LineMode" in s:
            write(nm, "LineMode", s["LineMode"], quiet=True)
        write(nm, "UserOutputSelector", "UserOutput0", quiet=True)
        write(nm, "UserOutputValue", s.get("UserOutputValue", False), quiet=True)
        write(nm, "TriggerSelector", "FrameStart", quiet=True)
        if "TriggerMode" in s:
            write(nm, "TriggerMode", s["TriggerMode"])
        if "AcquisitionFrameRateEnable" in s:
            write(nm, "AcquisitionFrameRateEnable", s["AcquisitionFrameRateEnable"])
        if s.get("AcquisitionFrameRateEnable") and "AcquisitionFrameRate" in s:
            write(nm, "AcquisitionFrameRate", s["AcquisitionFrameRate"], quiet=True)
        if "DeviceLinkThroughputLimit" in s:
            write(nm, "DeviceLinkThroughputLimit", s["DeviceLinkThroughputLimit"], quiet=True)
        if "DeviceLinkThroughputLimitMode" in s:
            write(nm, "DeviceLinkThroughputLimitMode", s["DeviceLinkThroughputLimitMode"], quiet=True)
        if "PixelFormat" in s:  # stream is stopped by now, so this is writable
            write(nm, "PixelFormat", s["PixelFormat"], quiet=True)


# --------------------------------------------------------------------------- #
# Acquisition thread (keeps the UI responsive at low frame rates)
# --------------------------------------------------------------------------- #
@dataclass
class FrameData:
    frame: np.ndarray  # BGR, full resolution
    gray: np.ndarray
    score: float
    mean: float
    hi: float  # % pure white
    lo: float  # % pure black


def buffer_to_image(buffer, pixel_format: str) -> np.ndarray:
    """Copy an 8-bit Arena buffer into a BGR numpy image (caller requeues)."""
    w, h = buffer.width, buffer.height
    arr = (ctypes.c_ubyte * (w * h)).from_address(ctypes.addressof(buffer.pbytes))
    raw = np.ndarray(buffer=arr, dtype=np.uint8, shape=(h, w)).copy()
    if pixel_format in BAYER_CODES:
        return cv2.cvtColor(raw, BAYER_CODES[pixel_format])
    return cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)


def centre_box(w: int, h: int, frac: float = 1 / 3) -> tuple[int, int, int, int]:
    bw, bh = int(w * frac), int(h * frac)
    x0, y0 = (w - bw) // 2, (h - bh) // 2
    return x0, y0, x0 + bw, y0 + bh


class Grabber(threading.Thread):
    def __init__(self, device, pixel_format: str):
        super().__init__(daemon=True)
        self.device = device
        self.pixel_format = pixel_format
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.latest: FrameData | None = None
        self.fps = 0.0
        self.frames = 0
        self.incomplete = 0
        self.error = ""

    def run(self) -> None:
        t_prev = time.monotonic()
        while not self.stop_event.is_set():
            try:
                buf = self.device.get_buffer(timeout=1000)
            except Exception as e:  # noqa: BLE001 -- timeout or link error
                self.error = f"no frame: {e}"[:80]
                continue
            try:
                bad = buf.is_incomplete
                frame = buffer_to_image(buf, self.pixel_format)
            finally:
                self.device.requeue_buffer(buf)

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape
            x0, y0, x1, y1 = centre_box(w, h)
            data = FrameData(
                frame=frame,
                gray=gray,
                score=float(cv2.Laplacian(gray[y0:y1, x0:x1], cv2.CV_64F).var()),
                mean=float(gray.mean()),
                hi=float((gray >= 255).mean() * 100),
                lo=float((gray <= 0).mean() * 100),
            )
            now = time.monotonic()
            with self.lock:
                self.latest = data
                self.frames += 1
                self.incomplete += int(bad)
                self.fps = 0.8 * self.fps + 0.2 / max(now - t_prev, 1e-6)
                self.error = ""
            t_prev = now


# --------------------------------------------------------------------------- #
# Control panel (drawn with OpenCV, so every control has a label + tooltip)
# --------------------------------------------------------------------------- #
TIPS = {
    "image": "Live image. The yellow box is the area used for the focus score - "
             "put the feature you care about inside it.",
    "status": "Frames per second actually received, image size and pixel format. "
              "'bad' counts frames damaged by network packet loss - if it keeps rising, "
              "lower --fps or --throughput.",
    "light": "Turn the light on or off. STEADY: stays on like a normal lamp. "
             "STROBE: flashes once per frame, for the exposure time.  Key: L",
    "mode": "STEADY holds Line1 on - easiest for adjusting aperture and focus by eye. "
            "STROBE pulses Line1 with every exposure, exactly like production - use it "
            "if the light controller only reacts to pulses.  Key: M",
    "exposure": "Exposure: how long the sensor collects light for each frame (us = "
                "microseconds). Longer = brighter, but moving parts blur. In STROBE mode it "
                "is also the flash length. Drag the bar or use - / +.  Keys: [ ]",
    "exp_dn": "Exposure -10%.  Key: [",
    "exp_up": "Exposure +10%.  Key: ]",
    "gain": "Gain: electronic amplification in dB. Brightens without a longer exposure "
            "but adds noise. Keep it low (0-6 dB): open the aperture or raise exposure first.",
    "gain_dn": "Gain -0.5 dB",
    "gain_up": "Gain +0.5 dB",
    "clip": "Show lost detail: pure white pixels (255) are painted RED, pure black (0) "
            "BLUE. These are marker colours, not the real image.  Key: C",
    "zoom": "Zoom into the centre: 1x -> 2x -> 4x. At 4x you see single sensor pixels - "
            "best for fine focus.  Key: Z",
    "reset": "Forget the best focus score. Use it after moving the part or changing the "
             "aperture, then sweep the focus ring through the sharp point again.  Key: R",
    "snap": "Save the current full-resolution frame (without markers) as PNG in "
            "~/Documents/luciddesk/focus/.  Key: S",
    "quit": "Stop and restore Line1, trigger, frame rate and bandwidth settings, then "
            "release the camera. Exposure and gain keep your values.  Keys: Q / Esc",
    "bright": "Brightness = average pixel level of the whole image, 0 (black) to 255 "
              "(white). Aim for about 100-180 (green zone). Adjust in this order: "
              "aperture ring, then exposure, then gain.",
    "white": "Pixels that are pure white (255) - detail there is lost. Keep it under "
             "~1% on the part itself: close the aperture a bit or shorten exposure.",
    "black": "Pixels that are pure black (0). A dark background is fine; the part "
             "itself should not be black.",
    "focus": "Sharpness inside the yellow box (higher = sharper). Turn the focus ring "
             "slowly through the sharp point: the score rises, peaks, then falls. Go back "
             "to the peak - 95%+ of best turns green. Only compare with the same light "
             "and aperture.",
}
DEFAULT_TIP = ("Hover over any button, slider or value to see what it does.  "
               "Keys: L light, M mode, C clip, Z zoom, R reset, [ ] exposure, S save, Q quit")


def text(img, s, org, scale=0.55, color=FG, thick=1) -> None:
    cv2.putText(img, s, org, FONT, scale, color, thick, cv2.LINE_AA)


def wrap(s: str, width_px: int, scale: float) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        trial = f"{cur} {word}".strip()
        if cv2.getTextSize(trial, FONT, scale, 1)[0][0] > width_px and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return [*lines, cur] if cur else lines


def inside(rect, x, y) -> bool:
    x0, y0, x1, y1 = rect
    return x0 <= x < x1 and y0 <= y < y1


class Panel:
    def __init__(self, sess: Session, grabber: Grabber, title: str, frame_wh: tuple[int, int]):
        self.sess = sess
        self.grabber = grabber
        self.title = title
        fw, fh = frame_wh
        scale = min(MAX_VIEW[0] / fw, MAX_VIEW[1] / fh, 1.0)
        self.vw, self.vh = int(fw * scale), int(fh * scale)
        self.h = max(self.vh, MIN_H)
        self.w = self.vw + PANEL_W

        self.exp = node(sess.nm, "ExposureTime")
        self.gain = node(sess.nm, "Gain")
        self.show_clip = False
        self.zoom = 1
        self.best = 0.0
        self.message, self.message_t = "", 0.0

        self.mouse = (-1, -1)
        self.drag: str | None = None
        self.pending: dict[str, float] = {}  # slider values waiting to be written
        self.actions: list[str] = []
        self.last_write = 0.0
        self.cache: dict[str, float] = {}
        self.cache_t = 0.0
        self._refresh_cache()

        p, pw = self.vw + 16, PANEL_W - 32
        half = (pw - 12) // 2
        self.p, self.pw = p, pw
        self.rects = {
            "image": (0, 0, self.vw, self.vh),
            "status": (p, 38, p + pw, 62),
            "light": (p, 72, p + half, 110),
            "mode": (p + half + 12, 72, p + pw, 110),
            "exp_dn": (p, 150, p + 32, 180),
            "exposure": (p + 42, 150, p + pw - 42, 180),
            "exp_up": (p + pw - 32, 150, p + pw, 180),
            "gain_dn": (p, 238, p + 32, 268),
            "gain": (p + 42, 238, p + pw - 42, 268),
            "gain_up": (p + pw - 32, 238, p + pw, 268),
            "clip": (p, 304, p + half, 342),
            "zoom": (p + half + 12, 304, p + pw, 342),
            "reset": (p, 352, p + half, 390),
            "snap": (p + half + 12, 352, p + pw, 390),
            "quit": (p, 400, p + pw, 438),
            "bright": (p, 452, p + pw, 502),
            "white": (p, 506, p + pw, 528),
            "black": (p, 532, p + pw, 554),
            "focus": (p, 562, p + pw, 612),
        }

    # -- camera values --------------------------------------------------------
    def _refresh_cache(self) -> None:
        c = self.cache
        c["exp"], c["exp_min"] = self.exp.value, max(self.exp.min, 1.0)
        c["exp_max"] = min(self.exp.max, EXPOSURE_SLIDER_CAP_US)
        if self.gain is not None:
            c["gain"], c["gain_min"], c["gain_max"] = self.gain.value, self.gain.min, self.gain.max
        self.cache_t = time.monotonic()

    def _slider_frac(self, key: str) -> float:
        c = self.cache
        if key == "exposure":
            v = self.pending.get(key, c["exp"])
            lo, hi = np.log(c["exp_min"]), np.log(c["exp_max"])
            return float(np.clip((np.log(max(v, 1e-3)) - lo) / (hi - lo), 0, 1))
        v = self.pending.get(key, c.get("gain", 0.0))
        span = c.get("gain_max", 1.0) - c.get("gain_min", 0.0)
        return float(np.clip((v - c.get("gain_min", 0.0)) / max(span, 1e-6), 0, 1))

    def _slider_value(self, key: str, x: int) -> float:
        x0, _, x1, _ = self.rects[key]
        f = float(np.clip((x - x0) / (x1 - x0), 0, 1))
        c = self.cache
        if key == "exposure":
            lo, hi = np.log(c["exp_min"]), np.log(c["exp_max"])
            return float(np.exp(lo + f * (hi - lo)))
        return c["gain_min"] + f * (c["gain_max"] - c["gain_min"])

    def apply_pending(self) -> None:
        now = time.monotonic()
        if self.pending and now - self.last_write > 0.1:
            if "exposure" in self.pending:
                write(self.sess.nm, "ExposureTime", self.pending.pop("exposure"))
            if "gain" in self.pending and self.gain is not None:
                write(self.sess.nm, "Gain", self.pending.pop("gain"))
            self.last_write = now
            self._refresh_cache()
        elif now - self.cache_t > 1.0 and not self.drag:
            self._refresh_cache()

    # -- input ----------------------------------------------------------------
    def on_mouse(self, event, x, y, _flags, _param) -> None:
        self.mouse = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            for key, rect in self.rects.items():
                x0, y0, x1, y1 = rect
                if key in ("exposure", "gain") and inside((x0, y0 - 8, x1, y1 + 8), x, y):
                    if key == "gain" and self.gain is None:
                        return
                    self.drag = key
                    self.pending[key] = self._slider_value(key, x)
                    return
                if inside(rect, x, y):
                    self.actions.append(key)
                    return
        elif event == cv2.EVENT_MOUSEMOVE and self.drag:
            self.pending[self.drag] = self._slider_value(self.drag, x)
        elif event == cv2.EVENT_LBUTTONUP:
            self.drag = None

    def handle(self, action: str) -> bool:
        """Run a button/key action. Returns False to quit."""
        nm, c = self.sess.nm, self.cache
        if action == "quit":
            return False
        if action == "light":
            self.sess.toggle_light()
        elif action == "mode":
            self.sess.toggle_mode()
        elif action == "clip":
            self.show_clip = not self.show_clip
        elif action == "zoom":
            self.zoom = {1: 2, 2: 4, 4: 1}[self.zoom]
        elif action == "reset":
            self.best = 0.0
        elif action in ("exp_dn", "exp_up"):
            write(nm, "ExposureTime", c["exp"] * (0.9 if action == "exp_dn" else 1.1))
            self._refresh_cache()
        elif action in ("gain_dn", "gain_up") and self.gain is not None:
            write(nm, "Gain", c["gain"] + (-0.5 if action == "gain_dn" else 0.5))
            self._refresh_cache()
        elif action == "snap":
            self.snapshot()
        return True

    def snapshot(self) -> None:
        with self.grabber.lock:
            data = self.grabber.latest
        if data is None:
            self.flash("No frame yet - nothing saved")
            return
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        path = (SNAP_DIR / f"focus_{datetime.now():%Y%m%d_%H%M%S}.png").resolve()
        ok = cv2.imwrite(str(path), data.frame)
        self.flash(f"Saved {path}" if ok else f"FAILED to save {path}")
        print(self.message)

    def flash(self, msg: str) -> None:
        self.message, self.message_t = msg, time.monotonic()

    # -- drawing --------------------------------------------------------------
    def render(self) -> np.ndarray:
        canvas = np.full((self.h, self.w, 3), BG, np.uint8)
        with self.grabber.lock:
            data = self.grabber.latest
            fps, frames, bad, err = (self.grabber.fps, self.grabber.frames,
                                     self.grabber.incomplete, self.grabber.error)
        if data is not None:
            self.best = max(self.best, data.score)
            canvas[: self.vh, : self.vw] = self._view(data)
        else:
            text(canvas, "Waiting for the first frame...", (30, 60), 0.8, AMBER, 2)
        if err:
            text(canvas, err, (12, self.vh - 14), 0.55, RED, 1)
        self._panel(canvas, data, fps, frames, bad)
        return canvas

    def _view(self, data: FrameData) -> np.ndarray:
        img = data.frame.copy()
        if self.show_clip:
            img[data.gray >= 255] = (0, 0, 255)
            img[data.gray <= 0] = (255, 0, 0)
        h, w = img.shape[:2]
        x0, y0, x1, y1 = centre_box(w, h)
        cv2.rectangle(img, (x0, y0), (x1, y1), (0, 255, 255), max(2, w // 600))
        if self.zoom > 1:  # centre crop at sensor resolution
            zw, zh = w // self.zoom, h // self.zoom
            zx, zy = (w - zw) // 2, (h - zh) // 2
            img = img[zy:zy + zh, zx:zx + zw]
        interp = cv2.INTER_AREA if img.shape[1] > self.vw else cv2.INTER_NEAREST
        img = cv2.resize(img, (self.vw, self.vh), interpolation=interp)
        mode = "STROBE" if self.sess.strobe else "STEADY"
        state = f"LIGHT {'ON' if self.sess.light_on else 'OFF'} ({mode})   zoom {self.zoom}x"
        cv2.putText(img, state, (12, 30), FONT, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, state, (12, 30), FONT, 0.7,
                    GREEN if self.sess.light_on else RED, 2, cv2.LINE_AA)
        return img

    def _button(self, img, key: str, label: str, color=BTN) -> None:
        x0, y0, x1, y1 = self.rects[key]
        hover = inside(self.rects[key], *self.mouse)
        cv2.rectangle(img, (x0, y0), (x1, y1), BTN_HOVER if hover else color, -1)
        cv2.rectangle(img, (x0, y0), (x1, y1), ACCENT if hover else DIM, 1)
        (tw, th), _ = cv2.getTextSize(label, FONT, 0.55, 1)
        text(img, label, (x0 + (x1 - x0 - tw) // 2, y0 + (y1 - y0 + th) // 2))

    def _slider(self, img, key: str, frac: float) -> None:
        x0, y0, x1, y1 = self.rects[key]
        cy = (y0 + y1) // 2
        hover = inside(self.rects[key], *self.mouse) or self.drag == key
        cv2.rectangle(img, (x0, cy - 4), (x1, cy + 4), BTN, -1)
        kx = int(x0 + frac * (x1 - x0))
        cv2.rectangle(img, (x0, cy - 4), (kx, cy + 4), ACCENT, -1)
        cv2.circle(img, (kx, cy), 10 if hover else 8, FG, -1, cv2.LINE_AA)

    def _bar(self, img, y: int, frac: float, color, zone: tuple[float, float] | None = None):
        p, pw = self.p, self.pw
        cv2.rectangle(img, (p, y), (p + pw, y + 12), BTN, -1)
        if zone:
            cv2.rectangle(img, (p + int(zone[0] * pw), y), (p + int(zone[1] * pw), y + 12),
                          (50, 90, 50), -1)
        cv2.rectangle(img, (p, y + 3), (p + int(np.clip(frac, 0, 1) * pw), y + 9), color, -1)

    def _panel(self, img, data: FrameData | None, fps: float, frames: int, bad: int) -> None:
        p, pw, c = self.p, self.pw, self.cache
        pf = self.grabber.pixel_format
        text(img, self.title, (p, 26), 0.6, ACCENT, 1)
        size = f"{data.frame.shape[1]}x{data.frame.shape[0]}" if data is not None else "-"
        text(img, f"{fps:4.1f} fps   {size}  {pf}   bad {bad}/{frames}", (p, 56), 0.5,
             RED if bad else DIM)

        light_col = (40, 110, 40) if self.sess.light_on else (40, 40, 120)
        self._button(img, "light", f"Light: {'ON' if self.sess.light_on else 'OFF'}", light_col)
        self._button(img, "mode", f"Mode: {'STROBE' if self.sess.strobe else 'STEADY'}")

        exp = self.pending.get("exposure", c["exp"])
        text(img, "Exposure", (p, 140), 0.6, FG, 1)
        text(img, f"{exp:,.0f} us  ({exp / 1000:.2f} ms)", (p + 110, 140), 0.55, ACCENT)
        self._button(img, "exp_dn", "-")
        self._slider(img, "exposure", self._slider_frac("exposure"))
        self._button(img, "exp_up", "+")
        text(img, f"{c['exp_min']:.0f} us", (p + 42, 198), 0.4, DIM)
        text(img, f"{c['exp_max'] / 1000:.0f} ms", (p + pw - 90, 198), 0.4, DIM)

        text(img, "Gain", (p, 228), 0.6, FG, 1)
        if self.gain is not None:
            g = self.pending.get("gain", c["gain"])
            text(img, f"{g:.1f} dB", (p + 110, 228), 0.55, ACCENT)
            self._button(img, "gain_dn", "-")
            self._slider(img, "gain", self._slider_frac("gain"))
            self._button(img, "gain_up", "+")
            text(img, f"{c['gain_min']:.0f} dB", (p + 42, 286), 0.4, DIM)
            text(img, f"{c['gain_max']:.0f} dB", (p + pw - 90, 286), 0.4, DIM)
        else:
            text(img, "not available on this camera", (p + 110, 228), 0.5, DIM)

        self._button(img, "clip", f"Clip markers: {'ON' if self.show_clip else 'OFF'}")
        self._button(img, "zoom", f"Zoom: {self.zoom}x")
        self._button(img, "reset", "Reset best focus")
        self._button(img, "snap", "Save snapshot")
        self._button(img, "quit", "Quit (restore camera)", (40, 40, 110))

        if data is not None:
            ok = 100 <= data.mean <= 180
            text(img, f"Brightness  {data.mean:5.1f} / 255", (p, 468), 0.6, GREEN if ok else AMBER)
            text(img, "aim 100-180", (p + pw - 95, 468), 0.45, DIM)
            self._bar(img, 478, data.mean / 255, GREEN if ok else AMBER, (100 / 255, 180 / 255))
            text(img, f"Too bright (pure white): {data.hi:5.1f} %", (p, 522), 0.5,
                 RED if data.hi > 1 else DIM)
            text(img, f"Too dark (pure black):   {data.lo:5.1f} %", (p, 548), 0.5, DIM)
            pct = data.score / self.best * 100 if self.best > 0 else 0
            col = GREEN if pct >= 95 else AMBER if pct >= 80 else RED
            text(img, f"Focus  {data.score:8.1f}   best {self.best:8.1f}", (p, 578), 0.55, col)
            text(img, f"{pct:3.0f}%", (p + pw - 45, 578), 0.55, col)
            self._bar(img, 588, pct / 100, col)

        # Tooltip / message box
        box_y = 624
        cv2.rectangle(img, (p - 6, box_y), (p + pw + 6, self.h - 12), (48, 48, 48), -1)
        cv2.rectangle(img, (p - 6, box_y), (p + pw + 6, self.h - 12), DIM, 1)
        hovered = next((k for k, r in self.rects.items() if inside(r, *self.mouse)), None)
        if self.drag:
            hovered = self.drag
        if time.monotonic() - self.message_t < 4:
            tip, col = self.message, GREEN
        else:
            tip, col = TIPS.get(hovered or "", DEFAULT_TIP), FG
        y = box_y + 24
        for line in wrap(tip, pw - 8, 0.5):
            if y > self.h - 20:
                break
            text(img, line, (p, y), 0.5, col)
            y += 22


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
KEYS = {
    ord("q"): "quit", 27: "quit", ord("l"): "light", ord("m"): "mode", ord("c"): "clip",
    ord("z"): "zoom", ord("r"): "reset", ord("s"): "snap", ord("["): "exp_dn", ord("]"): "exp_up",
}


def window_closed() -> bool:
    try:
        return cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:  # Qt backend raises once the window has been destroyed
        return True


def run(device, args, title: str) -> None:
    sess = Session(device, args.line, args.strobe)
    nm = sess.nm
    grabber: Grabber | None = None
    try:
        sess.configure(args.fps, args.exposure, args.gain, args.throughput)
        grabber = Grabber(device, read(nm, "PixelFormat"))
        panel = Panel(sess, grabber, title, (read(nm, "Width"), read(nm, "Height")))

        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE | cv2.WINDOW_GUI_NORMAL)
        cv2.setMouseCallback(WINDOW, panel.on_mouse)

        mode = "strobing with each exposure" if sess.strobe else "held ON"
        print(f"Streaming {grabber.pixel_format}. Light on {args.line} is {mode}. "
              f"Hover over the panel for help; press q to quit.")
        device.start_stream(4)
        grabber.start()
        try:
            while True:
                panel.apply_pending()
                cv2.imshow(WINDOW, panel.render())
                key = cv2.waitKey(30) & 0xFF
                if window_closed():
                    break
                if key in KEYS:
                    panel.actions.append(KEYS[key])
                if not all([panel.handle(a) for a in panel.actions]):
                    break
                panel.actions.clear()
        finally:
            grabber.stop_event.set()
            grabber.join(timeout=3)
            device.stop_stream()
    finally:
        try:
            sess.restore()
        finally:
            exp, gain = read(nm, "ExposureTime"), read(nm, "Gain")
            print(f"\nFinal values -> ExposureTime = {exp} us, Gain = {gain} dB")
            print("(Not saved to a UserSet: a camera reboot reverts them.)")
            cv2.destroyAllWindows()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default="192.168.7.41", help="camera IP (default 192.168.7.41)")
    ap.add_argument("--line", default="Line1", help="output line wired to the light (default Line1)")
    ap.add_argument("--strobe", action="store_true",
                    help="start with the light pulsing with each exposure (ExposureActive) "
                         "instead of held on; can be switched in the window")
    ap.add_argument("--fps", type=float, default=5.0,
                    help="frame rate; lower it to allow longer exposures (default 5)")
    ap.add_argument("--throughput", type=float, default=90.0,
                    help="camera bandwidth cap in Mbit/s, 0 = no cap (default 90, suits a "
                         "100 Mb/s NIC; use --throughput 0 --fps 15 on a gigabit link)")
    ap.add_argument("--exposure", type=float, help="starting exposure in us (default: keep current)")
    ap.add_argument("--gain", type=float, help="starting gain in dB (default: keep current)")
    args = ap.parse_args()

    try:
        from arena_api.system import system
    except BaseException as e:  # noqa: BLE001 -- arena_api raises non-ImportError
        sys.exit(f"arena_api not available: {e!r}")

    # Ctrl+C already raises KeyboardInterrupt; make `kill` unwind cleanly too.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    infos = system.device_infos
    matches = [d for d in infos if d.get("ip") == args.ip]
    if not matches:
        sys.exit(f"No camera at {args.ip}. Found: {[d.get('ip') for d in infos]}")
    info = matches[0]
    title = f"{info.get('model')}  {args.ip}"
    print(f"Opening {info.get('model')} s/n {info.get('serial')} at {args.ip}")

    try:
        device = system.create_device(device_infos=[info])[0]
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Could not open camera ({e}). Is ArenaView / the osm backend / "
                 f"another script using it?")
    try:
        run(device, args, title)
    except KeyboardInterrupt:
        pass
    finally:
        system.destroy_device(device)
        print("Camera released.")


if __name__ == "__main__":
    main()
