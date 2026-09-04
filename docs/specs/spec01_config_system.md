# Spec 1 — Config System

## Context

raph-vision runs on a single Linux tower. Machine topology (stations, camera mounts, PLC register map) is fixed per tower and lives in `default_config.yaml`. Each part has its own recipe (`recipes/{part_number}.yaml`) defining which stations/cameras are active, which pipeline runs on each camera, and rejection routing. The active recipe lives in `config.yaml`, which persists across reboots (last-selected part resumes automatically).

Read `specs/06_frozen_architecture_chart.md` and `specs/08_session_config_lifecycle.md` (sections 1–4) before starting — this spec implements exactly what those docs describe. Read `CLAUDE.md` for project context.

**Process: present a plan first (files to add/change, function signatures, no full implementations) and wait for confirmation before writing code.**

## Existing files relevant to this task

- `backend/app/core/config.py` — if it exists from the auth slice (pydantic-settings `Settings` class), extend it; don't duplicate.
- `backend/app/db/db.py` — existing pattern for `get_db()`, follow the same style for any new dependencies.
- Backend folder structure: `app/core/`, `app/schemas/`, `app/routers/` — follow existing conventions from the auth slice.

## What to build

**New files:**
- `backend/app/config/default_config.yaml` — machine-level config: `slot_count`, `pulses_per_rev`, full physical station list (id, offset, kind: load/inspection/reject/exit), full physical camera list per inspection station, PLC register map, actuator map. This is example/placeholder data for now — real values will be filled in when hardware specs are confirmed, but the schema must be correct and complete.
- `backend/app/config/recipes/` — folder for per-part recipe files. Add one example recipe (e.g. `P001.yaml`) matching the shape in `specs/08_session_config_lifecycle.md` section 2.
- `backend/app/schemas/machine_config.py` — Pydantic models: `Station`, `Camera`, `MachineConfig` (matches `default_config.yaml`'s shape).
- `backend/app/schemas/recipe_config.py` — Pydantic models: `RecipeCamera`, `RecipeStation`, `RejectionRouting`, `RecipeConfig` (matches a `recipes/*.yaml`'s shape).
- `backend/app/core/config_loader.py`:
  - `load_machine_config() -> MachineConfig` — loads and validates `default_config.yaml`. Raise a clear, loud exception if missing or invalid (app should not start without it).
  - `load_recipe(part_number: str) -> RecipeConfig` — loads and validates `recipes/{part_number}.yaml`. Raise a specific, catchable exception (e.g. `RecipeNotFoundError`) if the file doesn't exist, so callers can turn it into a clean 404/422 API error.
  - `validate_recipe_against_machine(recipe: RecipeConfig, machine: MachineConfig) -> None` — every station/camera ID referenced in the recipe must exist in the machine config. Raise a clear validation error listing exactly which ID(s) don't match, if any.
  - `activate_recipe(part_number: str) -> RecipeConfig` — loads + validates the recipe, then atomically writes it into `config.yaml`: write to a temp file in the same directory, then `os.replace(tmp_path, "config.yaml")`. Never write directly over the live file.
  - `bootstrap_config_if_needed() -> None` — called once at startup. If `config.yaml` doesn't exist, copy `default_config.yaml` to `config.yaml` (this is the only case where `config.yaml` is seeded from the default rather than from a recipe). If `config.yaml` already exists, do nothing — it already holds the last-active part's recipe (or the bootstrapped default, if no part has ever been selected).
  - `load_active_config() -> RecipeConfig` — loads whatever is currently in `config.yaml`.

**Behavior:**
- On backend startup: call `load_machine_config()` first (hard failure if missing/invalid), then `bootstrap_config_if_needed()`, then `load_active_config()` to get the currently-active recipe into memory.
- `config.yaml` is only ever written by `activate_recipe()` (on part selection) or `bootstrap_config_if_needed()` (first boot only) — no other code path should write to it.
- `default_config.yaml` and files under `recipes/` are treated as read-only by the application — never modified at runtime.

**Tests** (`backend/tests/`):
- `test_load_machine_config_success` / `test_load_machine_config_missing_file`
- `test_load_recipe_success` / `test_load_recipe_not_found`
- `test_validate_recipe_rejects_unknown_station_id`
- `test_validate_recipe_rejects_unknown_camera_id`
- `test_bootstrap_creates_config_from_default_when_missing`
- `test_bootstrap_does_nothing_when_config_already_exists`
- `test_activate_recipe_atomic_write` — simulate an interrupted write (e.g. mock `os.replace` to raise) and confirm `config.yaml` is left in its previous valid state, not corrupted

## Explicitly out of scope for this spec

- `StationManager` (the in-memory runtime object other slices will build on top of this config — that's spec 3/5's concern, this spec only covers loading/validating/activating the files themselves)
- Any HTTP endpoint exposing this to the frontend (spec 5 — session creation — will call `activate_recipe()` as part of `POST /sessions`, not this spec)
- Real machine topology values — `default_config.yaml`'s content is placeholder/example data for now
- Editing config from the UI — file-based only, per the frozen architecture decision

## Definition of done

- `pytest` passes all tests listed above
- Deleting `config.yaml` and restarting the app recreates it from `default_config.yaml` automatically
- Calling `activate_recipe("P001")` with the example recipe correctly overwrites `config.yaml`, and the previous content is fully replaced (verify by inspecting file content, not just no-error)
- Calling `activate_recipe()` with a recipe referencing a station/camera ID not in `default_config.yaml` raises a clear validation error and does NOT touch `config.yaml`
- No changes to files outside what's listed above
