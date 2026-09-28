# s2 part off-centre / wandering in the camera FOV

- **Date seen:** 2026-09-28
- **Area:** Indexer / dispatcher (inspection-station firing)
- **Severity:** Medium: defect inspection needs the part centred; off-centre parts plus reflections hurt detection
- **Status:** Fixed and verified on the machine (2026-09-28): parts land centred in the FOV
- **Fix commit(s):** see the commit that adds this report

## Summary
Inspection stations fired their cameras when the station's slot index
changed, noticed on the next 50 ms tick. Parts sit anywhere inside their
64-pulse slot, so the capture moment relative to the *part* varied by up to
one slot (~21 mm) plus one tick (~10 mm at 7.6 rpm, ~33 mm at 25 rpm). The
reject station didn't have this problem, because it fires from the part's own
detection pulse (spec12).

## Symptom
`.claude/temp_images/s2_offset.png`: the cam2 image shows the part left of
centre. Across parts it lands at different positions in the FOV.

## Diagnosis
- `_tick_real` step 3 ("identical slot-changed trigger as _tick_sim") fired
  inspection stations on `slot_ids` changes only.
- Slot = encoder_cpr / n_slots = 4800 / 75 = 64 pulses, and
  π × 500 mm / 4800 ≈ 0.33 mm/pulse, so ~21 mm per slot.
- Tick = 50 ms. At the measured 7.6 rpm that's ~30 pulses per tick; at 25 rpm,
  ~100.
- The encoder itself was healthy by then (PULSE DEBUG panel: RAW wrapping at
  4800, 0 backward steps), so the scatter was purely the trigger logic.

## Root cause
Inspection firing was slot-quantized and tick-quantized by design (spec12
changed only the reject path to be pulse-precise and left inspection as
"do not touch").

## Actions taken
spec16 (`docs/specs/spec16_pulse_precise_inspection_trigger.md`), real-PLC mode:
- Every `type: inspection` station fires at the part's own target pulse:
  `detection − entry_sensor_mid_offset − entry delay + station_offset_pulses − trigger_latency_ms`
  (the same corrected-detection term as the reject target).
- If the target falls before the next tick, a one-shot timer fires at
  `(target − now) / pulses_per_ms`, so timing isn't bound to the 50 ms tick.
- Each part fires exactly once per station. Up to half a slot late: fire and
  warn. Further: don't image the wrong part; record NOK with an error log.
- New optional `trigger_latency_ms` per inspection station (default 0).
- Sim mode and parts without a detection pulse keep the slot-change trigger.
- Each fire logs `target_pulse`, `est_pulse` and the error, for calibration.

## Prevention
- 7 tests in `tests/test_dispatcher_real_mode.py` cover:
  - sub-tick timer delay;
  - once-only firing;
  - firing on the crossing tick when the speed is unknown;
  - a miss recorded as NOK;
  - skipping a slot that changed occupant;
  - target math including mid-offset and latency;
  - `stop()` cancelling timers.

## Follow-ups
- Verified 2026-09-28: s2 parts centred with `station_offset_pulses: 1595`.
  Re-centre after any camera move with Δ pulses ≈ offset_mm / 0.327 (spec16).
  The meaning is documented at the stations in `machine_config.yaml`.
- Measure `trigger_latency_ms` (software trigger + GigE) if centring drifts
  with speed.
- Fix the inverted part sensor: detection currently happens at the trailing
  edge, which depends on part length.
- Reflections in the s2 image are a lighting issue (angle, diffuser,
  polariser), separate from this.
- For < 1 mm at 900 PPM: a hardware trigger (PLC output -> camera Line0).
