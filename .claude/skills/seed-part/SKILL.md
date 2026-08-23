---
name: seed-part
description: Create a dummy Part + CategoryRecipe pair in the database for local testing
argument-hint: <category> <part_code>
allowed-tools: Read, Bash(python3 *)
disable-model-invocation: true
---

User input: $ARGUMENTS

Step 1 — Extract from arguments:
- category (string, e.g. "bolt")
- part_code (string, e.g. "bolt_m8_test")

If either is missing, tell the user the correct format:
  /seed-part <category> <part_code>

Step 2 — Read `app/models/models.py` to understand the current Part and
CategoryRecipe schema before writing anything. The exact columns matter —
`defect_specs`/`dimension_specs`/`extra_checks` are JSON columns with a
specific shape, don't guess it.

Step 3 — Check whether a CategoryRecipe already exists for `category`.
- If yes, reuse it — don't create a duplicate recipe.
- If no, create a minimal CategoryRecipe with one camera station and a
  plausible pulse_offset (ask the user for the real value if this recipe is
  meant for anything beyond local testing — don't invent a production pulse
  offset).

Step 4 — Create the Part row:
- part_code = the given value
- category = the given value
- defect_specs / dimension_specs: minimal plausible values matching the
  existing schema shape (look at an existing Part row for the pattern, if any
  exist)
- calibration_factor / conf_thresh: part-specific per CLAUDE.md — do not put
  these on the CategoryRecipe

Step 5 — Print the inserted Part and CategoryRecipe (or confirmation that the
existing recipe was reused).

Do not touch PostgreSQL through raw SQL — use the existing SQLAlchemy models
and session, so this respects the same constraints the app itself enforces.
