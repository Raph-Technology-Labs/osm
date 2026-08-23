---
name: vision-pipeline-config
description: Use this skill when writing or editing machine_config.yaml, recipe YAML files, or code that resolves per-part pipeline configuration. Covers the serial-vs-parallel inference convention, calibration_factor placement, and the config resolution flow. Trigger on any mention of defect/measurement pipeline blocks, CategoryRecipe, resolve_config_for_part, or calibration_factor.
---

# Vision Pipeline Config Conventions

## Serial vs. parallel inference is implicit in the YAML shape

Don't add an explicit `mode: serial|parallel` field — the existing convention
encodes it structurally:

- `measurement` block **omits** `model_path` → it reuses `defect`'s raw
  detections, filtered by `allowed_classes`. One inference call. Serial/CMD —
  only valid when `measurement.allowed_cameras` is a subset of
  `defect.allowed_cameras`.
- `measurement` block **has its own** `model_path` → separate inference call.
  Parallel — typically used when measurement needs a camera not in the defect
  set, or a different model entirely.

When adding a new station's pipeline block, decide which of these applies
before writing it, and match the existing pattern rather than inventing a new
shape.

## calibration_factor and conf_thresh are part-specific, never category-wide

Lens distortion varies by part size even within the same category. These
values live on `Part`, not on `CategoryRecipe`. `CategoryRecipe` supplies
*defaults* only, and those defaults get pushed into a `Part`'s own specs via
an explicit `override_from_config` flag — never silently overwritten. If
you're writing code that reads `calibration_factor` from a recipe directly
instead of from the resolved `Part`, that's likely a bug.

## Config resolution flow — don't skip steps

`resolve_config_for_part(db, part_code)` is the single source of truth. It
joins `CategoryRecipe` structure with the `Part`'s own `defect_specs` /
`dimension_specs` / `extra_checks` into one validated `MachineConfig` object,
entirely in memory. Two things that must never happen:

1. `config.yaml` is a **debug snapshot only**, written *after* resolution.
   Never make the engine read it back — if you're writing code that loads
   `config.yaml` at startup or mid-session, that's wrong; it should call
   `resolve_config_for_part()` instead.
2. Recipe YAML files under `recipes/` are the **authoring format only**,
   imported into `CategoryRecipe.recipe_json` via `recipe_import.py`. The
   engine never reads these files live — if you're writing code that opens a
   `recipes/*.yaml` file directly at runtime, route it through the DB instead.

## Aggregation belongs at the reject station, not the config layer

`part_aggregation.pass_if` (e.g. `all_triggers_pass`) is evaluated at runtime,
at the R1/reject station's tick, using every station's stored result up to
that point — not read once from config and cached. If a new aggregation rule
is added (e.g. "any critical defect fails regardless of others"), it goes in
the aggregation evaluation logic, not as a static YAML flag interpreted
elsewhere.
