# Spec 12: Pulse-precise reject timing

## Goal
Real-hardware entry detection and reject-actuator firing driven by exact
detected pulse offsets, not nominal slot boundaries -- eliminates the fixed
error mechanical variance introduces when a part triggers a few pulses
early/late within its slot on a given revolution.

## Scope boundary
Real-mode only (`plc.sim.enabled: false`). Sim-mode dispatch
(`StationDispatcher._tick_sim`, unchanged/only renamed from `_tick`) is
completely unaffected -- see "Do not touch" below. Camera/inspection/exit
station dispatch stays slot-changed-triggered in BOTH modes; only entry
detection and reject-station firing change for real mode.

## The five placeholders
Five previously-unconfirmed physical/hardware constants this spec
introduces, all explicitly flagged rather than silently assumed:
1. `PULSE_COUNT_REGISTER_WRAP` (dispatcher.py) -- pulse_count read as a
   single Modbus holding register, assumed to wrap at 2**16 (uint16).
2. `indexer.entry_sensor_mid_offset_pulses` -- part_sensor is mounted
   mid-slot by design, not at the slot boundary; required config, no
   default (0 would itself be an unconfirmed physical claim).
3. `plc.sim.entry_sensor_response_delay_ms` -- optical sensor lag before
   it registers a part. Ring-wide (not per-station), 0 is a valid default.
4. `plc.sim.reject_actuator_response_delay_ms` -- solenoid/valve lag after
   reject_cmd is set. Ring-wide, 0 is a valid default.
5. `plc.real_poll_interval_ms` -- real-hardware poll cadence, distinct
   from `plc.sim.tick_interval_ms` (a simulated "time per slot," far too
   coarse for real rising-edge/pulse-precise work).

Update, 2026-09-08: #3 and #4 live under `plc.sim:` (ring-wide), not under
`indexer:`/the reject station as originally sketched -- per explicit
instruction, since both are meant to be trial-and-error'd directly in
machine_config.yaml against real hardware (stopwatch/scope), with no code
change needed to retune either. Converted to pulses internally using
`pulses_per_slot` and the CURRENT measured rotation rate at the moment of
use (`StationDispatcher._ms_to_pulses`/`_update_pulse_rate_sample`), never
a fixed conversion baked in at config-load time or from `speed_scale`
(sim-only).

## Design
- This needs continuous pulse-count comparison against pending targets,
  not the existing slot-changed check stations use today — propose where
  this comparison loop lives (inside the existing tick, reading
  `tracker.current_raw_pulse` each cycle; or a faster dedicated loop if
  tick granularity is too coarse for reliable pulse-level triggering).
  Show the proposal and reasoning before implementing.
- When `current_raw_pulse` crosses a pending `target_fire_pulse` (handle
  wraparound per the free-running assumption above), fire `reject_cmd`,
  hold for `reject_pulse_duration_ms` (converted to a time or pulse hold
  as appropriate), clear it, then call the existing removal/tally logic
  (`transition_r1` — spec11 hasn't landed, so this is the correct current
  method name; flag clearly that a follow-up will be needed if spec11's
  later `transition_reject` rename lands).

## Why raw pulse, not just slot number (context for future readers)
Nominal slot math tells you which slot bucket a part is in — sufficient for
cameras, DB records, UI display, since those tolerate the part dwelling in
front of them. It is not sufficient for actuator timing: mechanical
variance means the same physical slot can trigger a few pulses earlier or
later on different revolutions. Keeping the actual detected pulse and
deriving the reject target from it (rather than from the slot's nominal
boundary) cancels that variance out instead of eating it as fixed error.

## Do not touch
- Camera/station dispatch stays exactly as-is (slot-changed trigger) —
  this only changes entry detection and reject actuator timing.
- Simulation-mode behavior (`sim.enabled` path) is completely unaffected —
  see Scope boundary above.
- spec11 is paused, not implemented — build against `transition_r1` as it
  exists today, do not implement spec11's routing changes as part of this.

## Report back before implementing
- Confirmation that all five placeholders are scaffolded per the naming
  above, not blocking implementation.
