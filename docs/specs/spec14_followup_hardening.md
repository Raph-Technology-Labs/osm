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
   register.** spec11 Part 2 (dual reject routing) added support for
   multiple `type: reject` stations, each independently armed/fired
   (`StationDispatcher._arm_reject_targets`/`_fire_crossed_reject_targets`
   in `app/indexer/dispatcher.py`). `RegisterMapConfig.reject_cmd` is a
   single, ring-wide register, so every reject station's physical fire
   command writes the SAME register today. This is a real limitation for
   a machine with genuinely separate physical actuators per reject
   station -- deliberately not addressed now, since spec11's own scope
   explicitly excludes real reject-actuator wiring ("Out of scope: Real
   reject-actuator wiring (REJECT_CMD/40009) -- still unwired"), and
   nothing exercised today (sim mode, or real mode against a single
   physical actuator) needs more than one register. Would need a
   per-reject-station command register (e.g. `reject_cmd` becoming a
   `Dict[str, int]` keyed by reject station id, or an explicit
   `cmd_reg` field on `RejectStation` itself) if/when real multi-actuator
   hardware is wired up.

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
- Do not implement any of the above as part of landing this doc. This is
  tracking only, same as spec13's list was before it was picked up as its
  own follow-up pass.
