# Phantom revolution wraps from encoder dither

- **Date seen:** 2026-09-24
- **Area:** Indexer / dispatcher (`app/indexer/dispatcher.py`, `_tick_real`)
- **Severity:** High: ring tracking corrupted in real-PLC mode
- **Status:** Fixed
- **Fix commit(s):** `5a7444b`

## Summary
The dispatcher read every small backwards step of the encoder as the disc
completing a full turn. Near standstill the encoder dithers by 1-2 counts, so
the tracker gained a phantom revolution (4799 pulses) on each dither and lost
track of which part was in which slot.

## Symptom
Backend log during a real session, with the disc barely moving (the motor was
starting or stopping):

```
dispatcher: encoder_indexer_ppr revolution wrap: last_raw=1124, raw_pulse=1123, encoder_cpr=4800, computed_gap=4799
dispatcher: encoder_indexer_ppr revolution wrap: last_raw=1123, raw_pulse=1117, encoder_cpr=4800, computed_gap=4794
...
dispatcher: encoder_indexer_ppr revolution wrap: last_raw=1237, raw_pulse=1213, encoder_cpr=4800, computed_gap=4776
```

About 15 "wraps" were logged in 5 seconds. A real wrap only happens once per
revolution: about 2.4 s at 25 rpm, and never while nearly stationary.

## Diagnosis
- A real wrap goes from near `encoder_cpr` (4800) to near 0. Every logged
  "wrap" was a drop of only 1-60 counts (1124 -> 1123), so these weren't wraps.
- The raw value moved only about 7 counts in 1.3 s. At 25 rpm it should move
  about 2000 counts/s, so the disc was essentially stopped. That matches dither
  at standstill. The 1237 -> 1177 run just before the `motor/stop` request
  matches roll-back while stopping.
- `dispatcher.py:397` used the rule `raw_pulse < last => wrap` and computed
  `gap = (cpr - last) + raw`, which turns a 1-count backward step into +4799.

## Root cause
The unwrap logic assumed the encoder only ever moves forward. Real incremental
encoders flicker ±1 count when the shaft stops on a count edge, and a disc
rolls back slightly when the drive stops (gearbox/coupling backlash, drive
settling). The existing test only covered a clean forward wrap, and the sim
PLC never produces backward motion, so the bug only showed up on real hardware.

## Actions taken
- The unwrap now takes direction from the **shortest way round the circle**:
  `forward = (raw - last) % cpr`. If `forward <= cpr/2` the disc moved forward
  (this includes a real wrap such as 4795 -> 3 = +8). Otherwise it moved
  backward.
- A backward move adds **0**, and `_last_raw_pulse_count` stays at the
  furthest-forward position (high-water mark). When the disc moves forward
  again, pulses already counted aren't counted twice.
- Backward moves are logged at DEBUG. The INFO "revolution wrap" line now only
  appears for real wraps.

## Prevention
- New tests in `tests/test_dispatcher_real_mode.py`, built from the real log
  values:
  - `test_backward_wobble_is_not_a_revolution_wrap`
  - `test_rollback_while_stopping_is_held_then_resumes_without_double_count`
  - `test_backward_move_across_the_zero_point_is_not_a_wrap`
- Documented limit (comment in code): one tick must move less than half a
  revolution. That's about 850 rpm at 35 ms polling, far above the operating
  speed.
- `test_pulse_rate_measured_live_from_consecutive_ticks_not_speed_scale` now
  uses a realistic `encoder_cpr` (4800). Its old data stepped exactly one full
  revolution per tick, which can't be told apart from standing still.

## Follow-ups
- **Mechanical check (optional):** stop the motor and compare the encoder
  count before and after. A roll-back of more than ~50-100 counts, or one that
  grows over time, points to play in the coupling or gearbox.
- Consider making the sim PLC able to inject dither and roll-back, so sim runs
  exercise this path.

## Update (later on 2026-09-24)
The encoder turned out to be **slipping on the motor shaft**: a revolution
ended at ~1500 counts instead of 4800 (see
[encoder slipped on motor shaft](2026-09-24-encoder-slipped-on-motor-shaft.md)).
So the large "wraps" in the symptom log were partly these short slip
revolutions, not only standstill dither. The old formula padded each one
back to 4800 and hid the slip. The fix here still stands: after it, a short
revolution freezes the twin visibly instead of silently mis-tracking.
