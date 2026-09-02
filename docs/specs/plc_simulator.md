```markdown
# Task: OSM PLC handshake — simulator + wrap-corrected slot poller

**Status: Implemented (2026-08-30).** Files live under `backend/app/plc/`
(`registers.py`, `simulator.py`, `poller.py`), tests under
`backend/tests/plc/` — not the `osm/plc/` and root `tests/plc/` paths shown
below, which reflect the pre-restructure layout this spec was originally
written against. 7 tests passing (`test_slot_tracker.py`,
`test_poller_integration.py`). All "explicitly out of scope" items below are
still out of scope in the current codebase — none have been built since.

## Scope (today only — do not implement triggers, reject logic, session DB writes, or multi-station registers)

Implement a minimal Modbus TCP PLC simulator and a PC-side poller that converts raw encoder pulses into slot-boundary events, with wrap-around correction.

## Files to create
```

osm/plc/simulator.py # PlcSimulator + start_simulator()
osm/plc/poller.py # SlotTracker + PlcPoller
osm/plc/registers.py # register address constants
tests/plc/test_slot_tracker.py
tests/plc/test_poller_integration.py # spins up simulator + real poller against localhost

```

## Register map (holding registers, pymodbus)

| Register | Direction | Type | Meaning |
|---|---|---|---|
| `SPEED_SETPOINT` (addr 0) | PC → PLC | uint16, RPM ×10 | written once at session start |
| `PULSE_COUNT` (addr 1–2) | PLC → PC | uint32 | free-running, wraps at `encoder_cpr` |
| `HEARTBEAT` (addr 3) | PLC → PC | uint16 | increments every PLC scan tick |

## Requirements

### `PlcSimulator`
- Runs a `pymodbus` async TCP server.
- Background loop at configurable `tick_hz` (default 50Hz): reads `SPEED_SETPOINT`, advances `PULSE_COUNT` by `(rpm/60) * encoder_cpr * tick_interval`, wraps at `encoder_cpr`, increments `HEARTBEAT` mod 65535.
- `encoder_cpr` and `port` are constructor args, not hardcoded.

### `SlotTracker`
- Pure, stateless-per-call logic driven by `update(raw_count: int) -> int` (returns current slot index).
- Must wrap-correct: if `raw_count < last_raw`, treat as `encoder_cpr` wraparound, not a reset to zero.
- `slot_boundary_crossed(prev_slot, new_slot) -> bool`.
- No I/O, no asyncio — must be unit-testable in isolation.

### `PlcPoller`
- `AsyncModbusTcpClient` wrapper.
- `write_speed_setpoint(rpm: float)` — one-shot write at session start.
- `poll_once() -> int` at `poll_hz` (default 20Hz): reads `PULSE_COUNT` + `HEARTBEAT` in one request, feeds `SlotTracker.update()`, returns current slot.
- Heartbeat staleness check: if `HEARTBEAT` register hasn't changed for >500ms, raise `TimeoutError("PLC heartbeat stalled")`.

## Acceptance criteria / tests

1. `test_slot_tracker_no_wrap` — monotonic pulse counts map to correct slot indices.
2. `test_slot_tracker_handles_wrap` — counter resets mid-revolution (e.g. `5990 → 20`) still accumulates correctly (no negative delta, no lost pulses).
3. `test_slot_boundary_detection` — boundary fires exactly once per slot transition, not on every poll tick.
4. `test_poller_integration` — start `PlcSimulator` with small `encoder_cpr` (e.g. 600) so wraparound happens within seconds of real time; connect a real `PlcPoller`; write a speed setpoint; assert slot index advances monotonically over ~5 seconds and wraps correctly across at least 2 full revolutions.
5. Simulate a stalled PLC (stop feeding heartbeat updates) and assert `PlcPoller.poll_once()` raises `TimeoutError` within 500ms.

## Explicitly out of scope for this task

- `SessionState`, `part_sessions` DB writes, `resolve_config_for_part`
- Camera trigger registers, station-specific handshake
- Reject/exit actuation
- FastAPI endpoints

## Dependencies

- `pymodbus` (async client + server)
- `pytest`, `pytest-asyncio`
```

4
