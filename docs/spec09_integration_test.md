# Spec 9 — End-to-End Integration Test

## Context

This is a verification pass, not a new feature — confirming specs 1–8 actually work together as one system, against the simulator stack (sim PLC + mock camera + real pipeline registry), before moving on to the next phase (Inspection page UI, Dashboard, Electron shell).

Read `specs/06_frozen_architecture_chart.md` and `specs/08_session_config_lifecycle.md` in full before starting — this spec checks the implementation against everything those docs describe. Read `CLAUDE.md` for project context.

**Process: present a plan first (what will be tested, in what order, and how success is measured) and wait for confirmation before running anything.**

## Prerequisites

Specs 1–8 should be merged (or at least functionally complete) before starting this spec. If any are incomplete, list exactly which parts are missing during the plan step rather than testing around gaps silently.

## What to do

**Backend integration test** (`backend/tests/test_integration_full_flow.py` or similar):
- Boot the backend with `sim.enabled=true` for all devices.
- Confirm PLC + camera threads + inference process all start and reach a "ready" state (per Spec 3/4's health-check-visible status).
- Create a session for a known part (`P001`, using the example recipe from Spec 1).
- Start the session.
- Let the simulated pipeline run for a fixed number of parts (e.g. 20).
- Stop the session.
- Assert: `session_measurements`/`part_defects` row count matches the number of verdicts expected; `CompanySession.part_count`/aggregate fields are correct; no events were persisted before Start or after Stop (confirming Spec 5's staged/active gating is real, not assumed).
- Assert: backend shuts down cleanly afterward (regression check against the hang bug class found in the reference simulator — confirm no lingering non-daemon threads/processes).

**Frontend manual test checklist** (document as a checklist in this spec's output, run manually — not necessarily automated in this pass unless a frontend test framework is already set up in the repo):
- [ ] Log in, sidebar shows correct items for the logged-in role
- [ ] Create a new session end to end through the UI (Category → Part → Create Session)
- [ ] Attempting to select a part with no recipe file shows a clear error, doesn't proceed
- [ ] Device Settings page loads and saves camera config correctly
- [ ] Health Check page shows live sim/connected status for all devices, auto-refreshing
- [ ] Non-admin user cannot access admin-only pages/actions

**Bug-fix pass:**
- Any failure found above gets logged as a specific, reproducible issue (not fixed silently mid-test) — fix issues one at a time, re-run the relevant check after each fix, don't batch multiple fixes before re-verifying.

## Explicitly out of scope for this spec

- Testing against real hardware (Arena SDK cameras, real PLC) — sim-only for this pass
- Load/performance testing — functional correctness only at this stage
- The Inspection page UI, Dashboard, Electron shell — none of these exist yet, not tested here

## Definition of done

- Backend integration test passes reliably (run it 3 times in a row, not just once — confirm no flakiness from timing-sensitive ZMQ/threading code)
- Frontend manual checklist fully checked off, with any found issues fixed and re-verified
- A short written summary (a few sentences) of current system state and what's confirmed working, to hand to the team for the next planning pass
