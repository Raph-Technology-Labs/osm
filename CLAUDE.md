# OSM (Optical Sorting Machine) — Project Context

## 1. Project Overview

Indexer-based machine vision inspection system. Multiple camera stations
inspect parts on a continuously-rotating glass disc (fed from a bowl feeder),
aggregate per-station results, and drive a PLC-actuated reject via Modbus TCP.

Target throughput: **900 PPM (15 parts/sec)** — this is a **software
throughput SLA, not a motor speed.** Motor speed itself is tuned empirically
per part (a slotted fastener tolerates higher RPM without falling off the
disc; other parts may need slower handling) — that tuning is mechanical, not
a software decision. The software's job: never be the bottleneck up to 900
PPM sustained, regardless of which part-specific speed is actually
configured via `SPEED_SETPOINT`. See Critical Rule 7 and the Throughput
Design Requirements in Section 5.
constraint — see Critical Rule 7. It shapes every architecture decision below,
not just a nice-to-have.

Full application, not just the vision pipeline: role-based auth, a
multi-page React frontend (dashboard, health check, device settings, session
creation, live inspection, config/recipe editor, technical support, digital
twin view), and a FastAPI backend serving all of it.

## 2. Roles & Auth

Three roles, each strictly additive in privilege (Operator ⊂ Admin ⊂ Super Admin):

| Role | Who | Can do |
|---|---|---|
| Super Admin | Raph developers | Edit config, create recipes, add/delete parts |
| Admin | Client engineers | Add/delete parts |
| Operator | Machine operators | Select part, start/view sessions only |

Role checks belong in the backend (route-level authorization), never
enforced only in the frontend. More roles/permissions will be added later —
design the permission model to extend, not to be rewritten.

## 3. Pages (build order matters — see Section 8, Staged Plan)

1. **Login** — role-based auth, 3 roles above
2. **Dashboard** — production analysis (day/month/year/part filters), today's
   sessions on landing, machine efficiency metrics, graphs/pie charts/tables,
   CSV/PDF report export, pagination/record limits (never unbounded queries)
3. **Health Check** — PLC status, camera status, PLC error register
   monitoring — all driven by `health_check_reg` names defined in config, not
   hardcoded
4. **Device Settings** — run/stop indexer, reject actuation on/off, OK
   control (if present) — also config-driven
5. **Create Session** — part/category selection from DB, optional barcode
   scanner (cursor auto-focus behavior depends on `barcode_present` config
   flag — see Section 6), submitting initializes cameras + PLC variables from
   the recipe and redirects to Inspection
6. **Inspection** — the core live page: station-grouped camera feeds, live
   OK/NOK + part_id per camera, tabbed layout if too many cameras to fit,
   per-station aggregated OK/NOK, toast alerts on failure (esp. undischarged
   reject — alarm + toast, exact behavior TBD, build the hook now), running
   OK/NOK totals
7. **Config** — recipe editor (part name, category with add-new, indexer
   pitch/CPR editable) — this is the authoring UI for the same YAML schema
   already established, must stay in sync with it, not diverge into a
   separate shape
8. **Technical Support** — static Raph contact/support info (content pending)
9. **Digital Twin** — real-time visual of current indexer state (reference
   HTML to be provided) — this is a *view* onto `IndexerSlotTracker`'s live
   state, not a separate tracking implementation

Every page: Raph logo placed consistently, footer with rights message +
tagline (content pending).

## 4. Architecture

- `app/models/models.py` — SQLAlchemy schema (7 tables — see raph-vision
  platform notes)
- `app/indexer/tracker.py` — `IndexerSlotTracker`: pulse handling, slot math
- `app/indexer/dispatcher.py` — routes by station type (camera / reject / exit)
- `app/plc/modbus_client.py` — register R/W
- `app/plc/watchdog.py` — heartbeat + ACK timeout monitoring, owns `STOP_COMMAND`
- `app/pipeline/` — `PipelineContext`, `ModelRegistry`, defect/measurement steps
- `app/auth/` — role-based access control (NEW — not yet built)
- `recipes/*.yaml` — human-authored category recipes, imported via
  `recipe_import.py`, never read live by the engine
- `config.yaml` — debug snapshot only, written after `resolve_config_for_part()`,
  never read back
- `frontend/` — React, pages per Section 3

*(Adjust paths above to match the actual repo once code lands.)*

## 5. Code Style

