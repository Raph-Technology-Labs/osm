# Slow session start: 9 s GigE discovery per camera

- **Date seen:** 2026-09-24
- **Area:** Camera / session start (`LucidCamera.connect`)
- **Severity:** Medium: session start took ~20 s; nothing ran wrong
- **Status:** Fixed
- **Fix commit(s):** see the commit that adds this report

## Summary
Every camera connect ran a full GigE discovery scan
(`system.device_infos`), and each scan took **9.2 s** on this PC. With two real
cameras, "Create session" spent about 18 s just finding cameras. It now takes
about 1 s for both.

## Symptom
"Create session" in the UI took a long time (~20 s) before the inspection
page opened.

## Diagnosis
The backend logs to the terminal only, so each session-start step was timed
separately. None of these runs open a camera.

| Step | Time |
|---|---|
| import torch/ultralytics | 0.79 s |
| load + warm-up `osm.pt` (`_prewarm_models`) | 1.37 s |
| import `arena_api` | 0.24 s |
| **`system.device_infos` (each call)** | **9.2 s** |

Then:
- `system.DEVICE_INFOS_TIMEOUT_MILLISEC` reads **1000** in this arena_api
  build, although its own docstring says the default is 100.
- `system.interface_infos` lists **9 interfaces**: `enp4s0`, `enp3s0`, Wi-Fi,
  `tailscale0` and 5 Docker bridges. Discovery waits the full timeout on each
  one in turn: 9 × ~1 s ≈ 9.2 s.
- At 100 ms the scan took **0.95 s** and still found both cameras (Lucid
  cameras answer discovery within 100 ms).
- `LucidCamera.connect()` scanned once per camera (and a second time if the
  camera wasn't found), so session start cost ~18 s for s1 + s2.

## Root cause
Three things multiplied together:
1. an SDK default timeout 10× longer than documented;
2. discovery broadcasting on every host interface, including non-camera ones
   (VPN, Wi-Fi, Docker);
3. a fresh scan for every camera instead of one shared scan.

## Actions taken
- `app/camera/lucid_camera.py` has a new `discover_device()`:
  - scans with a **100 ms** timeout first;
  - **caches the scan for 5 s**, so cameras connected back-to-back in one
    session start share it (camera 2 costs 0 s);
  - falls back to **one slow scan (1000 ms)** only if the wanted camera isn't
    in the fast result, so a slow-answering or just-powered-up camera is still
    found;
  - logs each scan's duration and the IPs found.
- `scripts/focus_live.py` uses the same fast-then-slow scan (startup ~1 s
  instead of ~9 s).
- Measured on the real network after the fix: both cameras found in 0.94 s
  total.

## Prevention
- `tests/test_lucid_discovery.py` (6 tests, fake arena system):
  - one fast scan when the camera is present;
  - the second camera reuses the scan;
  - a stale cache rescans;
  - a late-answering camera is found by the slow fallback;
  - a missing camera returns `None` with everything that was seen;
  - a cached scan that doesn't contain the camera isn't trusted.
- The `GigE discovery (...) took Xs` INFO log line makes any regression visible
  in the backend log.

## Follow-ups
- Optional: stop Docker bridges or Tailscale on the production PC, or move
  them off, to shorten discovery further (each interface still costs ~0.1 s).
- Optional: write backend logs to a rotating file (e.g. `backend/logs/`) so
  session-start timing can be checked after the fact instead of only in the
  live terminal.
