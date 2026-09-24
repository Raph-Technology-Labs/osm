# focus_live lens-setup tool issues

- **Date seen:** 2026-09-24
- **Area:** Tooling (`backend/scripts/focus_live.py`)
- **Severity:** Low: engineering tool only, never in the inspection path
- **Status:** Fixed
- **Fix commit(s):** `781659b` (the tool's first commit includes all fixes)

## Summary
The first versions of the lens-setup tool (live view + light on Line1, for
setting aperture and focus) had several usability problems and one crash.
All were fixed before the tool was committed.

## Issues

| # | Symptom | Diagnosis / root cause | Action |
|---|---|---|---|
| 1 | Image looked almost black with large **blue** areas | The overlay text said brightness 4.5/255 and 35% of pixels at 0. The blue was the tool's clipping overlay (pure black painted blue), not real colour. The real problem was too little light reaching the sensor (light not on / exposure 2 ms). Which of the two it was wasn't confirmed; the next run was bright. | Clipping overlay off by default, labelled as marker colours, with an explanation in its hover help. |
| 2 | Crash on closing the window with the X button: `cv2.error ... NULL guiReceiver (please create a window) in function 'cvGetPropVisible_QT'` | OpenCV's Qt backend raises, instead of returning "not visible", once the window is destroyed. Camera settings had still been restored and the camera released. | Window-closed check wrapped in `try/except cv2.error`. |
| 3 | Sliders had no names, and toolbar icons didn't explain themselves | OpenCV's Qt trackbars and toolbar can't carry labels or tooltips. | Replaced with a drawn control panel: named Exposure/Gain sliders with -/+, labelled buttons, and hover help for every control and readout. |
| 4 | `QFontDatabase: Cannot find font directory .../cv2/qt/fonts` warnings | The opencv-python wheel's bundled Qt has no fonts. | Set `QT_QPA_FONTDIR` to the system DejaVu fonts before importing cv2. |
| 5 | About 4.5 fps and incomplete frames on 7.41 | 100 Mbit link, see [cam2-100mbit-link](2026-09-24-cam2-100mbit-link.md). | `--throughput` cap (default 90 Mbit/s) and `--fps` (default 5); both restored on exit. |
| 6 | Light controller may only react to pulses | A steady-on output does nothing on an edge-triggered or overdrive controller. | `--strobe` / Mode button: pulses Line1 with each exposure, the same as production. |

## Prevention
- Hardware tools restore every setting they change on exit, including on a
  crash, Ctrl+C or closing the window. `focus_live` restores line, trigger,
  frame rate, bandwidth and pixel format. Exposure and gain are deliberately
  kept and printed.
- Tested offline by rendering the panel against a fake nodemap before
  handing it over.