- Python: PEP 8, type hints on all public functions
- **Given the 900 PPM target: profile before optimizing, never the reverse
  — but three specific design decisions are already known to matter and
  should be built in from the start, not discovered under load:**

  **Throughput Design Requirements (non-negotiable given the SLA):**
  1. **Batch Modbus reads.** Lay out frequently-co-read registers at
     contiguous addresses so they can be pulled in one
     `read_holding_registers(start, count)` call instead of N separate
     round trips (each is ~5-20ms over TCP — this compounds fast at 15
     events/sec). This is a register-map layout decision — coordinate with
     whoever finalizes the register list, don't retrofit it later.
  2. **Batch DB writes.** Never one `INSERT` per part on the hot path.
     Buffer `SessionResult`/`CameraResult` writes and flush in batches via a
     background task.
  3. **Live camera feed: ZMQ direct to Electron's main process, drop-old
     semantics, not a queue.** Backend `PUB`s at full pipeline rate; Electron
     main `SUB`s directly (no WebSocket, no HTTP — see Section 9 for why).
     Hold only the *latest* frame per camera and overwrite as new ones
     arrive — never queue a backlog to "catch up." A live preview is
     CCTV-style: dropping frames under load is correct behavior, not a bug.
     Non-real-time pages (Dashboard, reports, config) can use plain REST
     from the renderer — only the live feed needs this path.

  This workload is I/O-bound (Modbus polling, DB writes, network), not
  CPU-bound Python computation — `asyncio` for I/O orchestration + threading
  for GPU inference (GPU/OpenCV release the GIL) is the right shape. This is
  not a case for reaching past Python/FastAPI — the risk at 900 PPM is
  orchestration overhead, not raw inference throughput.
- Prefer O(1) lookups (dict/set) over scanning, generators over building
  large lists in the hot path, and keep the vision pipeline's hot path free
  of anything that isn't either numpy/OpenCV/PyTorch vectorized C or
  genuinely necessary Python glue.
- Prefer targeted diffs over full-file rewrites when fixing existing code
- Threading, not multiprocessing, for the vision pipeline — GPU/OpenCV ops
  release the GIL; `ModelRegistry` is a thread-safe singleton specifically to
  avoid duplicating GPU memory across stations
- React: functional components, hooks, no class components. Match whatever
  `theme.js` gets provided — don't invent a competing design system

## 6. Config Schema — new fields needed for the pages above

These extend the existing schema (already covers `stations`, `pipeline`,
`part_aggregation`, register list). New, not yet finalized:

```yaml
ui:
  barcode_present: true          # controls cursor auto-focus on Create Session
health_check:
  registers:
    - name: "PLC_STATUS"
      reg: 50
    # ... more, name/reg pairs, driven entirely by config, never hardcoded in frontend
device_settings:
  speed_setpoint_reg: 51         # PC -> PLC, Write. Motor speed is tuned
                                  # per-part empirically (mechanical/handling,
                                  # not software's call) — decide: does the
                                  # software enforce a max (e.g. don't accept
                                  # a setpoint the pipeline can't keep up
                                  # with), or is that entirely the operator's
                                  # responsibility?
stations:
  - id: s1
    capture_mode: parallel       # NEW — "parallel" | "serial", station-level
                                  # (separate from the existing defect/measurement
                                  # serial-vs-parallel convention, which is per-camera)
```

`capture_mode` and `health_check.registers` are proposed shapes — confirm
before building the config editor page against them, since the editor UI
needs to match the real final schema, not an assumed one.

## 7. Critical Rules — do not violate without flagging it explicitly

1. **The PC owns all slot tracking.** PLC only streams pulse count/heartbeat +
   entry sensor + reject/OK acks. Camera stations never wait on a PLC trigger
   register — the PC fires them itself.

2. **`PULSE_COUNT` resets to 0 every revolution.** Never divide this register
   directly for slot-boundary math — route through the wrap-corrected
   internal accumulator.

3. **The reject decision is evaluated at the R1 (reject) station tick — never
   at Exit.** R1 physically discards NOK parts via a blower; the part is gone
   from the ring at that point. Exit only ever sees parts that already passed.

4. **Every `_CMD` register gets a matching `_ACK`, with a timeout.** Missed
   `REJECT_ACK` escalates to `STOP_COMMAND` (a NOK part may have escaped —
   safety-critical). Missed `OK_ACK` only raises `FAULT_STATUS`.

5. **Machine spec is config-driven, not hardcoded.** `n_slots`, `encoder_cpr`,
   station pulse offsets, `capture_mode`, `health_check` registers — all from
   config, computed/read per part or per machine, never literal in code.

6. **Role checks are backend-enforced, not frontend-only.** A hidden button
   is not access control.

