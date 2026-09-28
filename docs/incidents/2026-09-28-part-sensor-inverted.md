# Entry part sensor inverted (active-low): parts detected when leaving

- **Date seen:** 2026-09-24 (confirmed again 2026-09-28)
- **Area:** PLC input / dispatcher entry detection
- **Severity:** Medium: detection one part length late, and dependent on part length
- **Status:** Option added in code (`plc.part_sensor_active_low`), **reverted in config** (flag false) after the machine test. Open.
- **Fix commit(s):** see the commit that adds this report

## Summary
The entry sensor reads **1 with no part and 0 when a part is present**
(active-low: dark-on / NC wiring). osm assumed 1 = present and admitted a
part on the 0 -> 1 edge, which with this sensor is the moment the part
**leaves** the sensor. Detection, homing and every downstream target were one
part length (~18 mm ≈ 55 pulses) late. Offsets calibrated on the machine had
absorbed that, so things looked right, but the error varied with each part's
length.

## Symptom
- UI/panel showed `part_sensor = true` with no part; placing a part turned it
  `false`.
- Log: `part_sensor baseline established ... level=True` with nothing at the
  sensor.

## Diagnosis
- `scripts/plc_monitor.py`: register 40004 read 1 idle for seconds on end,
  with the motor off and no part.
- Modbus tester (backend stopped): placing a part drove 40004 to 0; removing
  it restored 1.
- `dispatcher._tick_real`: `elif sensor_state and not self._last_part_sensor_state`
  is a 0 -> 1 edge on the raw register, so this sensor gives the trailing edge.

## Root cause
Sensor output polarity (dark-on / NC wiring, or PNP/NPN inversion) is the
opposite of the register sheet's "1 = part detected". osm had no polarity
setting, so it couldn't be corrected without rewiring or changing the PLC
program.

## Actions taken
- New `plc.part_sensor_active_low` (default false). When true, the dispatcher
  converts the raw register to "part present" before baseline and edge
  detection, so parts are admitted on **arrival** (leading edge). Homing,
  detection pulse, spec12 reject targets and spec16 capture targets are
  unchanged: they already work in "present" terms. The baseline log line now
  prints raw and present.
- `machine_config.yaml`:
  - `part_sensor_active_low: true`;
  - s1 offset 267 → **322**, s2 offset 1595 → **1650** (+55 pulses ≈ 18 mm part
    length), so captures stay where they were before the change.
- `scripts/plc_monitor.py` reports "PART ARRIVED" / "part left" using the same
  flag; the Modbus tester label notes the polarity.

## Prevention
- 4 tests in `tests/test_dispatcher_real_mode.py`:
  - active-low admits on 1 -> 0 (arrival) and homes there;
  - a part leaving (0 -> 1) is not a detection;
  - idle-high never admits a phantom part;
  - the default active-high is unchanged.
- **Commissioning checklist:** with no part at the sensor, the baseline log
  must show `part_present=False`. If it shows True, flip
  `part_sensor_active_low`.

## Follow-ups
- On the machine:
  - s1 and s2 parts centred (fine-tune with Δ pulses = mm / 0.327);
  - reject still hits the right part;
  - exactly one "entered" log line per part.

## Update 2026-09-28: reverted in config
With `part_sensor_active_low: true` and offsets +55 (s1 322, s2 1650), s2
parts landed at a **different position each time**, where the trailing-edge
setup (flag false, 267 / 1595) had them centred. The flag is back to `false`
with the offsets restored. The code option stays (default off, 4 tests).

Why it didn't work as-is:
- The sensor edge is only seen on the next 50 ms dispatcher poll, so the
  detection pulse is quantized to one tick of disc travel (~30 pulses at
  7.6 rpm, ~100 at 25 rpm), and so is every capture position that uses it.
- +55 was an estimate of the sensor's on-time, not a measurement.

Before retrying (planned in `docs/specs/spec17_precise_part_detection.md`):
1. Measure the sensor on-time in pulses (plc_monitor, backend stopped,
   PART ARRIVED vs part left) instead of estimating.
2. Reduce detection quantization: interpolate the edge between the last
   "absent" and first "present" poll, or better, have the PLC latch the
   encoder count at the sensor edge into a register that osm reads.