- The entry-detection architecture proposal (tick branch vs. dedicated
  poller) and reasoning.
- The reject-timing comparison loop proposal (tick-based vs. dedicated,
  and why) and reasoning.
- Confirmation of the single top-level sim/real gate design.

## Acceptance criteria
- With `sim.enabled: true`, behavior is byte-for-byte unchanged from
  before this spec — existing sim tests must still pass untouched.
- With `sim.enabled: false` (mocked PLC for testing), a simulated
  part_sensor rising edge correctly derives slot_index and stores
  pulse_count_at_detection.
- A NOK part's computed target_fire_pulse reflects its actual detected
  pulse offset (including both delay corrections), not the nominal
  slot-boundary value — verify with two mocked detections at slightly
  different pulse offsets for the same slot_index across two revolutions,
  confirming target_fire_pulse differs accordingly.
- Wraparound (free-running pulse count crossing back to 0) is handled
  correctly in the comparison loop, with a test case that crosses a
  revolution boundary between detection and fire.
- Changing `speed_scale` mid-session does not corrupt pending
  target_fire_pulse calculations for parts already in flight.

## Status: implemented (2026-09-08)
Answers to "Report back before implementing," resolved directly rather than
blocking on review, per explicit instruction to propose and proceed on any
remaining open question:
- **Entry-detection architecture**: inside the existing tick
  (`StationDispatcher._tick_real`), not a dedicated poller -- one shared
  poll of `part_sensor`/`pulse_count` per tick, same cadence
  (`plc.real_poll_interval_ms`) drives both entry detection and reject
  comparison. A dedicated faster loop was rejected: `real_poll_interval_ms`
  is itself the tunable granularity knob -- if it turns out too coarse
  against real hardware, that's the value to lower, not a reason to run a
  second, independently-timed loop that could drift against the first.
- **Reject-timing comparison loop**: tick-based (`_arm_reject_targets()` +
  `_fire_crossed_reject_targets()`, called every `_tick_real()`), same
  reasoning -- one poll loop, not two independent ones that could drift
  against each other.
- **Sign convention / target_fire_pulse formula** (assumption, flagged in
  `_arm_reject_targets`'s own docstring): `target_fire_pulse =
  (pulse_count_at_detection - entry_sensor_mid_offset_pulses -
  entry_sensor_response_delay_pulses) + reject_station.station_offset_pulses
  - reject_actuator_response_delay_pulses`. Both sensor-side corrections
  subtract (they pull the raw detection pulse *back* toward the part's true
  physical arrival); the actuator-side correction also subtracts (fire the
  command that many pulses *early* so the physical action, once its own lag
  elapses, lands exactly on the target).
- **Already-passed targets**: skip and log ERROR once per occupant (not
  fire on whatever part is currently at the nozzle instead) -- firing on
  the wrong part is worse than a missed reject, which `transition_exit`'s
  own `any_station_nok()` fallback still tallies correctly as NOK.
- **Fire semantics**: fire-and-immediately-clear (write 1, write 0 right
  back), not hold-then-clear -- the PLC generates the actual pulse width.
- **Single top-level sim/real gate**: confirmed, `self._tick_fn` chosen
  once in `__init__`, never a scattered per-call `if sim.enabled` check.

Blocking gap found and fixed during this pass: `SlotRecord` never actually
declared `pulse_count_at_detection` (read by `_arm_reject_targets` but
never set), and `IndexerConfig`/`PLCConnectionConfig` never declared
`entry_sensor_mid_offset_pulses`/`real_poll_interval_ms` as real pydantic
fields (pydantic silently ignores unknown YAML keys, so the real config
resolved without them despite the YAML setting them) -- real-mode dispatch
was fully implemented and unit-tested against hand-built fakes, but would
have raised `AttributeError` the first time it ran against the actual
resolved config. Also: `inspection_session.py`'s `start_session()` never
passed `plc_client` to `StationDispatcher` at all, even though
`load_machine()` already connects (or fails to and leaves `None`)
`app.state.plc_client` unconditionally -- real-mode dispatch was
unreachable from actual app startup. All three fixed; full suite green
(94 tests).