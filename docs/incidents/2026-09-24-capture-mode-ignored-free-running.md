# Cameras free-running although config said `capture_mode: single_shot`

- **Date seen:** 2026-09-24
- **Area:** Camera driver (`app/camera/lucid_camera.py`)
- **Severity:** Medium: stale images and constant load; no crash
- **Status:** Fixed in code. Hardware test pending.
- **Fix commit(s):** see the commit that adds this report

## Summary
`CameraConfig.capture_mode` accepted `single_shot` | `continuous`, and every
camera was configured `single_shot`, but no code read the setting. The Lucid
driver always free-ran at `fps` and `read_frame()` took the newest buffered
frame. Cameras streamed all session, the strobe flashed at the frame rate,
and each station fire got a frame taken up to one frame period *before* the
fire.

## Symptom
- Question raised during station 2 bring-up: "why is the camera streaming all
  the time? It should only capture when the part is under the station."
- Consequences:
  - frame age up to ~33 ms (30 fps) plus transfer at the moment of the fire;
  - ~500 Mbit/s per camera (1920x1080 Mono8 @ 30 fps) for the whole session,
    on the switch shared with the PLC;
  - with the strobe on Line1 (`ExposureActive`), 30 flashes/s continuously,
    wearing the light and heating it for nothing.

## Diagnosis
`grep -rn capture_mode app/`: the only hit was the field's definition in
`config_loader.py`. `LucidCamera._configure()` never touched `TriggerMode`,
and `read_frame()` was a plain `get_buffer()`. The driver's pattern came from
gcm (a continuously streaming single-camera app), where free-run is correct.

## Root cause
A config field with no implementation behind it, carried over from the
schema design ("single_shot" was the intent) while the driver copied gcm's
free-run behaviour. There was no test that `capture_mode` changed anything,
so the gap was invisible.

## Actions taken
`LucidCamera` now applies `capture_mode` at connect (`_configure_trigger`):
- **single_shot:** `TriggerSelector=FrameStart`, `TriggerSource=Software`,
  `TriggerMode=On`. Each `read_frame()`:
  1. drains any leftover buffer (a late frame from an earlier timed-out
     trigger), so it can never be returned as this part's image;
  2. waits for `TriggerArmed` (up to 0.5 s, otherwise a clear
     `CameraConnectionError`);
  3. executes `TriggerSoftware`;
  4. collects that one frame.
  A per-camera lock keeps overlapping station fires from collecting each
  other's frames. The strobe now flashes once per part.
- **continuous:** the old behaviour, with `TriggerMode=Off` set explicitly, so a
  camera left in trigger mode by another tool can't hang the session.
- `fps` still caps the trigger rate and the max exposure in single_shot.

## Prevention
- `tests/test_lucid_capture_mode.py` (8 tests, fake arena device): trigger
  setup per mode, one frame per read, stale-frame drain, TriggerArmed wait
  and timeout, concurrent reads each get their own frame, no trigger in
  continuous mode.
- Review rule: a config field must have a test proving it changes behaviour,
  or a `NOT WIRED YET` comment (as `strobe_reg` has).

## Follow-ups
- Hardware test on cam2 (`sim.enabled: false`). The log should show
  `cam2: triggered capture (software trigger, 1 frame per read)`, and the light
  should flash once per station fire.
- Capture position still depends on the dispatcher tick (50 ms, up to ~100
  counts at 25 rpm). For exact positioning at 900 PPM: a PLC output ->
  camera Line0 hardware trigger (`TriggerSource=Line0`), see
  `docs/specs/spec15_multi_light_capture.md`.
