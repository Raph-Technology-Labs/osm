# PLC-register strobe (sb-devNtest) not merged

- **Date seen:** 2026-09-24 (review of `origin/sb-devNtest`, commit `4923dbc`)
- **Area:** Camera / strobe (`app/camera/station_registry.py`, `scripts/standalone_strob.py`)
- **Severity:** Medium: would have broken every real-camera capture if merged
- **Status:** Not merged. Replaced by the camera-driven strobe.
- **Fix commit(s):** `781659b` (camera-driven strobe)

## Summary
The strobe code on `sb-devNtest` turns the light on and off by writing a PLC
Modbus register around each capture. Review found it would raise on every
real capture, doesn't match how station 2's light is wired, and can't be
synchronised with the exposure. It wasn't merged. Station 2 uses the camera's
own output line instead.

## Findings
1. **Crash on every real capture.** `fire_strobe(self, strobe_reg)` is a
   module-level function with a stray `self` parameter, called as
   `fire_strobe(camera_config.strobe_reg)`, which is one argument short. That
   raises `TypeError` before `driver.read_frame()`, so every real-camera frame
   would fail.
2. **Not used as a context manager.** Even with the arguments fixed, it's a
   `@contextmanager` called without `with`, so the strobe code would never run.
3. **Wrong wiring for station 2.** Station 2's light controller is wired to
   the camera's Line1, not to the PLC.
4. **Not synchronised to the exposure.** The camera free-runs, and
   `read_frame()` returns the newest frame, which was usually exposed *before*
   the Modbus write reached the PLC. Timing depends on network and PLC scan
   jitter.
5. **Hot-path cost.** Two Modbus writes per frame work against the 900 PPM
   throughput rule (CLAUDE.md §5).
6. Minor: unused `contextmanager` import added to `inspection_session.py`, and
   the trailing newline removed from `station_registry.py`.

## Diagnosis
`git diff 8751a18 origin/sb-devNtest -- backend/`, read against the
`LucidCamera` capture path, and the station 2 wiring confirmed with
`scripts/focus_live.py` (Line1 drives the light).

## Action taken
Implemented a camera-driven strobe instead: `CameraConfig.strobe`
(`enabled`, `line`, `inverted`). With it enabled, `LucidCamera` sets
`LineSource = ExposureActive`, so the camera pulses the light for exactly the
exposure time of every frame. The camera does the timing, with no per-frame
Modbus traffic. Station 1 stays off until its wiring is done.

## Prevention
- Branches that touch the capture path should run the test suite before being
  proposed for merge. A unit test calling `real_frame_provider` with a fake
  driver would have caught finding 1 immediately.
- The PLC-register approach (`strobe_reg` / `strobe_capture_delay_ms` in the
  config) is still available for a station whose light really is PLC-wired.
  It would need triggered capture (see `docs/specs/spec15_multi_light_capture.md`,
  Phase 1) to be synchronised.

## Follow-ups
- Share this report with the branch author.