7. **900 PPM is a software throughput SLA — the ceiling the software must
   never fail to sustain, not a physical motor constant.** Motor speed is
   tuned per-part empirically (mechanical/handling concern, not software's
   to decide) via `SPEED_SETPOINT`. Before deep pipeline work: benchmark
   real inference latency, verify the three Throughput Design Requirements
   (Section 5) are actually built in, and get the real angular
   time-of-flight from last inspection station to R1 at max configured
   speed — that's the worst case for the reject deadline. Don't write code
   whose correctness depends on a throughput number nobody has measured.

8. Never commit `.env`, PATs, or DB connection strings.

## 8. Staged Development Plan (frontend design isn't ready yet)

Build backend-first and API-contract-first, so frontend work can start the
moment wireframes exist, without waiting on backend implementation to finish:

**Stage 0 — Performance Budget spec.** Benchmark inference latency,
determine real throughput ceiling, determine reject-deadline time-of-flight.
Gates everything else — do this before Stage 1.

**Stage 1 — Backend foundations.** Auth/RBAC, DB schema finalization
(including any new tables/fields Section 6 needs), `IndexerSlotTracker` +
dispatcher (if not already built), Modbus client + register list finalized
(including new health-check and device-settings registers).

**Stage 2 — API contracts, no UI yet.** Write the spec (Section 3's page
list, one spec per page via `/create-spec`) with API Contract sections fully
filled in, even before frontend design exists. This is what unblocks
frontend work later without backend being the bottleneck.

**Stage 3 — Core inspection loop.** Create Session → Inspection page backend
support (this is the highest-risk page given the PPM target — build and load
test this before the lower-stakes pages).

**Stage 4 — Remaining pages**, roughly in the order listed in Section 3,
each via its own spec.

**Stage 5 — Frontend**, once wireframes/theme exist — implement against the
API contracts from Stage 2, page by page.

Don't skip straight to page-by-page full-stack work — the risk with this
project specifically is that the PPM target invalidates an architecture
decision late, and it's much cheaper to discover that in Stage 0/1 than
after 5 pages are built against it.

## 9. System Architecture

**Desktop application, not a web app.** Electron frontend + Python backend,
both running locally on the tower PC. Do not design for browser
compatibility — it is not a requirement, and attempting it would mean
maintaining two different data paths (one IPC-based, one browser-safe) for
no real benefit.

**Two local processes, talking over localhost ZMQ — not microservices:**
- **Python backend** — FastAPI + vision pipeline + `IndexerSlotTracker` +
  PLC comms, all in one process (threaded, not multiprocessed — GPU/OpenCV
  release the GIL, `ModelRegistry` avoids duplicating GPU memory across
  processes). `ZMQ PUB` for live camera frames and state.
- **Electron app** — main process `SUB`s directly from the backend's ZMQ
  socket (native `zeromq.js` bindings — this only works in Electron's main
  process, not a browser tab), bridges to the renderer via `ipcMain`/
  `ipcRenderer`. Live camera preview and inspection state flow through this
  path, not WebSocket.
- Dashboard/Config/reports pages (non-real-time) can still use plain
  REST calls from the renderer to the backend's HTTP API — only the
  high-rate live feed needs the ZMQ→IPC path.

**Modular monolith, not microservices.** One deployment unit. Internal
module boundaries (`indexer/`, `plc/`, `pipeline/`, `auth/`, `api/`) exist
for code organization and testability, not for independent scaling or
deployment — there's no need for either on a single-machine industrial
system, and splitting into networked services would reintroduce exactly the
per-hop latency the Throughput Design Requirements (Section 5) work to
eliminate.

**Remote access: AnyDesk/remote desktop, not a browser fallback.** Mirrors
the real Electron window (including camera feeds) with zero additional
engineering. If a genuine need for standalone remote web access to specific
pages (e.g. Dashboard KPIs) emerges later, that's a separate, thin REST-only
web view built if and when actually needed — not a default requirement now.

**Docker scope:** containerize the backend (FastAPI + Postgres + Redis, GPU
passthrough via `nvidia-container-toolkit`) — `docker-compose.dev.yml`/
`docker-compose.prod.yml` already exist in this repo for this. Electron
ships separately as a native installer/AppImage, not inside a container —
matches the AppImage + `COMPOSE_MODE` pattern already established on the
broader raph-vision platform.



If a task needs actual current register addresses, part spec, or station
layout and they're not in this repo's recipe YAML, ask rather than inventing
plausible-looking values.
