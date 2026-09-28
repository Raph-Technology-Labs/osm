# Spec: Session lifecycle: runs in the background, one at a time, ends only on Stop / app close

Status: **PLANNED, not started.** Written 2026-09-28; implementation starts
2026-09-29. Companion to `spec18_plc_outage_session_end.md` (shares the
`end_session(app, reason)` helper and `end_reason`).

## 1. Problem Statement

A running session should keep inspecting in the backend while the operator
looks at the Dashboard, Part Details, Health Check and so on. There should be
one obvious way back to the live view. A new session should only be possible
after the running one is stopped, and the session should end only via
**Stop** or **closing the app**.

What exists today (checked 2026-09-28):
- Leaving `/inspection` does NOT stop anything. That's correct.
- `sessionActive` is derived from the **URL** (`MainLayout.jsx:13`), so on any
  other page "New Session" is enabled again. Starting one **silently replaces**
  the running session (`start_session()` just stops the old dispatcher).
- There's no way back to the live view except the route itself.
- Closing Electron only disconnects ZMQ (`public/electron.js:106-111`). The
  backend keeps running **with the motor on**.
- There's no backend "is a session active" API: `/session/current` returns
  totals only.

## 2. Functional Requirements

1. **The backend is the source of truth** for whether a session is running.
2. **One session at a time, enforced by the backend.** Starting a second one
   is rejected with a clear message; no silent replacement. Machine/part
   config edits that affect the running session are rejected too.
3. **Frontend session context** replaces the URL-based `sessionActive`:
   - "New Session" (and Add Part / config edits) disabled on **every** page
     while a session is active, with the tooltip "Stop the running session
     first";
   - a prominent **"● LIVE — RB-001"** button at the top of the sidebar
     (pulsing red dot, elapsed time, OK/NOK), visible on every page, that
     opens `/inspection` (live feed, twin, Stop);
   - `/part-selection` redirects to `/inspection` while a session is active;
   - after login or an app restart, if a session is active → go straight to
     `/inspection`.
4. **Leaving the Inspection page:** nothing changes in the backend. The
   dispatcher, cameras and motor keep running, and results keep being saved.
   ZMQ frames are simply not rendered.
5. **The session ends only via:**
   - **Stop button** (existing: motor/stop + session/stop);
   - **App close (graceful):** Electron `before-quit` → `preventDefault()` →
     IPC to the renderer ("stop session") → the renderer calls motor/stop +
     session/stop with its auth token → ack → quit. Timeout ~5 s, then quit
     anyway. If a session is running, confirm first: "A session is running —
     stop it and quit?";
   - **Safety net (app crash / killed / PC sleep):** the frontend sends a
     heartbeat every 2 s. If none arrives for `ui_heartbeat_timeout_s`
     (config, e.g. 30 s) while a session is active, the backend **stops the
     motor and ends the session** (`ui_lost`), logged at ERROR;
   - **Backend shutdown:** FastAPI shutdown hook → motor stop + end session
     (`backend_shutdown`);
   - **PLC outage** → end session (`plc_lost`, spec18).
6. Every end records `end_reason`: `stop_button` / `app_close` / `ui_lost` /
   `backend_shutdown` / `plc_lost`.

## 3. API / Interface Contract

| Aspect | Description |
|---|---|
| `GET /inspection/session/state` | `{active, session_id, part_code, started_at, motor_running, plc_state, last_end}` |
| `POST /inspection/session/start` | **409** "A session is already running (RB-001) — stop it first" while one is active (and 503 while the PLC is down, spec18) |
| `POST /inspection/ui/heartbeat` | Every 2 s from the frontend while logged in |
| Config | `ui_heartbeat_timeout_s` (e.g. 30) |
| DB | `PartSession.end_reason` (Alembic migration) |
| Electron IPC | New `before-quit` → renderer "stop-session" → ack channel, documented in the IPC bridge spec (CLAUDE.md §13) |
| PLC registers | `stop_cmd` / `speed_setpoint` via the existing motor endpoints only; no new registers |

## 4. Constraints

- The session must survive page navigation. Only the ZMQ rendering stops.
- App close must never leave the motor running without the operator having
  been asked.
- A heartbeat timeout that's too short would end sessions during normal UI
  hiccups: 30 s default, configurable.

## 5. Edge Cases & Error Handling

| Edge case | How to handle |
|---|---|
| PLC ACK never arrives | Motor stop on app close / ui_lost is a single `stop_cmd` write. If the PLC is unreachable, end the session anyway and rely on the PLC-side comms-loss stop (spec18 §4). |
| Electron restarted within the heartbeat timeout | Re-attach: after login, `session/state.active` → go to `/inspection`; no data lost. *(Confirm on 2026-09-29.)* |
| Electron killed / crashed | The heartbeat safety net stops the motor and ends the session after `ui_heartbeat_timeout_s`. |
| Second browser/window starts a session | 409 from the backend. |
| Config edited while a session runs | 409 on config write endpoints that affect it. |

## 6. Acceptance Criteria

- [ ] Start a session, browse Dashboard/Health: inspection continues (counts
      rise) and "New Session" is disabled on every page.
- [ ] The LIVE button returns to the live view from any page.
- [ ] `POST /session/start` while active → 409 with a clear message.
- [ ] Closing the app asks, then stops the motor and ends the session (`app_close`).
- [ ] Killing Electron: after 30 s the backend stops the motor and ends the session (`ui_lost`).
- [ ] Backend shutdown ends the session (`backend_shutdown`).
- [ ] Tests: API 409 guard, state endpoint, heartbeat timeout (fake PLC),
      shutdown hook, `end_reason` persisted. Frontend lint/build.

## Implementation outline (files)

- **Backend:**
  - `app/routers/inspection.py`: session/state, 409 guard, ui/heartbeat,
    `end_reason`;
  - `app/inspection_session.py`: active-session state,
    `end_session(app, reason)`, heartbeat watchdog thread, shutdown hook;
  - `app/models/models.py` + Alembic: `PartSession.end_reason`;
  - config: `ui_heartbeat_timeout_s`.
- **Frontend:**
  - new `src/context/SessionContext.jsx`;
  - `layouts/MainLayout.jsx` and `components/Sidebar.jsx` (LIVE button,
    disable rules);
  - `routes/AppRoutes.jsx` (part-selection redirect);
  - `pages/InspectionPage.jsx` (heartbeat, stop);
  - `public/electron.js` + `preload.js` (before-quit IPC, confirm dialog).

## Decisions to confirm (2026-09-29)

1. Re-attach on an Electron restart within the timeout: yes (recommended)?
2. `ui_heartbeat_timeout_s`: 30 s?
3. Which config edits to block while a session runs (all machine config, or only the running part's)?

---

*Reviewed before implementation, per TEMPLATE.md / CLAUDE.md Critical Rules.*
