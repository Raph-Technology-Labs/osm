# Spec: Precise part detection at the entry sensor (FUTURE)

Status: **PLANNED, not started.** Written 2026-09-28 after the first attempt
was reverted in config. See `docs/incidents/2026-09-28-part-sensor-inverted.md`.

## 1. Problem Statement

Every station's timing (spec12 reject targets, spec16 capture targets, home
calibration) starts from the part's **detection pulse** at the entry sensor.
Two things make that pulse imprecise today:

1. **Inverted sensor.** The sensor is active-low (1 = no part, 0 = part).
   With `plc.part_sensor_active_low: false` (current), osm detects the part
   on the **trailing edge** (part leaving the sensor). That's one part length
   late, and the delay depends on each part's length. Offsets are calibrated
   around it (s1 267, s2 1595), which works but hides the error.
2. **Poll quantization.** The sensor is read every 50 ms dispatcher tick, so
   an edge is only seen at the next poll: up to one tick of disc travel late
   (~30 pulses at 7.6 rpm, ~100 pulses ≈ 33 mm at 25 rpm), and the lateness
   is random per part.

The 2026-09-28 attempt (flag true, detect on arrival, offsets +55 estimated)
fixed (1) but still had (2), and the +55 was a guess. Parts landed at
varying positions, so it was reverted in config.

## 2. Functional Requirements

- The detection pulse is the encoder position at the moment the part
  **arrives** at the sensor (leading edge), with an error well under one
  tick (target ≤ ±3 pulses ≈ ±1 mm).
- Station offsets are re-calibrated once, from measurement, not estimates.
- No change to spec12/spec16 target math. They consume the better detection
  pulse unchanged.

## 3. Approach, in order of preference

**A. PLC-latched encoder count (best).** The PLC program captures the
encoder count (`encoder_indexer_ppr`) in hardware/interrupt time at the
sensor's falling edge (part arrives) and writes it, plus a sequence counter,
to new holding registers (e.g. `part_detect_pulse`, `part_detect_seq`). osm
reads them in the existing batched read. A new seq means a new part, and
detection = the latched pulse, independent of polling. Needs: register map
update (instrumentation team), PLC program change, config + dispatcher
change, and a bounds check that the latched pulse is ≤ the current pulse and
within a revolution.

**B. Software edge interpolation (fallback, no PLC change).** Take detection
= the midpoint between the last "absent" poll pulse and the first "present"
poll pulse. That halves the random error (±½ tick). Optionally reduce
`plc.real_poll_interval_ms` (e.g. 20 ms) after checking PLC load: it's a
single-connection Pi PLC, so watch Modbus round-trip times.

## 4. Steps (either approach)

1. **Measure the sensor on-time** with the backend stopped:
   `scripts/plc_monitor.py --hz 50`, PART ARRIVED vs "part left" pulses, over
   20+ parts. This gives the exact trailing-to-leading shift and its spread.
2. Implement A (or B). Keep `plc.part_sensor_active_low` (already in code,
   tested) and set it `true`.
3. Re-calibrate s1/s2 `station_offset_pulses` from images
   (Δ pulses = mm / 0.327), then re-check r1 reject timing.
4. Tests: latched-pulse path (new seq, repeated seq, stale/out-of-range
   pulse), interpolation math, active-low still admits on arrival.
5. Incident report update + commit.

## 5. Edge Cases & Error Handling

| Edge case | How to handle |
|---|---|
| PLC ACK never arrives | Not applicable: read-only registers. |
| Latched seq jumps by > 1 (parts closer than one poll) | Admit each missed part only if the PLC exposes a small FIFO; otherwise log a warning and admit the latest one. |
| Latched pulse newer than current or older than 1 rev | Reject as invalid, fall back to B for that part, log. |
| Sensor bounce (several edges per part) | Minimum-gap filter in pulses (e.g. < half a part length → ignore). |

## 6. Acceptance Criteria

- [ ] Detection error ≤ ±3 pulses (A) or ≤ ±½ tick (B), measured.
- [ ] s1/s2 parts centred within ±2 mm over 20 parts at 25 rpm.
- [ ] Reject hits the right part.
- [ ] Existing spec12/spec16 tests pass unchanged.
