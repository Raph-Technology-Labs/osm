---
name: review-feature
description: Runs parallel ring-math and PLC-safety review for an OSM feature that touched the indexer or Modbus layer.
allowed-tools: Read, Task
disable-model-invocation: true
---

# Review Feature

## Step 1 — Parallel Review

Launch BOTH subagents in parallel:
- `osm-ring-math-reviewer`
- `osm-plc-safety-reviewer`

These are independent — run them concurrently, don't wait for one before
starting the other.

## Step 2 — Unified Report

Merge findings from both into a single report, grouped by which reviewer
raised each finding.

## Step 3 — Approval Gate

If either reviewer recommends a change, ask the user before applying it —
don't auto-fix findings from either reviewer without confirmation, since
these two specifically cover safety-relevant logic (reject escalation,
slot-boundary correctness).

If a change didn't touch the indexer or PLC layer at all, both subagents
should report "not applicable" rather than manufacturing a finding — that's
expected and fine, not a failure of the review.
