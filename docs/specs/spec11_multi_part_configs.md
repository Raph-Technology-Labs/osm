# Spec 11: Multi-part configs — camera scaling, dual reject routing, virtual exit

## Goal
Add three new part configs exercising config generality already built into
the system: variable camera-per-station counts, multi-reject-station
routing, and a no-removal "parts stay on the ring forever" mode.

## Step 0 — locate the actual per-part config structure (do this first, don't assume)
CLAUDE.md and earlier design notes describe default_config.yaml +
recipes/{part_code}.yaml, but the current machine_config.yaml embeds
part_code directly with no visible recipes/ folder. Find
resolve_config_for_part() in config_loader.py and report: does per-part
config live in a separate recipes/ directory today, or is
machine_config.yaml the only per-part file right now? This determines
whether new parts are new files in an existing folder or need scaffolding
first. Report before creating anything.

## Part 1 — rubber_small
- 3 inspection stations (s1, s2, s3), 2 cameras each (6 total).
- Same camera-block shape as rubber_big's s1.cameras.cam1 (ip, vendor,
  resolution, fps, roi, capture_mode, strobe_reg, sim) — incrementing
  ip/strobe_reg per camera, PLACEHOLDER-flagged the same way the existing
  file does.
- Rejection and exit are DEFAULT: single r1 (type: reject, enabled: true)
  after s3, single exit1 after that — same pattern as rubber_big.
- Reuse rubber_big's measurement/defect pipeline blocks as a structural
  starting point. Don't invent new tolerance/threshold numbers — mark
  PLACEHOLDER same as existing convention.
- No tracker/dispatcher changes needed — config only.

## Part 2 — med-3-station (dual reject routing)
- 3 inspection stations (s1, s2, s3). TWO reject stations:
  - r1, positioned after s1 (before s2) — fires if s1 reports NOK.
  - r2, positioned after s3 (before exit) — fires if s2 OR s3 reports NOK.
- A part failing s1 is pulled at r1, never reaches s2/s3. A part passing s1
  but failing s2 or s3 continues past r1 (nothing there catches it) and is
  pulled at r2.
- Requires a real behavior change: transition_r1 today only knows "any
  station nok," with no notion of which reject station cares about which
  inspection stations.
  - Proposed schema: each reject-station config gets a `watches: [station_ids]`
    field (e.g. r1.watches: [s1], r2.watches: [s2, s3]).
  - Proposed tracker change: generalize transition_r1 into
    transition_reject(slot_id, reject_station) reading that station's
    `watches` list against station_states, so future parts can define any
    station-to-reject-station mapping.
  - Propose this schema + tracker change to me before implementing — this
    is new behavior, not just a new yaml file.
- Camera count per station: not yet specified — ask before assuming
  1-per-station or matching rubber_small's 2-per-station.

## Part 3 — continuous, no removal ("parts stay on the indexer")
- No reject or exit station — only inspection stations in this part's
  station list.
- Add a new station type: `virtual_exit`. Sits at a configured
  station_offset_pulses like any other station, so the EXISTING
  dispatcher _tick() slot_id-changed detection fires it once per
  revolution per slot — no new revolution-boundary detection needed, this
  reuses the same mechanism real exit/reject already use.
