# Digital twin frozen / cameras not firing: encoder slipped on the motor shaft

- **Date seen:** 2026-09-24
- **Area:** Indexer hardware (encoder coupling) -> PLC encoder registers -> dispatcher
- **Severity:** High: ring tracking and all station triggers depend on it
- **Status:** Root cause found (mechanical). Fix = re-secure the coupling, then verify.
- **Fix commit(s):** none (hardware). Diagnostic tools listed below.

## Summary
The encoder coupling had slipped on the motor shaft, so the encoder turned
less than the motor and the PLC counted only ~1500 pulses per indexer
revolution instead of 4800. osm (after `5a7444b`) correctly refused to treat
the early reset at ~1500 as a full revolution, so the digital twin held
still and no station fired. Before `5a7444b`, the old wrap formula padded
every short revolution back to exactly 4800, which hid the slip.

## Symptom
- Parts loaded, slot 0 filled at the first part, but the digital twin didn't
  rotate. cam1 and cam2 never triggered.
- PULSE DEBUG panel: RAW stayed between ~1075 and ~1500, HIGH-WATER crept up to
  ~1494, ACCUMULATED stayed near 0, RPM (measured) 0, many backward steps.
- Modbus tester: registers 40001 and 40002 both topped out at ~1500 and never
  approached 4800.

## Diagnosis (in order)
1. **Ruled out network bandwidth.** Encoder pulses are wired straight to the
   PLC inputs. Camera traffic is unicast to the PC and never reaches the PLC
   port. Modbus reads took 0.6 ms.
2. **Read-only PLC reads** (`scripts/plc_monitor.py`, inline traces):
   `part_sensor` idle = 1 (inverted sensor, a separate finding). Encoder
   registers 40001/40002/40003 were all frozen at 1078 with the motor
   stopped.
3. **TEMP PULSE DEBUG panel** on the Inspection page
   (`dispatcher._pulse_debug_snapshot` -> `publish_ring_state(debug=...)` ->
   `frontend/.../PulseDebug.jsx`):
   - frames from a screen recording (`encoder.webm`) showed RAW
     1078 -> 1107 -> 1379 -> 1461 -> 1385 -> 1457 over ~12 s at "25 rpm",
     where ~2000 counts/s was expected;
   - HIGH-WATER never above ~1500.
4. **Compared against the config's own confirmed history**
   (`machine_config.yaml`, verified 2026-09-12):
   - 40002 used to reset at **4800** and 40001 at **2400**;
   - both now reset at **~1500**, so a large, recent loss of counted pulses.
5. **PLC connection limit found along the way:** the PLC accepts one Modbus
   TCP connection. A second client times out while the backend is connected,
   so diagnostic readers must run with the backend stopped. The PLC's MAC
   (`d8:3a:dd:…`) is a Raspberry Pi.
6. **Physical inspection:** the encoder had **slipped from the motor**.

## Root cause
Mechanical: the encoder-to-motor coupling was loose, so the encoder shaft
slipped relative to the motor. Grip-slip-spring-back also explains the small
backward steps.

Why it wasn't caught sooner:
- The pre-`5a7444b` unwrap computed `gap = (cpr - last) + raw` on every drop,
  which turns a revolution that ended at ~1500 into exactly 4800. The twin kept
  turning (badly: ~50 of 75 slots skipped per revolution), so the slip looked
  like normal operation.
- Nothing checked that a revolution actually contained ~`encoder_cpr` counts.

## Actions taken
- Diagnosis tools (local, not committed yet):
  - `backend/scripts/plc_monitor.py`: read-only encoder / part-sensor monitor with a summary;
  - `backend/scripts/modbus_tester.py`: the register tester from `25723ab`,
    restored with PLC IP .72, 250 ms refresh, and bound to 127.0.0.1 with debug off;
  - TEMP PULSE DEBUG panel (backend snapshot + `PulseDebug.jsx`), with backward
    steps counted against the previous reading.
- **Hardware (pending):** re-secure the encoder coupling.

## Prevention
- **Mechanical:** paint-mark the coupling and motor shaft so slip is visible at
  a glance. Add it to the pre-shift checklist.
- **Verification after any encoder or coupling work:** run the Modbus tester
  (backend stopped) at 25 rpm. 40002 must reach 4799 and wrap to 0 about every
  2.4 s, and 40001 must wrap at 2400.
- **Revolution-length alarm (built, warn only):** at every PLC reset of
  `encoder_indexer_ppr`, `StationDispatcher._check_revolution_length()`
  compares the count reached (peak + last tick's step) with `encoder_cpr`.
  Below `indexer.min_revolution_pct` (default 90 %), it logs an error and the
  Inspection page shows a yellow "Encoder lost pulses" warning (`EncoderAlarm.jsx`,
  sent on the RingState broadcast as `encoder_alarm`).
  - A reset = a drop of ≥ cpr/5 to within the first cpr/10 counts, so
    wobble and roll-back never trigger it.
  - The revolution in progress at session start, and a stop mid-turn, aren't
    judged.
  - 7 tests in `tests/test_dispatcher_real_mode.py`.
  - Today's fault would have been flagged within one revolution (~2.4 s).

## Follow-ups
- Re-secure the coupling, run the verification above, then remove the TEMP
  PULSE DEBUG panel (or keep it behind a debug flag).
- Decide whether the revolution-length alarm should also stop the session after N short revolutions (warn only today).
- The part sensor is inverted (1 = no part). Fix it at the sensor (dark-on /
  NO output) or in the PLC, or add `part_sensor_active_low` to osm. Today parts
  are admitted on the trailing edge (part leaving the sensor).
- Related: [phantom revolution wraps](2026-09-24-phantom-revolution-wraps.md).
  Its large "wraps" were partly these short slip revolutions, not only
  standstill dither.
