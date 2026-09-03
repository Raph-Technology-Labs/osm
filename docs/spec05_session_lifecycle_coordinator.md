# Spec 5 — Session Lifecycle & Coordinator

## Context

This is where everything from specs 1–4 comes together. Per `specs/08_session_config_lifecycle.md` sections 5–7: creating a session stages a recipe (loaded, not yet persisting); pressing Start makes it active (indexer "starts", verdicts get persisted); pressing Stop finalizes it. The Coordinator tracks parts in-flight across multiple stations before making a final accept/reject decision per part.

Read `specs/08_session_config_lifecycle.md` sections 5–7 before starting, and the Coordinator design discussion (in-flight parts tracked by `part_id` in a dict, not by physical slot — that's the PLC/camera thread's concern, not the Coordinator's). Read `CLAUDE.md` for project context.

**Process: present a plan first (files to add/change, function signatures, no full implementations) and wait for confirmation before writing code.**

## Existing files relevant to this task

- `backend/app/runtime/zmq_listener.py` (from spec 3) — the `queue.Queue()` this spec drains from.
- `backend/app/core/config_loader.py` (from spec 1) — `activate_recipe()`, called on session creation.
- `backend/app/models/models.py` — existing `CompanySession`, `SessionMeasurement`, `PartDefect` tables — use these, don't create new ones.
- `backend/app/db/db.py` — existing `get_db()` pattern.

## What to build

**New files:**
- `backend/app/schemas/session.py` — `SessionCreate` (part_id, mode, counting_type, etc. — match existing `CompanySession` fields), `SessionOut`.
- `backend/app/runtime/coordinator.py`:
  - `PartRecord` dataclass: `part_id`, `results: list[Verdict]`, `max_severity: str | None`.
  - `SessionCoordinator` class: `session_id`, `staged: bool`, `active: bool`, `active_recipe: RecipeConfig`, `in_flight: dict[int, PartRecord]`, `counts: dict`.
  - `create(part_number, mode) -> session_id` — calls `activate_recipe()` (spec 1), creates the `CompanySession` DB row, sets `staged=True`, `active=False`.
  - `start()` — sets `active=True`, triggers the PLC actuator write to start the indexer (via the PLC client from spec 2/3).
  - `stop()` — sets `active=False`, triggers actuator write to stop, finalizes `CompanySession.session_end` and aggregate counts.
  - `handle_event(msg)` — called for every message drained from the ZMQ listener's queue. Routes by message kind: encoder ticks (track position if needed), camera-ready (no-op for now unless needed for UI), verdicts (append to the relevant `PartRecord`, and when a part reaches a reject/exit station, run arbitration and persist).
  - `VerdictArbitrator` (can live in this file or `backend/app/runtime/arbitrator.py`) — given a `PartRecord` and the active recipe's `rejection_routing`, decide final disposition (which reject station, or accept).
  - `drain_loop(msg_queue)` — the `async def` loop draining the queue via `asyncio.to_thread(msg_queue.get, True, 0.2)` (timed get, per the bug found and fixed in `10_pipeline_runtime_simulator.py` — a bare blocking get will hang shutdown; use the timeout pattern from that file).
- `backend/app/routers/sessions.py`:
  - `POST /sessions` — calls `coordinator.create(...)`, returns `SessionOut`.
  - `POST /sessions/{id}/start` — calls `coordinator.start()`.
  - `POST /sessions/{id}/stop` — calls `coordinator.stop()`.
  - Register this router in `main.py`.
- Update `backend/app/runtime/lifecycle.py` (from spec 3) — start the Coordinator's `drain_loop` as an `asyncio.Task` alongside the existing background threads/process.

**Behavior:**
- The Coordinator only persists to the database while `active=True` — events arriving while staged or stopped are received (so Health Check-style status stays current) but not written to `session_measurements`/`part_defects`.
- `in_flight` entries for a part should be removed once that part reaches a final disposition (reject or accept) — don't let this dict grow unbounded. A part that never reaches a final station (sensor issue, timeout) is a known edge case — for this spec, add a basic time-based cleanup (e.g. drop entries older than N seconds with a log warning) rather than leaving it fully unhandled.
- One `CompanySession` can only be active at a time — reject a `start()` call if a session is already active (return a clear error, don't silently replace it).

**Tests:**
- `test_create_session_stages_without_persisting`
- `test_start_session_activates_and_writes_on_verdict`
- `test_stop_session_finalizes_counts`
- `test_verdict_arbitration_critical_routes_correctly`
- `test_verdict_arbitration_cosmetic_routes_correctly`
- `test_events_ignored_while_not_active`
- `test_in_flight_cleanup_drops_stale_parts`
- `test_cannot_start_second_session_while_one_active`
- `test_drain_loop_exits_cleanly_on_shutdown` — regression test for the exact hang bug found in the reference simulator

## Explicitly out of scope for this spec

- Live push of events out to the frontend (Electron IPC / ZMQ out) — not part of this spec, Coordinator just persists and tracks counts for now; the frontend-facing live stream is a later slice
- The Inspection page UI (grid/pagination) — separate frontend slice, not covered here
- Multiple concurrent sessions — explicitly one at a time, per behavior above

## Definition of done

- `pytest` passes all tests listed above
- A full create → start → (simulated verdicts arrive) → stop cycle, run against the mock PLC/camera/inference stack from specs 2–4, results in correct rows in `session_measurements`/`part_defects` and correct final counts on the `CompanySession` row
- Attempting to start a session while one is already active returns a clear error, doesn't corrupt state
- Backend shuts down cleanly (no hang) with the Coordinator's drain loop running
- No changes to files outside what's listed above
