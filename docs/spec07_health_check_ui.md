# Spec 7 — Health Check UI

## Context

Health Check shows live connectivity and sim/real mode for every PLC and camera, independent of any active session — this is possible because monitoring runs continuously from app startup (Spec 3). Per `specs/08_session_config_lifecycle.md` section 4a, connectivity and sim/real mode are shown as two separate facts, not collapsed into one status.

Read `specs/08_session_config_lifecycle.md` section 4a before starting. Confirm with Snehal that a `GET /health` endpoint exposing per-device status (per Spec 3's in-memory connection state) exists or is ready — if not, coordinate timing rather than blocking on it. Read `CLAUDE.md` for project context.

**Process: present a plan first (files to add/change, function signatures, no full implementations) and wait for confirmation before writing code.**

## Existing files relevant to this task

- `frontend/src/pages/PlaceholderPage.jsx` — currently placeholder for Health Check, replace with the real page.
- `frontend/src/routes/AppRoutes.jsx` — existing `/health-check` route.
- `frontend/src/theme/theme.js` — use existing theme tokens.
- `frontend/src/api/axios.js` — existing authenticated axios instance.

## What to build

**New files:**
- `frontend/src/pages/HealthCheckPage.jsx` — a list/grid of devices (PLC + each camera), each showing:
  - Connected / disconnected status (clear visual indicator — color + icon, not just text)
  - Mode: sim or real (per-device, per the schema in doc 08 §4a)
  - Last-seen timestamp, if the backend provides one
- `frontend/src/api/health.js` — `getHealthStatus()` API client function, calling the backend's health endpoint.

**Behavior:**
- This page should poll (not need a live WebSocket/SSE connection — per the architecture, this is low-frequency status, not the high-frequency live inspection feed) — a simple interval refetch (e.g. every 5–10 seconds) is sufficient. Confirm this matches backend response shape/expectations during planning.
- Visually distinguish "disconnected" (red/error state) from "connected but simulated" (a distinct neutral/informational state, not styled as an error — a sim device intentionally being simulated isn't a problem) from "connected and real" (clear healthy state).
- If the backend endpoint isn't available yet at the time of building, build against a documented mock response shape (confirm exact shape with Snehal / from doc 08 §4a) so the UI can be built and later wired to the real endpoint with minimal changes.

## Explicitly out of scope for this spec

- Device Settings (editing camera config) — Spec 6, a separate page
- Actuator control (starting/stopping the indexer manually from this page) — not part of Health Check
- Historical uptime/connectivity logging — this page shows current status only

## Definition of done

- Health Check page shows live, auto-refreshing status for the PLC and every configured camera
- Sim vs real mode is visually distinct from connected vs disconnected — both facts visible at once per device
- Page handles the "backend unreachable" case gracefully (doesn't crash, shows a clear error state)
- No changes to files outside what's listed above
