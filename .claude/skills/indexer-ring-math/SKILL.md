---
name: indexer-ring-math
description: Use this skill whenever writing or reviewing code that computes slot positions, station timing, or pulse-count handling for the OSM rotary indexer. Covers the station_slot_id formula, the pulse-count wraparound fix, and the heartbeat/action cadence split. Trigger on any mention of slot_id, station_offset, pulses_per_slot, entry_slot_id, or IndexerSlotTracker.
---

# Indexer Ring Math

## The model

`slot_id` is a ring-buffer index meaning "the part that entered N ticks ago" —
**not** a fixed physical position. Stations are fixed distances (in slot-ticks)
after Entry. Every slot boundary, the buffer's meaning shifts relative to the
current entry pointer.

## The core formula

```python
station_offset = round(station_pulse_distance_from_entry / pulses_per_slot)
station_slot_id = (entry_slot_id - station_offset) % n_slots
```

`pulses_per_slot = encoder_cpr // n_slots`. `station_offset` is computed once at
config load. `station_slot_id` is recomputed every tick — it's the only part of
this that changes per-tick.

**Always use Python's `%`, never a manual sign check.** Python's modulo already
returns a positive result for negative operands (`-1 % 8 == 7`), which is
exactly the wraparound behavior needed here.

## Position flags are unconditional

Set `flag_cam` / `flag_reject_status` / `flag_exit_status` for whichever slot
lines up with a station **regardless of whether a part is present there**.
Actuation (firing a camera, firing a reject) is a *separate* check on
`slot.assign_part_id is not None`. Don't fold these two checks into one
condition — a common mistake is skipping the flag entirely on an empty slot,
which breaks anyone reading the table for pure position tracking.

## The pulse-count wraparound trap

The PLC's `PULSE_COUNT` register resets to 0 every revolution (`encoder_cpr`
pulses). **Never** do `cumulative_pulses // pulses_per_slot` directly on the
raw register value — when it resets, the division result goes backward and a
slot-boundary crossing gets silently missed.

Correct pattern: maintain an internal, never-reset accumulator. Detect the
wrap (`new_value < last_value`), correct the gap for it
(`gap = (encoder_cpr - last_value) + new_value`), and add the corrected gap to
the accumulator. Do slot-boundary math against the accumulator, never the raw
register.

## Heartbeat vs. action cadence — two different things

- `heartbeats_per_slot` subdivides each slot into liveness checkpoints
  (e.g. 3 → a check every `pulses_per_slot / 3` pulses). Pure liveness — no
  slot action runs, no register beyond `PULSE_COUNT`/`HEARTBEAT_*` involved.
- The actual `tick()` (slot advance, station dispatch) only fires once per
  **full** `pulses_per_slot`, regardless of how finely heartbeats are
  subdivided.

If `pulses_per_slot % heartbeats_per_slot != 0`, the heartbeat spacing goes
uneven — validate this at config load and raise, don't silently truncate.

## Everything here is parameterized, never hardcode

`n_slots` is part-size dependent (computed per recipe, not fixed). Don't write
code, tests, or examples that assume a specific slot count like 80 — use it as
one example among several when testing, and always derive it from config.
