# Spec: PLC lost during a session → retry, then end the session + "drain the parts"

Status: **PLANNED, not started.** Written 2026-09-28; implementation starts
2026-09-29. Builds on `6260a02` (dispatcher reconnect with backoff) and
`docs/incidents/2026-09-28-plc-outage-stopped-dispatcher.md`.

## 1. Problem Statement

Since `6260a02` the dispatcher survives a PLC drop and keeps reconnecting.
But a session can wait forever, and the operator only gets a toast that's
easy to miss. With no connection the PC can't drain or stop anything:
stopping the indexer and draining is **PLC-side / physical**, and there's no
drain button in the UI. If the disc turned while the PC couldn't see it,
captures and rejects were missed, so those parts must be drained and
re-checked.

Decisions (2026-09-28):
- Retry for a set time. If still not reconnected: **end the session**, and
  show a **central error: "PLC connection lost — drain the parts. Session
  completed."**
- While the PLC is disconnected: a **red toast on every page that doesn't go
  away** until the PLC is back.
- Starting a new session is **blocked** with "PLC not connected".

## 2. Functional Requirements

```
RUNNING ─link lost─▶ RECONNECTING (dispatch paused, persistent red toast "PLC connection lost — reconnecting… 12 s")
   ▲                    │
   │ reconnected within  │ grace expired  ─or─  reconnected but disc moved / PLC rebooted
   │ grace AND disc did  ▼
   │ not move       SESSION ENDED (end_reason = plc_lost)
   └── resume            │  centre modal: "PLC connection lost — session completed.
                         │   Drain all parts from the disc and re-check them.
                         │   7 parts were in progress; 3 may have reached the OK bin since 14:32:05."  [OK]
                         ▼
                   IDLE: red toast on every page until the PLC answers again;
                   New Session / Start blocked: "PLC not connected (192.168.7.72:502)"
```

1. **Link lost:** dispatch is paused and reconnecting (exists). The red toast
   appears on every page and **can't be dismissed**, showing "PLC connection
   lost — reconnecting… (down 12 s)". It clears itself when the PLC answers.
2. **Reconnected within `plc.reconnect_grace_s`** (config, e.g. 30 s):
   - disc **didn't move** (`encoder_count` delta < ½ slot, because the PLC
     stopped the motor or it was a blip) → **resume** silently with the same
     state (toast "PLC reconnected — resumed");
   - disc **moved**, or `encoder_count` went backwards (PLC rebooted) →
     tracking is lost → step 3 (write `stop_cmd` first, now that it's
     reachable).
3. **Grace expired, or reconnected but tracking lost → session ends
   automatically:**
   - dispatcher stopped;
   - session finalized with the same code as the Stop endpoint, with
     `end_reason = plc_lost`; results flushed;
   - in-flight parts recorded as **"drained / re-check"**, a separate total,
     not OK or NOK;
   - "May be in the OK bin" count: parts that passed the exit during the
     outage, computed from the `encoder_count` delta if the PLC came back,
     otherwise estimated from the last speed × outage time and labelled
     "estimated";
   - a **centre modal** (must be acknowledged) on whatever page the operator
     is on: "PLC connection lost — session completed. Drain all parts from
     the disc and re-check them. N in progress; M may have reached the OK bin
     since HH:MM:SS."
4. **Afterwards:**
   - the persistent red toast stays on every page while the PLC is
     disconnected;
   - **New Session / Start is blocked in real-PLC mode while the PLC is
     unreachable:**
     - backend: `POST /inspection/session/start` first tries
       `_connect_plc()`; if it still fails → **503 "PLC not connected
       (192.168.7.72:502) — check the PLC and its network"**, instead of the
       confusing NoTickSource error;
     - frontend: the Part Selection page still loads the part list (it comes
       from the DB, not the PLC), so the operator can pick a part. The
       **Start button is disabled** with the note "PLC not connected —
       waiting…", and it enables itself when `/health/plc` reports connected.
       Sidebar "New Session" gets the same tooltip.

## 3. API / Interface Contract

| Aspect | Description |
|---|---|
| Input | Batched read now 40002..40004: `encoder_indexer_ppr`, `encoder_count` (monotonic total pulses), `part_sensor` |
| Output | `stop_cmd` (40010) write when tracking is lost and the PLC is reachable; session finalized with `end_reason = plc_lost`; RingState `plc_state {state, down_s, ended, drained, maybe_in_ok_bin, since}` (replaces `plc_outage`) |
| API | `POST /inspection/session/start` → 503 while the PLC is unreachable; `GET /inspection/session/state` → includes `last_end` for the modal |
| Config | `plc.reconnect_grace_s` (default 30) |

