# Spec: Pulse-precise inspection-station trigger

Status: implemented 2026-09-28 (real-PLC mode). Follows spec12 (pulse-precise
reject timing), whose target math it reuses.

## 1. Problem Statement

Inspection stations (s1, s2, ...) fire their cameras when the station's
**slot index changes** (`_tick_real` step 3). That has two errors, and they
add up:

- **Slot quantization.** A part sits anywhere inside its 64-pulse slot (~21 mm
  of disc at 500 mm diameter / 4800 cpr), so the capture moment relative to
  the *part* varies by up to one slot.
- **Tick quantization.** The slot change is only noticed on the next 50 ms
  dispatcher tick: ~30 pulses (~10 mm) at 7.6 rpm, ~100 pulses (~33 mm) at
  25 rpm.

Seen on 2026-09-28: the s2 part lands at different positions in the FOV, often
off-centre. Defect inspection needs the part centred every time.

The reject station doesn't have this problem, because it fires from the part's
own detection pulse (spec12).

## 2. Functional Requirements

- In real-PLC mode, every `type: inspection` station fires its cameras when
  the ring reaches **that part's** target pulse:
  `target = pulse_count_at_detection − indexer.entry_sensor_mid_offset_pulses
  − ms_to_pulses(plc.sim.entry_sensor_response_delay_ms)
  + station.station_offset_pulses − ms_to_pulses(station.trigger_latency_ms)`
  (the same corrected-detection term as the reject target).
- **Between ticks:** if the target falls before the next tick, a one-shot
  timer fires at `(target − now) / measured pulses_per_ms`, so timing error
  isn't bounded by the 50 ms tick.
- **Exactly once** per station per occupant (keyed by the occupant's
  detection pulse), however many ticks see it.
- **Late but close** (≤ half a slot past the target): fire now, log a warning
  with how late.
- **Missed** (> half a slot past, the part has left the FOV): don't fire.
  Record the station as NOK for that part, with an error log. Imaging
  whatever is there now would judge the wrong part.
- **Fallback:** a part with no detection pulse, and sim mode (`_tick_sim`),
  keep the slot-change trigger unchanged.
- **Per-station choice:** `trigger: pulse | slot` on each inspection station
  (default `pulse`). `slot` restores the legacy slot-change firing for that
  station. It's only meant for a large FOV where centring doesn't matter, or
  to run without relying on detection pulses. `pulse` is correct for any FOV.
- Each fire logs its target pulse and position, for calibrating
  `station_offset_pulses`.

## 3. API / Interface Contract

| Aspect | Description |
|---|---|
| Input | `encoder_indexer_ppr` + `part_sensor` (already read every tick), `station_offset_pulses`, new optional `trigger_latency_ms` per inspection station (default 0) |
| Output | `station_registry.fire_station()` at the target pulse; `tracker.mark_pending()`; `apply_station_result(passed=False)` on a miss |
| Registers | No new registers read or written |

## 4. Constraints

- Timing error ≈ Modbus poll jitter + timer jitter + trigger latency spread:
  a few ms, ~1-2 mm at 25 rpm (was up to one slot plus one tick).
- `pulses_per_ms` is measured live between ticks (spec12). Scheduling uses the
  current rate. A speed change during the final < 1 tick is negligible.
- No extra Modbus traffic. Per tick: O(stations × slots) in-memory checks.

## 5. Edge Cases & Error Handling

| Edge case | How to handle |
|---|---|
| PLC ACK never arrives | Not applicable: capture firing writes no PLC register. |
| Slot freed or reassigned before a scheduled timer fires | The timer re-checks the occupant's part_id and skips if it changed. |
| Rate unknown (first ticks, 0 pulses/ms) | No scheduling; fire on the tick that crosses the target (late ≤ 1 tick). |
| Dispatcher stopped with timers pending | `stop()` cancels them. The timer also checks `_stopped`. |
| Target already passed at arm time (short offset / late detection) | Late ≤ ½ slot: fire and warn. Otherwise: NOK plus an error log. |
| Encoder slip | Revolution-length alarm (warns). Targets are in accumulated pulses, so a slip shifts capture position. |

## 6. Acceptance Criteria

- [x] Inspection stations in real mode fire from the part's detection pulse, not from slot change.
- [x] Sub-tick timer fires between ticks, exactly once per occupant.
- [x] Late/missed handling as above; slot-change fallback kept.
- [x] Unit tests for target math, scheduling, once-only, late, missed, reassigned slot.
- [x] On hardware (2026-09-28): s2 parts land centred in the FOV (`station_offset_pulses: 1595`).

## Calibrating `station_offset_pulses`

Measure the part centre's offset from the image centre along the direction of
travel, in mm (mm/px from the camera's calibration). Then:

`Δ pulses = offset_mm / (π × diameter_mm / encoder_cpr)`

That's ≈ offset_mm / 0.327 at 500 mm / 4800. If the part appears **before**
the centre (not yet arrived), **increase** the offset. If it's **past** the
centre, decrease it. Check the sign once on the machine, since it depends on
camera orientation.
