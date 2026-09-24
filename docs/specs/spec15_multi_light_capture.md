# Spec: Multi-light capture (one camera, one image per light)

Status: **PLAN -- not implemented.** Written 2026-09-24 as the follow-up to
the camera-driven strobe (`CameraConfig.strobe`, `LucidCamera._configure_strobe`).

## 1. Problem Statement

Some inspections need the same part imaged under different lighting (for
example a top/ring light for surface defects and a back light for the outline)
from **one** camera at **one** station. Today a camera has at most one strobe
line, and each dispatcher trigger produces exactly one frame. We need: trigger
comes in -> image 1 with the light on Line1 -> image 2 with the light on Line2
-> (optional more) -> every image goes through its own pipeline -> one
station verdict for the part.

A second, related problem: `capture_mode: single_shot` exists in the config
but nothing uses it. The Lucid driver free-runs at `fps` and `read_frame()`
returns the newest frame, so a frame may be exposed up to one frame period
(~33 ms at 30 fps), plus transfer time, **before** the trigger. Switching
lights per image only works with triggered capture, so fixing this comes first
(Phase 1) and also helps the single-light stations.

## 2. Functional Requirements

- A camera can list N lights (N >= 1). Each light has an id, the camera
  output line that fires it, and optionally its own exposure and gain.
- One capture trigger for the station captures N images in the configured
  order, one per light, with **only** that light firing during its exposure.
- Each image is traceable to its light, and can be routed to a different
  pipeline (for example the defect model on the top-light image, the
  measurement caliper on the back-light image).
- The station verdict combines all images under the existing `pass_if` rule.
- The live view shows every image (one tile per camera+light).
- A single-light camera (today's `strobe:` config) keeps working unchanged.
- Station 1 (strobe wiring pending) and station 2 (Line1 strobe) are unaffected
  until they opt in.

## 3. API / Interface Contract

**Config (proposed):**

```yaml
cameras:
  cam2:
    ip: "192.168.7.41"
    capture_mode: single_shot        # required for lights: (triggered capture)
    exposure_us: 3300                # default for lights that don't override
    gain_db: 3.4
    lights:                          # replaces strobe: when more than one light
      - { id: top,  line: Line1 }                          # uses camera exposure/gain
      - { id: back, line: Line2, exposure_us: 800, gain_db: 0, inverted: false }
pipeline:
  defect:
    allowed_cameras: ["cam2:top"]    # camera:light = one virtual camera per light
  measurement:
    allowed_cameras: ["cam2:back"]
```

Using `camera:light` ids means the existing per-camera plumbing (pipeline
routing, `pass_if: all_cameras_pass`, `CameraResult.camera_id`, ZMQ topic,
live grid tile) works per light without a new axis anywhere downstream.
A validator rejects `strobe.enabled` and `lights` on the same camera, duplicate
lines, and pipeline references to unknown `camera:light` ids.

**Driver contract:** `CameraDriver.read_frames() -> list[tuple[str | None, ndarray]]`.
The base class default returns `[(None, self.read_frame())]`, so sim cameras
and single-light cameras don't change.

| Aspect | Description |
|---|---|
| Input | One capture trigger from the dispatcher (unchanged) |
| Output | N `(light_id, BGR frame)` pairs -> N pipeline results -> 1 station verdict |
| PLC registers | None. Lights are driven by camera output lines, not Modbus |

## 4. Constraints

- **Time budget.** 900 PPM = **66.7 ms per part** per station. Each image
  costs exposure + sensor readout/transfer + line-switch writes:
  - Transfer of 1920x1080 Mono8 (2.07 MB): about 18 ms at 1 Gb/s, **about 180 ms
    at 100 Mb/s**. enp4s0 currently links at 100 Mb/s, so it must link at 1 Gb/s
    before this is possible at all.
  - The TRI023S's maximum frame rate at full resolution sets a floor of about
    24 ms between images.
  - Two lights at full resolution: about 50 ms. That fits in 66.7 ms, but only
    just. A smaller ROI or binning buys headroom. Measure it (Phase 2 exit
    criterion); don't assume.
- **Part motion between images.** The disc keeps moving, so image 2 is shifted
  by `disc_surface_speed x time_between_images`. Pipelines must not assume
  pixel alignment between lights, and each image needs its own motion-blur
  check (`exposure <= mm_per_px / speed`).
- **Line electrical limits.** On Triton, Line1 is the opto-isolated output.
  Line2/Line3 are non-isolated GPIO with different voltage and current
  limits. Check the camera datasheet against the second light controller's
  trigger input before wiring it. Outputs go to the controller's trigger
  input, never to the light directly.
- **Hot path.** No Modbus on the capture path (CLAUDE.md Throughput
  Requirements). Nodemap writes per image are GigE control-channel round
  trips of about 1-3 ms each, with jitter. Keep them to the minimum (see §7
  options).

## 5. Edge Cases & Error Handling

| Edge case | How to handle |
|---|---|
| PLC ACK never arrives | Not applicable: no PLC register is involved in capture or lighting. |
| One image of the sequence times out | Whole part = NOK (never judge on a partial set). Log which light. Reset all lines to Off before the next trigger so the sequence re-syncs. |
| App crashes mid-sequence with a light line left on | At `connect()` and `close()`, set every configured light line's LineSource to Off. A steady-on overdrive strobe can overheat. |
| Light not wired or dead (line fires, nothing lights) | Software can't sense it directly. Session-start self-test: capture each light once with the part area empty, and fail the station if a light's mean brightness isn't clearly above the lights-off frame (same idea as LucidDesk's strobe verify). |
| Next trigger arrives while the previous sequence is still running | Count it as a missed capture (existing dispatcher overrun handling). Never queue: capturing late means capturing the wrong part. |
| Exposure for one light is outside the camera's range at this fps | Fail at `connect()`, same as `exposure_us` today. |
| Camera does not have the configured line (for example Line3 on a model without it) | Fail at `connect()` with the list of lines the camera does have. |
| Single light configured via `lights:` | Allowed. Behaves like `strobe:` but triggered. |