**Exact movement:** keep the last good `encoder_count`. On reconnect:
- `moved = now - before`;
- `moved < 0` → PLC reboot → tracking lost;
- `moved < pulses_per_slot/2` → resume;
- otherwise → tracking lost.

Fallback if 40003 proves unreliable: any outage with last rate > 0 → tracking
lost.

## 4. Constraints

- The PC **can't send STOP without a link.** PLC-side requirements (PLC
  programmer):
  - **comms-loss stop:** if there's no Modbus request from the PC for
    > ~500 ms, stop the indexer and put the reject valve in its safe state;
  - draining is physical/PLC-driven: optionally a PLC-side purge routine
    triggered from the machine panel;
  - re-enable `plc.watchdog_enabled` for production.
- The PLC accepts one Modbus client. Diagnostic tools only run with the
  backend stopped.
- Reconnect backoff 0.5 → 5 s and a 1 s Modbus timeout (existing) keep
  detection within ~1-2 s.

## 5. Edge Cases & Error Handling

| Edge case | How to handle |
|---|---|
| PLC ACK never arrives | Not applicable: nothing here waits for a PLC ACK. `stop_cmd` is only written once the PLC is reachable again. |
| Reconnect within grace, disc not moved | Resume, state intact, no session end. |
| Reconnect within grace, disc moved | Tracking lost → `stop_cmd`, end session, drain modal. |
| `encoder_count` went backwards | The PLC rebooted → tracking lost. |
| Grace expires while still down | End session without any PLC write; drain modal with an *estimated* OK-bin count. |
| Operator on another page | Modal and toast are mounted in `MainLayout`, so they show on any page. |
| Backend restarted during the outage | Session state is lost with the process; spec19's shutdown hook and `end_reason` cover it. |

## 6. Acceptance Criteria

- [ ] Motor stopped, 10 s cable pull, re-plug → resumes, no session end.
- [ ] Motor running, pull > 30 s → centre modal "session completed, drain
      the parts", session ended (`plc_lost`), red toast on every page. Part
      Selection shows parts with Start disabled ("PLC not connected").
      Re-plug → toast clears, Start enables.
- [ ] Motor running, 5 s pull, re-plug → disc moved → session ended + drain modal.
- [ ] PLC power-cycle during a session → ended (reboot detected).
- [ ] Tests:
  - dispatcher: resume within grace; end on movement, reboot or expiry;
    `stop_cmd` only when reachable;
  - API: 503 start with the PLC down; `end_reason` persisted;
  - frontend: lint/build; the PLC toast is non-dismissible.

## Implementation outline

- **Config** (`PLCConnectionConfig`): `reconnect_grace_s: float = 30`.
- **Dispatcher** (`app/indexer/dispatcher.py`):
  - `encoder_count` in the batched read;
  - the grace deadline checked in `_on_plc_tick_failure`;
  - on expiry or tracking lost: call a session-end callback, injected by
    inspection_session (keeps the dispatcher free of DB code);
  - `tracker.mark_all_drained()` returns the counts;
  - publish `plc_state` on RingState.
- **Session** (`app/inspection_session.py`, `app/routers/inspection.py`):
  - an `end_session(app, reason)` helper shared by the Stop endpoint, the
    PLC-lost auto-end and spec19's app-close / ui-lost;
  - `PartSession.end_reason` + a drained total (Alembic migration);
  - session/start: `_connect_plc()` retry, then 503;
  - `last_end` in app state for the modal.
- **Frontend:**
  - `ConnectionAlerts.jsx`: the PLC alert becomes non-dismissible and
    auto-clears on reconnect (camera alerts stay dismissible);
  - new `PlcSessionEndedDialog.jsx` in `MainLayout`;
  - PartSelection Start disabled + note while the PLC is down;
  - Sidebar New Session tooltip;
  - remove `plc_outage` from `EncoderAlarm.jsx`.
- **Docs:** link from the outage incident report; a PLC-programmer note.

## Decisions to confirm (2026-09-29)

1. `reconnect_grace_s`: 30 s?
2. Drained parts: separate "Drained / re-check" total (recommended), or NOK?
3. PLC programmer: comms-loss stop, and an optional panel purge routine.

---

*Reviewed before implementation, per TEMPLATE.md / CLAUDE.md Critical Rules
(touches the indexer and register list).*
