# Spec Checklist — Run These In Claude Code, One At A Time

Each of these is a `/create-spec` invocation. Do NOT write all of these specs
in one sitting and rubber-stamp them — review each one before moving to the
next. A spec written on top of a wrong assumption from spec #2 will propagate
into every spec after it.

Order matches CLAUDE.md Section 8 (Staged Plan). Don't reorder without a
reason — later specs assume earlier ones are settled.

## Stage 0

- [ ] `/create-spec performance budget — inference latency benchmark, Modbus batch-read register layout, DB write batching, WebSocket throttle rate, reject-deadline time-of-flight at max configured speed`
      **Do this first.** Every other spec's Constraints section should
      reference numbers from this one, not assume them. This spec should
      pin down the three Throughput Design Requirements from CLAUDE.md
      Section 5 as concrete implementation decisions (which registers are
      contiguous, the DB batch flush interval, the WS push rate cap) — not
      leave them as general principles to figure out later.

## Stage 1

- [ ] `/create-spec role-based auth — Super Admin, Admin, Operator`
- [ ] `/create-spec indexer slot tracker` (if not already fully spec'd from earlier work)
- [ ] `/create-spec modbus register finalization — health check + device settings registers`
- [ ] `/create-spec electron-backend IPC bridge — ZMQ pub/sub, drop-old frame buffer, ipcMain/ipcRenderer contract`
      Locks in the Section 9 architecture decision as a concrete interface
      spec before any page that displays live camera feeds gets built
      against it.

## Stage 2 — one spec per page, API contract first

- [ ] `/create-spec login page`
- [ ] `/create-spec dashboard page — production analysis, filters, reports`
- [ ] `/create-spec health check page`
- [ ] `/create-spec device settings page`
- [ ] `/create-spec create session page — part selection, barcode flag behavior`
- [ ] `/create-spec inspection page — station-grouped live feeds, aggregation, alerts`
- [ ] `/create-spec config page — recipe editor`
- [ ] `/create-spec technical support page`
- [ ] `/create-spec digital twin page`

## Before writing the Inspection page spec specifically

This is the highest-risk page given the 1200 PPM target — it's the one
actually in the hot path. Its spec needs:
- Real numbers from the Stage 0 performance budget spec, not placeholders
- The exact toast/alarm behavior for "reject not discarded" — currently
  marked TBD in CLAUDE.md, needs a decision before this spec can be marked
  complete, not left as an open question inside the spec itself
- Confirmation of the `capture_mode` (parallel/serial) config shape from
  CLAUDE.md Section 6

## After all specs exist

Only then move to Stage 3 (core inspection loop implementation) per
CLAUDE.md's staged plan — don't let spec-writing and implementation
interleave across different pages, or you lose the benefit of having
reviewed the full picture before committing to any one part of it.