## 6. Acceptance Criteria

The feature is considered complete if:

- [ ] Phase 1: `capture_mode: single_shot` really triggers. Frame timestamp minus trigger time is within exposure + transfer, measured on 7.41.
- [ ] A 2-light camera returns 2 frames per trigger, and each frame is visibly lit only by its own light (checked with lights covered one at a time).
- [ ] Per-light pipelines run and the station verdict follows `pass_if` across both.
- [ ] Measured end-to-end sequence time per part is logged, and is under the station's budget at the configured speed.
- [ ] Crash and restart leaves no light line stuck on.
- [ ] Existing single-light (`strobe:`) and sim configs pass their tests unchanged.
- [ ] Unit tests against a fake nodemap for the line-switch sequence, timeout, and reset-to-Off paths.

---

## 7. Implementation options (input to the Technical Design Plan)

**A. Host-switched lines + software trigger (recommended first).**
For each light: set its line to `ExposureActive`, set the other light lines to
`Off`, set exposure/gain if they differ, `TriggerSoftware.execute()`, then
`get_buffer()`. This is simple, deterministic (the frame-to-light mapping is
exact), and works with the planned wiring (light A on Line1, light B on Line2).
The cost is about 2-4 nodemap writes per image on the hot path. Build this
first and measure it.

**B. Camera sequencer (hardware, zero per-image writes).**
Lucid cameras have a Sequencer that steps through feature sets on each
trigger. Whether a set can carry the output-line source, or only
exposure/gain/ROI, has to be checked on the real camera: list
`SequencerFeatureSelector` entries on 7.41 (read-only, for example in
ArenaView). If it can, this is the fastest option. If it only carries
exposure/gain, combine it with C.

**C. Light-controller sequencing.**
Both light channels' trigger inputs are fed from Line1 (`ExposureActive`), and
a multi-channel strobe controller in sequence mode alternates channels on each
pulse. The software cost is zero, but the controller has to support it, and
the sequence has to be re-synced (so image 1 is always light A) at session
start and after any missed pulse.

### Phases

1. **Triggered capture** (`capture_mode: single_shot` -> `TriggerMode On`,
   `TriggerSource Software`, `read_frame()` = trigger + `get_buffer`). Useful
   on its own for today's single-light stations.
2. **`lights:` config + `read_frames()` + option A**, with `camera:light`
   routing through pipelines, results, ZMQ and the live grid.
3. **Timing measurement on real hardware**. If the budget is tight, evaluate
   options B and C.
4. **Session-start light self-test**.

### Open questions (need answers before the Technical Design Plan)

- Which station(s) and lights, and which light is on which line? Is Line2 electrically compatible with the second controller?
- Does each light need its own exposure/gain?
- Which pipeline/model runs on which light's image?
- Target speed (PPM) for the station that uses multi-light, to size the timing budget.
- Will enp4s0 be fixed to link at 1 Gb/s? (Required, see §4.)
