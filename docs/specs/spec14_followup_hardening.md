# Spec 14: Follow-up hardening pass #2 (found during spec11 planning/implementation)

## Goal
Track real, verified gaps found while planning/implementing spec11 (multi-
part configs) that are out of that spec's own scope -- same purpose as
spec13's #1/#4-10 list (itself found during spec12's code review). Not
implemented here; this is a tracking doc only, per explicit instruction.

## Items

1. **`ExitStation.pass_if` is a dead field.** `config_loader.py` declares
   `pass_if: Literal["all_stations_pass", "any_station_pass"] = "all_stations_pass"`
   on `ExitStation`, but `IndexerSlotTracker.transition_exit()` never reads
   it at all -- the OK/NOK decision is hardcoded to `all_stations_ok()`
   regardless of what `pass_if` is set to in config. A part config setting
   `pass_if: any_station_pass` today would load cleanly and silently be
   ignored. Found while designing spec11 Part 3's `virtual_exit` station
   type (deliberately did NOT give `VirtualExitStation` a `pass_if` field
   for this reason -- no sense propagating a field that isn't wired up).
   Fix is either: wire `transition_exit()` to actually branch on it, or
   remove the field if `all_stations_pass` is the only behavior this
   system will ever support.

2. **Multi-reject-station real-mode firing shares one `reject_cmd`
   register -- design note, not a defect.** spec11 Part 2 (dual reject
   routing) added support for multiple `type: reject` stations, each
   independently armed/fired (`StationDispatcher._arm_reject_targets`/
   `_fire_crossed_reject_targets` in `app/indexer/dispatcher.py`).
   `RegisterMapConfig.reject_cmd` is a single, ring-wide register, and
   every reject station's physical fire command writing that same
   register today is **correct and intentional**: every real machine
   this app talks to has exactly one physical reject actuator, regardless
   of how many *logical* reject stations a part config declares (e.g.
   med_3_station's r1/r2 are two software routing decisions against the
   same one physical blower). This only becomes real work once a config
   with multiple reject stations actually gets a second physical actuator
   wired in.

   **Groundwork added now (2026-09-09), since the cost is low today and
   higher later:** `RejectStation.actuator_reg: Optional[int] = None`.
   Unset (every existing part config -- rubber_big, rubber_small,
   med_3_station, continuous_part) keeps writing the shared `reject_cmd`
   register, unchanged; `_fire_crossed_reject_targets` reads
   `armed_by.actuator_reg` first, falling back to `registers.reject_cmd`.
   Confirmed via `test_actuator_reg_unset_uses_the_shared_reject_cmd_register`/
   `test_actuator_reg_set_routes_firing_to_that_specific_register`
   (`test_dispatcher_real_mode.py`) and the config-level
   `test_actuator_reg_defaults_to_none_meaning_use_the_shared_register`/
   `test_actuator_reg_can_be_set_per_reject_station`
   (`test_config_loader.py`). When a second physical actuator eventually
   arrives, wiring it in is a one-line config change (set `actuator_reg`
   on that reject station), not a schema migration.

3. **`part_sensor`/`pulse_count` are two separate Modbus reads per
   real-mode tick, not batched.** Found in spec12's code review
   (2026-09-08): `app/plc/modbus_client.py`'s `read_register()` is
   explicitly documented as "not the batched `read_holding_registers`
   call," but `StationDispatcher._tick_real()` now calls it twice per
   tick on the real-time poll path (`plc.real_poll_interval_ms`, default
   50ms) that determines reject-timing precision. Two serial round trips
   instead of one batched read adds avoidable latency directly on that
   path -- worth batching per CLAUDE.md's Throughput Design Requirement 1
   (contiguous registers, one `read_holding_registers(start, count)`
   call) once real hardware is actually being polled against; not needed
   for anything exercised today (sim mode never calls this path at all).

## Do not
- Items #1 and #3 are tracking only -- do not implement them as part of
  landing this doc, same as spec13's list was before it was picked up as
  its own follow-up pass.
- Item #2's groundwork (`actuator_reg`) is implemented, per explicit
  instruction (2026-09-09) that the cost is low now and higher later.
  Wiring a second real physical actuator to it is still future work, not
  done here -- no config sets `actuator_reg` today.
