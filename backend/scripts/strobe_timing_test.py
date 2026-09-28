"""Strobe timing test: is the light actually ON during the exposure?

With the camera-driven strobe (LineSource = ExposureActive) the camera drives
its output line exactly for the exposure time. If the light arrives late, the
cause is between that line and the light: inverted polarity (the controller
fires on the END-of-exposure edge), a delay or fixed pulse width set in the
light controller, or a slow light.

This takes software-triggered frames at a range of exposure times, with the
strobe line normal and inverted, plus a lights-off baseline, and prints the
mean brightness of each. Reading the table:

  * normal column bright even at short exposures  -> timing is fine.
  * inverted bright, normal dark                  -> polarity: set
                                                     strobe.inverted: true.
  * both dark at short exposures, bright only from
    exposure X upward                             -> the light arrives ~X
    after the exposure starts (controller delay / rise time): remove the
    controller's delay, or use an exposure longer than X.
  * nothing ever brighter than the baseline       -> the light isn't firing
    at all (wiring / controller mode).

Point the camera at a static, light-coloured target. Nothing else may hold
the camera: stop the osm backend first. All touched settings are restored.

Usage (from backend/scripts):
    python strobe_timing_test.py                      # 192.168.7.41, Line1
    python strobe_timing_test.py --exposures 200 500 1000 1500 3000 6000 12000
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cv2  # noqa: E402

from focus_live import BAYER_CODES, buffer_to_image, node, read, write  # noqa: E402

SAVED = [
    "PixelFormat", "TriggerSelector", "TriggerMode", "TriggerSource",
    "AcquisitionFrameRateEnable", "AcquisitionFrameRate",
    "ExposureAuto", "ExposureTime",
]
LINE_SAVED = ["LineMode", "LineSource", "LineInverter"]


def capture_mean(device, pixel_format: str, frames: int, exposure_us: float) -> float:
    nm = device.nodemap
    total = 0.0
    for _ in range(frames):
        deadline = time.monotonic() + 1.0
        while not node(nm, "TriggerArmed").value:
            if time.monotonic() > deadline:
                raise RuntimeError("camera never armed for a trigger")
            time.sleep(0.001)
        node(nm, "TriggerSoftware").execute()
        buf = device.get_buffer(timeout=int(exposure_us / 1000) + 2000)
        try:
            img = buffer_to_image(buf, pixel_format)
        finally:
            device.requeue_buffer(buf)
        total += float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean())
    return total / frames


def run(device, args) -> None:
    nm = device.nodemap
    saved = {n: read(nm, n) for n in SAVED}
    write(nm, "LineSelector", args.line, quiet=True)
    line_saved = {n: read(nm, n) for n in LINE_SAVED}
    try:
        entries = node(nm, "PixelFormat").enumentry_names
        fmt = "Mono8" if "Mono8" in entries else next(f for f in BAYER_CODES if f in entries)
        write(nm, "PixelFormat", fmt)
        write(nm, "TriggerSelector", "FrameStart", quiet=True)
        write(nm, "TriggerMode", "Off")
        write(nm, "TriggerSource", "Software")
        write(nm, "TriggerMode", "On")
        # Low frame rate so long exposures fit (exposure <= frame period).
        write(nm, "AcquisitionFrameRateEnable", True)
        write(nm, "AcquisitionFrameRate", 5.0)
        write(nm, "ExposureAuto", "Off")
        tl = device.tl_stream_nodemap
        tl["StreamBufferHandlingMode"].value = "NewestOnly"
        tl["StreamAutoNegotiatePacketSize"].value = True
        tl["StreamPacketResendEnable"].value = True

        write(nm, "LineSelector", args.line, quiet=True)
        write(nm, "LineMode", "Output", quiet=True)
        sources = node(nm, "LineSource").enumentry_names
        device.start_stream(4)
        try:
            # Baseline: light never fires, longest exposure = ambient only.
            write(nm, "LineSource", "Off" if "Off" in sources else "UserOutput0")
            write(nm, "ExposureTime", float(max(args.exposures)))
            baseline = capture_mean(device, fmt, args.frames, max(args.exposures))

            write(nm, "LineSource", "ExposureActive")
            rows = []
            for exp in args.exposures:
                write(nm, "ExposureTime", float(exp))
                actual = read(nm, "ExposureTime")
                means = []
                for inverted in (False, True):
                    write(nm, "LineInverter", inverted)
                    means.append(capture_mean(device, fmt, args.frames, exp))
                rows.append((actual, *means))
        finally:
            device.stop_stream()
    finally:
        print("\nRestoring camera settings...")
        write(nm, "LineSelector", args.line, quiet=True)
        for n in ("LineSource", "LineInverter", "LineMode"):
            if line_saved.get(n) is not None:
                write(nm, n, line_saved[n], quiet=True)
        write(nm, "TriggerMode", "Off", quiet=True)
        for n in SAVED:
            if saved.get(n) is not None:
                write(nm, n, saved[n], quiet=True)

    print(f"\nStrobe on {args.line}, {args.frames} frame(s) per point, {fmt}")
    print(f"Baseline (light OFF, {max(args.exposures)} us): mean brightness {baseline:6.1f}\n")
    print(f"{'exposure us':>12}  {'normal':>8}  {'inverted':>9}")
    for exp, normal, inv in rows:
        mark = lambda v: "*" if v > baseline + args.margin else " "  # noqa: E731
        print(f"{exp:12.0f}  {normal:8.1f}{mark(normal)}  {inv:8.1f}{mark(inv)}")
    print(f"\n* = brighter than the lights-off baseline by more than {args.margin}")

    lit = lambda col: [r[0] for r in rows if r[col] > baseline + args.margin]  # noqa: E731
    normal_lit, inv_lit = lit(1), lit(2)
    shortest = min(args.exposures)
    print("\nREADING IT")
    top = max(max(r[1], r[2]) for r in rows)
    if baseline >= top - args.margin and baseline > 2 * args.margin:
        print("  - Lights-OFF baseline is as bright as with the strobe: the light doesn't follow "
              "Line1 -- the controller is in continuous (constant-on) mode or not wired to the "
              "camera output. Put the controller in trigger/strobe mode.")
    elif not normal_lit and not inv_lit:
        print("  - The light never shows up in the image: it isn't firing (wiring, controller "
              "mode/power) or the target is too dark.")
    elif inv_lit and (not normal_lit or min(inv_lit) < min(normal_lit)):
        print("  - Brighter INVERTED: the controller fires on the opposite edge -> set "
              "strobe: { inverted: true } for this camera (or change the controller's edge).")
    elif normal_lit and min(normal_lit) <= shortest * 1.01:
        print("  - Light is on during even the shortest exposure: strobe timing is fine.")
    else:
        print(f"  - Light only appears from ~{min(normal_lit):.0f} us exposure: it arrives about "
              "that late. Check the light controller for a trigger delay / fixed pulse width, or "
              "use an exposure longer than that.")
    if saved.get("ExposureTime") is not None:
        print(f"\n(Exposure restored to {saved['ExposureTime']:.0f} us.)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default="192.168.7.41")
    ap.add_argument("--line", default="Line1")
    ap.add_argument("--exposures", type=float, nargs="+",
                    default=[100, 300, 700, 1500, 3000, 6000, 12000, 25000])
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--margin", type=float, default=5.0,
                    help="brightness above baseline that counts as 'lit' (default 5)")
    args = ap.parse_args()

    try:
        from arena_api.system import system
    except BaseException as e:  # noqa: BLE001
        sys.exit(f"arena_api not available: {e!r}")

    matches = []
    for timeout_ms in (100, 1000):
        system.DEVICE_INFOS_TIMEOUT_MILLISEC = timeout_ms
        matches = [d for d in system.device_infos if d.get("ip") == args.ip]
        if matches:
            break
    if not matches:
        sys.exit(f"No camera at {args.ip}")
    try:
        device = system.create_device(device_infos=[matches[0]])[0]
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Could not open camera ({e}). Stop the osm backend / ArenaView first.")
    try:
        run(device, args)
    finally:
        system.destroy_device(device)
        print("Camera released.")


if __name__ == "__main__":
    main()
