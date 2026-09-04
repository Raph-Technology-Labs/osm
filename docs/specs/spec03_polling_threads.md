# Spec 3 — PLC & Camera Polling Threads

## Context

Per `specs/08_session_config_lifecycle.md` section 4: PLC and camera monitoring runs continuously from app startup, independent of any session — this is what powers the Health Check page and makes hardware status visible before an operator ever creates a session. This spec builds those always-on background threads and the ZMQ transport connecting them to the rest of the app.

Read `specs/06_frozen_architecture_chart.md` (process map, section 3) before starting. Also read `10_pipeline_runtime_simulator.py` — it's a working, tested reference implementation of exactly this thread + ZMQ wiring pattern; follow its structure rather than reinventing it. Read `CLAUDE.md` for project context.

**Process: present a plan first (files to add/change, function signatures, no full implementations) and wait for confirmation before writing code.**

## Existing files relevant to this task

- `backend/app/hardware/device_resolver.py`, `plc_interface.py`, `camera_interface.py` (from spec 2) — use these, don't create a second way to get a PLC/camera client.
- `backend/app/core/config_loader.py` (from spec 1) — `load_machine_config()`, `load_active_config()`.

## What to build

**New dependency:** `pyzmq` — add to `backend/requirements.txt`.

**New files:**
- `backend/app/runtime/plc_thread.py` — `PLCPollThread` (or a `run_plc_poll_loop(ctx, running_event, stop_event)` function run inside a `threading.Thread`): connects via `get_plc_client()`, loops reading registers at a fixed interval, publishes each reading over a ZMQ socket bound to `inproc://plc-events`. Must respect a `stop_event` (clean shutdown) in addition to the session `running_event` (start/stop indexer) — these are two different flags, don't conflate them: the thread itself runs from app startup to app shutdown; the indexer only "runs" (increments ticks / matters for session data) between session start and stop.
- `backend/app/runtime/camera_thread.py` — same pattern for camera capture: connects via `get_camera_source()` per configured camera, loops capturing frames when active, publishes frame-ready notices over `inproc://camera-status`. Actual frame dispatch to inference (via `ipc://`) is spec 4's concern — this spec should publish frame-ready events and hold captured frames somewhere accessible (in-memory, keyed by camera_id, most-recent-only is fine for now), but the ZMQ PUSH to the inference process's frame-input socket happens in spec 4 once that socket exists.
- `backend/app/runtime/zmq_listener.py` — `ZMQListenerThread`: binds `inproc://plc-events` and `inproc://camera-status` as PULL sockets (bind BEFORE the threads above start connecting — see doc 06/doc 10 for why), polls both via `zmq.Poller`, forwards every message onto a `queue.Queue()`. This queue is what spec 5's Coordinator will drain.
- `backend/app/runtime/lifecycle.py` — `start_background_runtime()` / `stop_background_runtime()`: called from FastAPI's `lifespan` startup/shutdown handlers. Starts the ZMQ listener thread first, waits briefly for its binds to complete, then starts the PLC and camera threads. On shutdown, sets `stop_event`, joins all threads with a timeout, closes ZMQ sockets/context cleanly.
- Wire `start_background_runtime()` / `stop_background_runtime()` into `backend/app/main.py`'s `lifespan` context manager.

**Behavior:**
- All three threads (listener, PLC, camera) must be daemon threads or cleanly joined on shutdown — no hung process on Ctrl+C.
- The PLC/camera threads must handle a connection failure gracefully (log it, retry with backoff) rather than crashing the thread — a disconnected camera should show as "disconnected" on Health Check (spec 7), not take down the whole backend.
- No database writes happen from this spec — that's the Coordinator's job (spec 5). This spec only gets data flowing through ZMQ into the listener's queue.

**Tests:**
- `test_zmq_listener_binds_before_threads_connect` — verify no messages are lost if PLC thread starts immediately after listener signals ready
- `test_plc_thread_publishes_ticks` — run briefly against `PLCSimClient`, confirm messages appear on the queue
- `test_camera_thread_publishes_status` — same, against `MockCameraSource`
- `test_background_runtime_starts_and_stops_cleanly` — start then stop, confirm all threads actually terminate (use `thread.join(timeout=...)` and assert `is_alive() is False`)
- `test_plc_thread_survives_connection_failure` — mock a connection error, confirm thread doesn't crash/exit

## Explicitly out of scope for this spec

- Anything about sessions (staged/active) — these threads run identically regardless of session state, per doc 08 §4. Session-awareness lives in the Coordinator (spec 5).
- Dispatching frames to the inference process — spec 4.
- Persisting anything to Postgres — spec 5.
- Health Check API/UI reading this data — spec 7 (though this spec should make current connection status queryable in-memory, in a form spec 7 can read).

## Definition of done

- `pytest` passes all tests listed above
- Running the backend locally shows continuous PLC/camera thread activity in logs from startup, with zero sessions ever created
- Stopping the backend (Ctrl+C / normal shutdown) exits cleanly within a few seconds, no hung threads
- Disconnecting the mock source mid-run (simulate however is easiest) doesn't crash the backend
- No changes to files outside what's listed above
