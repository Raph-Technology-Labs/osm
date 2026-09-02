# Spec Checklist — Run These In Claude Code

Matches CLAUDE.md Section 8 (parallel frontend + backend, per page). Each
`/create-spec` line below is one invocation. Review and lock the contract
before either side of a page starts building — that's the gate that makes
parallel work safe.

**Status as of 2026-08-31:** built so far, ahead of this checklist's original
order, is: PLC simulator + wrap-corrected poller (`docs/specs/plc_simulator.md`,
implemented), `IndexerSlotTracker` + `StationDispatcher` (simulation-timer
firing only, not PLC-driven yet), N-camera `StationRegistry` with a real
YOLO defect pipeline and a real contour/ellipse measurement pipeline
end-to-end against simulated images, repo restructure to `backend/`/`frontend/`
only, and a working Inspection page (with sidebar) driven by all of the
above. None of Stage 0 or Stage 1 below has an actual spec doc yet — this
was built directly, spec-first was not followed for it. See the "Feature
list — next" note in `docs/specs/` planning discussion for how the two
reconcile going forward.

## Stage 0 — do this first, gates everything else

- [ ] `/create-spec performance budget — inference latency benchmark, Modbus batch-read register layout, DB write batching, ZMQ drop-old frame buffer rate, reject-deadline time-of-flight across the configured speed range`
      Every other spec's Constraints section should reference numbers from
      this one, not assume them. Pin down the Throughput Design
      Requirements (CLAUDE.md Section 5) as concrete decisions — which
      registers are contiguous, the DB batch flush interval, the frame push
      rate — not general principles to figure out later. **Not done** —
      register batching, DB write batching, and ZMQ drop-old semantics are
      not yet built or benchmarked; only the raw pipeline pieces exist.

## Stage 1 — shared foundations, sequential, both sides depend on these

- [ ] `/create-spec role-based auth — Super Admin, Admin, Operator` —
      **not built.** No role checks exist in any router; `LoginPage.jsx` is
      a frontend shell only. Biggest outstanding Critical Rule 6 gap.
- [x] Indexer slot tracker — `app/indexer/tracker.py` +
      `app/indexer/dispatcher.py` exist and are exercised by the live
      simulation-timer path; no dedicated spec doc was written for it.
- [ ] `/create-spec modbus register finalization — health check + device settings registers, including speed_setpoint_reg`
      — still placeholder addresses in `machine_config.yaml` (`error_registers`,
      `actuators`, `speed_setpoint_reg` all commented out / TBD).
- [ ] `/create-spec electron-backend IPC bridge — ZMQ pub/sub, drop-old frame buffer, ipcMain/ipcRenderer contract`
      — ZMQ PUB exists (`app/utils/zeromq.py`, `tcp://*:5558`) and Electron
      main process SUBs from it, but there's no written contract and no
      confirmed drop-old (vs. queuing) semantics.

Nothing page-specific was meant to start until these are done — both frontend and
backend for every page below depend on auth, the register list, and the IPC
bridge contract. In practice the Inspection page's backend was built ahead of
this gate; flagging it here rather than silently treating the gate as
satisfied.

## Stage 2 — per page, in this order, parallel frontend + backend within each

For every page: `/create-spec` → review and **lock the API contract** →
backend and frontend build in parallel (frontend against a mock server
matching the locked contract) → integration → test both sides.

- [ ] **Create Session** — `/create-spec create session page — part selection, barcode flag behavior`
- [ ] **Inspection** — `/create-spec inspection page — station-grouped live feeds, aggregation, alerts`
      Highest-risk page given the throughput SLA — build and load-test this
      pair before the lower-stakes pages. Before writing this spec: - Real numbers from the Stage 0 performance budget spec, not placeholders - The exact toast/alarm behavior for "reject not discarded" — currently
      marked TBD in CLAUDE.md, needs an actual decision first, not left
      open inside the spec - Confirm the `capture_mode` (parallel/serial) config shape (Section 6)
- [ ] **Config** — `/create-spec config page — recipe editor, n_slots override with validation + station-offset preview + audit log (see CLAUDE.md Section 3, page 7)`
- [ ] **Health Check** — `/create-spec health check page`
- [ ] **Device Settings** — `/create-spec device settings page`
- [ ] **Dashboard** — `/create-spec dashboard page — production analysis, filters, reports`
- [ ] **Login** — `/create-spec login page`
- [ ] **Technical Support** — `/create-spec technical support page`
- [ ] **Digital Twin** — `/create-spec digital twin page`

## The rule that makes this safe

If backend discovers mid-implementation that a locked contract needs to
change: **stop, flag it, update the spec, tell whoever's building frontend
against it.** Never silently diverge from a locked contract — that's how
parallel work turns into an integration-time surprise instead of a caught
problem.