- tracker.py: add `transition_virtual_exit(slot_id)`:
  - Reuse transition_exit's exact ok/nok decision (all station_states ok
    -> ok_total++, anything else -> nok_total++).
  - Do NOT call free_slot() — assign_part_id and the part stay on the
    ring permanently.
  - After tallying, reset that slot's station_states back to unreached
    (not assign_part_id) so the digital twin shows a fresh
    pending->resolved sweep next revolution — same part, same eventual
    result (from sim's forced_verdict), every lap.
- dispatcher.py: add an elif branch for `type == "virtual_exit"` calling
  tracker.transition_virtual_exit(slot_id), same shape as the existing
  exit/reject branches.
- Confirm: since entry only loads a slot when assign_part_id is None, and
  virtual_exit never clears it, these slots should already be permanently
  excluded from entry's re-fill logic — confirm this holds given entry's
  existing free-slot check, or flag if an explicit guard is needed.
- Seeding: confirm whether sim.nok/sim.blank apply as-is for a
  never-removed part (2 permanently-NOK slots per your original ask), or
  need adjusted meaning here since there's no removal/refill cycle to
  reseed against.

## Out of scope
- Real reject-actuator wiring (REJECT_CMD/40009) — still unwired per
  existing machine_config.yaml notes, unaffected by this spec.
- Changing rubber_big's existing config or behavior at all.
- Unifying wire_part_id / tracker assign_part_id (flagged elsewhere as a
  separate follow-up).

## Report back before implementing beyond Part 1
- Step 0's finding on recipes/ structure.
- Part 2's reject-routing schema proposal (watches: field + transition_reject).
- Part 2's camera-count question, answered.
- Part 3's virtual_exit design, confirmed against entry's re-fill guard
  and sim seeding question.

Part 1 (rubber_small) can be implemented directly once Step 0 resolves
where part files actually live — it needs no new tracker/dispatcher
behavior, config only.

## Status: Parts 1, 2, and 3 implemented (2026-09-08)

**Part 1 (rubber_small)**: see Step 0's finding above -- `machine_config
.rubber_small.yaml`, a sibling file to `machine_config.yaml`, resolved via
`resolve_config_for_part()`'s existing (previously unused by any real
caller) `config_path` parameter.

**Part 2 (med-3-station)**: implemented as proposed, with one important
correction found and fixed during implementation. Config: `RejectStation`
gained `watches: Optional[List[str]] = None` (None = watch every
inspection station, preserving rubber_big/rubber_small's exact original
behavior with zero changes to those files); `at_most_one_reject_station`
was removed and `reject_before_exit` generalized to check every reject
station; `reject_station()` was replaced with `reject_stations()`, which
returns them sorted by `station_offset_pulses` (ring order) -- this
ordering is load-bearing, not cosmetic (see below). Tracker:
`transition_r1(slot_id, enabled)` became `transition_reject(slot_id,
reject_station)`, using a new `any_watched_station_nok(slot_id, watches)`
that delegates to the original `any_station_nok()` when `watches is None`.
`r1_removed` was renamed `reject_removed` (confirmed no consumer of the
old name anywhere, including the frontend). Camera count: 2/station,
confirmed, matching Part 1's pattern.

**The correction**: the original proposal's `_pending_reject_targets`
dict (`StationDispatcher`, real-hardware mode) is shared across every
reject station by design (a physical slot must only ever be claimed by
one), but the *fire* step originally took a `reject_station` parameter
and would fire/transition using whichever station's loop iteration
noticed the crossing -- not necessarily the one that actually armed it.
With two reject stations, this could write the physical `reject_cmd`
register, then call `transition_reject()` with the WRONG station's
`.watches`, which could silently no-op (part reads as still in-flight in
the tracker despite already being physically discarded). Fixed by adding
a parallel `_pending_reject_targets`-keyed `_pending_reject_armed_by` map,
firing/transitioning with whichever station's own armed-target this was.
Similarly, `_reject_target_skipped` (the "already logged a miss, don't
spam" map) was re-keyed from `slot_id` alone to `(reject_station_id,
slot_id)`: one reject station missing its window doesn't mean a
physically-later reject station has also missed *its* (later) window --
each needs its own independent chance.

Proven, not just reasoned about: `test_dispatcher_real_mode.py`'s
`test_overlapping_watches_*` tests construct two reject stations with
deliberately overlapping `watches` (impossible in today's med-3-station
layout, whose r1/r2 watches are disjoint) and confirm the shared dict is
never overwritten, the physically-first station always wins regardless of
YAML declaration order, firing uses the correct armer, and a station
missing its window doesn't block a later station's independent chance.

Two gaps found along the way, deliberately not fixed here, tracked in
`spec14_followup_hardening.md`: `ExitStation.pass_if` is declared but
never read by `transition_exit()` (a pre-existing dead field, confirmed
while deciding `VirtualExitStation` shouldn't carry it either for Part 3);
and multi-reject-station real-mode firing shares one `reject_cmd`
register (a real limitation for separate physical actuators, out of
scope per this spec's own "real reject-actuator wiring" exclusion).

**Part 3 (continuous, no removal)**: implemented as proposed, both open
questions resolved as predicted and confirmed empirically, not just
reasoned about:
- **Entry re-fill guard**: confirmed unnecessary, no code change --
  `StationDispatcher._try_assign_entry()`'s existing `if
  record.assign_part_id is not None: return` already excludes a
  virtual_exit slot forever, since `transition_virtual_exit()` never
  clears `assign_part_id`. `test_virtual_exit_never_frees_the_slot`
  proves this across three full revolutions (`entered_count` never grows
  past one entry per non-blank slot).
- **sim.blank/sim.nok seeding**: confirmed unchanged, no code change --
  both are per-physical-slot properties `free_slot()` already preserves
  regardless of anything, and `transition_virtual_exit()` never calls
  `free_slot()` at all. `machine_config.continuous_part.yaml` sets
  `plc.sim.blank: 2`, meaning exactly what it means everywhere else.

New: `VirtualExitStation` (id/name/station_offset_pulses only --
deliberately no `pass_if`, matching the finding above that `ExitStation`'s
own `pass_if` isn't even wired up, so there was nothing worth propagating).
`ResolvedMachineConfig.exactly_one_exit_station` became
`exactly_one_terminal_station`: exactly one `type: exit` with zero
`virtual_exit`, OR zero `exit` with one-or-more `virtual_exit` -- never
both, never neither. `reject_before_exit` was made to no-op cleanly when
there's no real exit station to check against (a reject station combined
with virtual_exit-only stations isn't what Part 3 itself builds, but
isn't forbidden by the schema either, and the validator must not crash on
it). `IndexerSlotTracker.transition_virtual_exit()` reuses
`transition_exit()`'s exact ok/nok decision and fail-safe-to-NOK-on-
unresolved logic, but skips `free_slot()` and instead resets
`station_states` back to unreached for next lap.
`machine_config.continuous_part.yaml` (2 inspection stations, reused
verbatim from rubber_big, plus one `virtual_exit`) exercises it end to
end; `test_per_revolution_invariant_no_double_counting_for_continuous_part`
confirms `ok_total`/`nok_total` increment by exactly one per non-blank
slot per revolution, matching the acceptance criteria exactly.

## Acceptance criteria
- rubber_small: 6 cameras (2/station) all fire correctly, single r1/exit1
  behave identically to rubber_big's.
- med-3-station: a forced s1-fail part is pulled at r1, never reaches
  s2/s3. A forced s2-or-s3-fail (s1 pass) part is pulled at r2.
- Part 3: ok_total/nok_total increment once per revolution per slot
  (verify via the same conservation-style test pattern used for sim.nok/
  sim.blank elsewhere), no double-counting within a revolution, and no
  slot in this part is ever re-entered by the feeder.