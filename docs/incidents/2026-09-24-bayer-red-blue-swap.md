# Colour camera: red shown as blue

- **Date seen:** 2026-09-24
- **Area:** Camera / imaging (`scripts/focus_live.py`, then `LucidCamera.to_bgr`)
- **Severity:** Medium: wrong colours in any colour pipeline
- **Status:** Fixed
- **Fix commit(s):** `781659b`

## Summary
Live video from the colour TRI023S-C (7.41) showed red objects as blue. The
Bayer-to-BGR conversion used the OpenCV code with the *same name* as the
camera's pixel format, but OpenCV names Bayer patterns differently, so red and
blue were swapped.

## Symptom
A red mark on the part appeared blue/purple in `focus_live.py`.

## Diagnosis
- The camera streams `BayerRG8` (GenICam: the pattern starts R G / G B).
- The code used `cv2.COLOR_BayerRG2BGR`. OpenCV names its Bayer codes from the
  2nd row / 2nd column of the pattern, so GenICam `BayerRG` is OpenCV
  `BayerBG`.
- Confirmed with a synthetic test: an 8x8 frame with only the R sites lit
  (the RGGB layout of a pure-red scene). `COLOR_BayerBG2BGR` gives
  B,G,R = 0,0,200 (red). The same-named code gives blue.

## Root cause
The known OpenCV/GenICam naming mismatch. It wasn't caught because nothing
checked colour correctness; the first colour camera on the machine found it.

## Actions taken
- Correct mapping in both places: `BayerRG8 -> COLOR_BayerBG2BGR`,
  `BayerGB8 -> COLOR_BayerGR2BGR`, `BayerGR8 -> COLOR_BayerGB2BGR`,
  `BayerBG8 -> COLOR_BayerRG2BGR`, with a comment explaining why.
- The osm driver (`LucidCamera`) only uses colour when `color: true`. The
  default stays mono, because the models are trained on mono images.

## Prevention
- `tests/test_lucid_strobe.py::test_to_bgr_color_keeps_red_red` uses the
  pure-red RGGB frame, so a wrong mapping fails CI.
- `luciddesk` (separate repo) uses the same correct mapping.
