# Station 2 config review before first run

- **Date seen:** 2026-09-24
- **Area:** Config / pipeline / camera driver
- **Severity:** Medium: station 2 would have run but given wrong results
- **Status:** Fixed
- **Fix commit(s):** `781659b`

## Summary
Enabling station 2 (it had been commented out) for the real camera turned up
four problems that would have let it run but inspect wrongly. They were caught
by reviewing the config and driver before the first session, not by a failure.

## Findings, causes and actions

| # | Finding | Why it mattered | Action |
|---|---|---|---|
| 1 | `conf_thresh: 1` in s2's defect pipeline | YOLO keeps a detection only if confidence ≥ threshold. At 1.0 it drops every detection, so every part passes. | Changed to `0.5` (by the engineer). |
| 2 | s2 camera IP was a placeholder (`192.168.5.42`) with `sim.enabled: true` | Station 2 would have inspected stored images, not the real camera, and the strobe would never have fired. | Set to the real camera `192.168.7.41`, `sim.enabled: false`. |
| 3 | Driver forced `Mono8` on every camera; 7.41 is a colour TRI023S-C | It was fine for the mono-trained model, but there was no way to switch to colour, and no error if colour was expected on a mono camera. | Added `color: false/true` (default false = mono). `true` debayers to BGR and fails on a mono sensor. |
| 4 | Exposure and gain weren't in the config | The camera kept whatever an earlier tool (ArenaView, `focus_live`) had left, and a camera reboot reset it. With the strobe on, exposure is also the flash length. | Added `exposure_us` / `gain_db`, applied with auto off. Out-of-range values fail `connect()`. cam2 = 3300 µs / 3.4 dB. |

## How it was diagnosed
Read `machine_config.yaml` s2 block, `LucidCamera._configure`, and
`app/pipeline/defect.py` (where `conf_thresh` is passed to `predict(conf=...)`).

## Prevention
- Unit tests for colour/pixel-format selection, Bayer conversion, and
  exposure/gain in `tests/test_lucid_strobe.py`.
- **Checklist before enabling a station:** real IP, `sim.enabled: false`,
  `conf_thresh` between 0 and 1 (typically 0.25-0.5), exposure/gain set,
  model path exists.

## Follow-ups
- Consider a config validator rule: `conf_thresh` must be less than 1.0.
