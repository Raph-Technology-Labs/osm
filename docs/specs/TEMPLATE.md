# Spec: <Feature Name>

Write the What and Why here — non-technical, tech-stack-agnostic. The
Technical Design Plan (a separate document, written after this one is
reviewed) covers the How.

## 1. Problem Statement

Why are we building this? What's broken or missing without it?

## 2. Functional Requirements

What exactly will the feature do? Plain bullet list, no implementation detail.

## 3. API / Interface Contract

What goes in, what comes out. For OSM features touching the indexer/PLC
layer, this includes: which registers are read/written, in which direction,
and what triggers the interaction — not how it's implemented internally.

| Aspect | Description |
|---|---|
| Input | |
| Output | |

## 4. Constraints

Performance, timing, hardware limits. For anything touching the indexer:
state the pulse/cycle-time budget explicitly if relevant — don't leave
timing constraints implicit.

## 5. Edge Cases & Error Handling

| Edge case | How to handle |
|---|---|
| | |

For OSM features: always include the "PLC ACK never arrives" case explicitly,
even if the answer is "not applicable to this feature" — it's easy to forget
and expensive to discover in production.

## 6. Acceptance Criteria

The feature is considered complete if:

- [ ]
- [ ]
- [ ]

---

*This spec is reviewed before writing a Technical Design Plan, and the
Technical Design Plan is reviewed before implementation begins. Both review
steps are not optional — they're what catches a wrong assumption before it's
baked into code. See CLAUDE.md's Critical Rules before writing a spec for
anything touching the indexer or register list — those aren't feature
decisions, they're already-settled invariants.*
