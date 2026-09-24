# OSM — Optical Sorting Machine

Machine vision inspection system for an indexer-based sorting machine. Parts are fed from a bowl feeder onto a rotating glass disc. Several camera stations inspect each part, the per-station results are combined, and a PLC-actuated reject (Modbus TCP) discards NOK parts.

**Throughput target:** 900 parts/min (15 parts/sec). This is a software throughput requirement; motor speed is tuned separately for each part.

## Architecture

The app runs as a desktop application on the machine's tower PC, with two local processes:

| Process | Stack | Responsibility |
| --- | --- | --- |
| **Backend** | Python, FastAPI, SQLAlchemy/Alembic, PostgreSQL, Redis | REST API (`/api/v1`), vision pipeline (YOLO defect detection + OpenCV measurement), indexer slot tracking, PLC comms over Modbus TCP |
| **Frontend** | Electron + React (MUI, Recharts) | Operator UI; live camera frames arrive over **ZMQ** (backend `PUB` → Electron main `SUB` → IPC to renderer), and everything else uses REST |

The backend is a modular monolith, not a set of microservices:

```
backend/app/
├── indexer/      # IndexerSlotTracker (pulse → slot math), StationDispatcher
├── plc/          # Modbus client, registers, PLC simulator, poller
├── camera/       # StationRegistry / CameraStation, Lucid camera + sim frame source
├── pipeline/     # ModelRegistry, defect (YOLO), measurement (ellipse fit), overlay drawing
├── config/       # machine_config.yaml + Pydantic schema / loader
├── routers/      # thin FastAPI routers: auth, parts, inspection, actuators, health, dashboard, ...
├── models/       # SQLAlchemy models
└── main.py       # FastAPI app entrypoint
```

Frontend pages include Login, Dashboard, Health Check, Device Settings, Part Selection / Create Session, Inspection, and Technical Support.

## Repository layout

```
backend/                 FastAPI app, Alembic migrations, tests, scripts
frontend/                Electron + React app
docs/specs/              Feature specs (spec-driven development, see TEMPLATE.md)
docs/reference/          Reference diagrams and simulators
docker-compose.dev.yml   Backend + Postgres + Redis for development
docker-compose.prod.yml  Production stack (GPU, Lucid Arena SDK)
CLAUDE.md                Project rules and design context (read this first)
SETUP.md                 Claude Code / MCP / database setup notes
```

## Getting started

### Prerequisites

- Docker + Docker Compose (for production, also `nvidia-container-toolkit`)
- Node.js + npm (frontend)
- Python 3 (only if you run the backend natively)
- Lucid Arena SDK. It is only needed for real Lucid cameras, is not available on PyPI, and can be downloaded from [thinklucid.com](https://thinklucid.com/downloads-hub/). Without it, cameras run in simulation mode.

### Backend (Docker, recommended)

```bash
# .env.dev sets ports, container suffix and DATA_DIR
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d
```

This starts Postgres (`:9432`), Redis (`:9379`) and the backend (`:9001`, debugpy on `:9679`, ZMQ on `:5558`). The backend runs `alembic upgrade head` automatically before starting uvicorn.

Production:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

### Backend (native)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# point DATABASE_URL (backend/.env) at an existing database, then:
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 9001 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run electron-dev   # React dev server + Electron, waits on the port from frontend/.env
```

Live camera feeds only work inside Electron. They are not available in a plain browser tab, because ZMQ runs in Electron's main process.

## Configuration

- Machine topology (stations, cameras, pipeline, registers, indexer geometry) lives in `backend/app/config/machine_config.yaml`. Per-part values stored in the DB override it when a session starts.
- Machine specs such as slot count, encoder CPR, station offsets, and health-check registers are **config-driven**. Never hardcode them.
- Secrets stay in `.env` files, which are gitignored. Never commit `.env`, PATs, or DB connection strings.

## Testing

```bash
cd backend
pytest
```

Tests cover the tracker, dispatcher, PLC simulator, reject routing, station registry, config loading, and ZMQ. They run against simulated PLC and cameras; no hardware is required.

## Development workflow

- Write a spec under `docs/specs/` (from `TEMPLATE.md`) before implementing a feature.
- Follow the critical rules in [`CLAUDE.md`](CLAUDE.md), especially these:
  - The PC owns slot tracking.
  - `PULSE_COUNT` wraps every revolution.
  - The reject decision is made at the R1 station.
  - Every `_CMD` has an `_ACK` with a timeout.
  - Role checks are enforced in the backend.
- Work on a feature branch and open PRs against the team branch.

---

© Raph Technology Labs
