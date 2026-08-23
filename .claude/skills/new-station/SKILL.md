---
name: new-station
description: Scaffold a new inspection or reject station into the config and dispatcher
argument-hint: [station-id] [type: camera|reject|exit]
disable-model-invocation: true
---

Add a new station `$1` of type `$2` to this project. Do all of the following:

1. Add an entry under `stations:` in the relevant part's YAML recipe with:
   - `id`, `name`, `type` (camera / reject / exit)
   - `pulse_offset` — ask the user for this value if not given; never guess a
     pulse distance, it must match the real machine's physical layout
   - for `camera` type: `cameras:`, `pipeline:` blocks following the existing
     pattern in other stations in the same file
   - for `reject` type: a `REJECT_CMD_<n>` / `REJECT_ACK_<n>` register pair
     (increment `<n>` past whatever's already used — check the register list
     doc first)
   - for `exit` type: confirm there's exactly one — there should never be more
     than one `OK_CMD`/`OK_ACK` pair regardless of station count

2. Update the register list documentation with any new registers added.

3. If the new station is type `camera`, confirm no PLC trigger register is
   being added for it — per the ownership model in CLAUDE.md, the PC fires
   camera triggers itself.

4. If the new station is type `reject`, confirm the aggregation/verdict
   evaluation happens at this station's tick, not deferred elsewhere.

5. Add or extend a test in `tests/test_indexer_tracker.py` covering the new
   station's `station_slot_id` calculation at at least two different
   `entry_slot_id` values, including one that wraps around `n_slots`.

Show me the diff before considering this done — don't just report success.
