---
name: sim-cycle
description: Simulate a run of the indexer tracker against synthetic pulse data, to manually verify station-slot math without hardware
argument-hint: [n_slots] [num_ticks]
disable-model-invocation: true
---

Write and run a short standalone script (not a permanent test file, put it in a
tmp/ or scratch location) that:

1. Instantiates `IndexerSlotTracker` with `n_slots=$1` (default 80 if not given)
   and a small set of example stations at varied, non-uniform `pulse_offset`
   values — don't use evenly-spaced offsets, the point is to exercise the
   general case.

2. Feeds it `$2` (default: enough to complete at least 2 full revolutions)
   simulated `on_pulse_update()` calls, including:
   - a normal steady stream
   - at least one deliberately dropped/delayed update, to exercise the
     missed-heartbeat path
   - at least one crossing of the `encoder_cpr` boundary, to exercise the
     wrap-corrected accumulator
   - a mix of `sensor_active=True/False` entries so some slots have parts and
     some don't

3. Prints the slot table (`as_table()`) after each tick where a station fired,
   in a readable format — one line per event, not a full table dump every time.

4. At the end, print a short summary: total ticks, total parts entered, any
   missed-heartbeat warnings raised, and confirm no exception was thrown during
   the revolution-wrap crossing.

Use this to sanity-check the tracker logic after any change to `tick()` or
`on_pulse_update()` — it's faster than wiring up real hardware to catch an
obvious regression.
