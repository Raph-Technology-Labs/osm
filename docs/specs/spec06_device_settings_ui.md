# Spec 6 — Device Settings UI

## Context

Device Settings lets an admin configure camera position/coordinate details per station. This is a frontend-heavy slice that reads/writes machine-level config fields introduced in Spec 1.

Read `specs/08_session_config_lifecycle.md` section 2 (config file shape) before starting. Confirm with Snehal whether the config API for this (reading/writing machine-level camera fields) exists yet from Spec 1's backend work — if not, this spec's backend portion may need to wait, or a minimal read-only endpoint may need to be added as part of this spec (clarify in the plan step, don't assume). Read `CLAUDE.md` for project context.

**Process: present a plan first (files to add/change, function signatures, no full implementations) and wait for confirmation before writing code.**

## Existing files relevant to this task

- `frontend/src/pages/PlaceholderPage.jsx` — currently placeholder for Device Settings, replace with the real page.
- `frontend/src/routes/AppRoutes.jsx` — existing `/device-settings` route.
- `frontend/src/theme/theme.js` — use existing theme tokens, don't hardcode colors.
- `frontend/src/api/axios.js` — existing authenticated axios instance (from the auth slice) — use this for all API calls, don't create a second axios setup.
- `frontend/src/context/AuthContext.jsx` (from the auth slice) — this page should be admin-gated; check role via this context, following whatever pattern Spec 8 (sidebar role-gating) establishes — coordinate timing with that spec if it lands first.

## What to build

**New files:**
- `frontend/src/pages/DeviceSettingsPage.jsx` — form UI: for each physical station/camera (fetched from the backend's machine config, per Spec 1), show editable fields for position/coordinate values. Use MUI form components consistent with the existing app style (see `ModeSelectionPage.jsx` for the visual pattern to follow — cards, theme gradients).
- `frontend/src/api/deviceSettings.js` (or similar) — API client functions: `getMachineConfig()`, `updateCameraPosition(cameraId, values)` (exact backend contract to be confirmed with Snehal during the plan step — this spec should not invent backend behavior unilaterally).

**Behavior:**
- Fields per camera: position/coordinate values (exact fields — x/y offset, angle, whatever the physical setup actually needs — confirm during planning, don't guess a schema that doesn't match Spec 1's actual `MachineConfig`/`Camera` shape).
- Save should show a clear success/error state (MUI `Snackbar` or `Alert`), and should not allow saving invalid values (required fields, numeric ranges) — client-side validation before the API call.
- This page edits **machine-level** config (physical camera setup), not per-part recipes — make sure this distinction is visually clear to the user (e.g. a note explaining "this affects all parts run on this machine").

## Explicitly out of scope for this spec

- Per-part recipe editing (pipeline assignment, tolerances) — that's config that lives in recipe files, not this page
- Health Check's live connected/mode display — separate spec (7), don't merge the two pages
- Backend schema changes beyond what Spec 1 already defines — if a needed field is missing from Spec 1's schema, flag it rather than adding it unilaterally

## Definition of done

- Device Settings page loads real camera/station data from the backend (not placeholder)
- Editing and saving a camera's position values persists correctly (confirm by reloading the page after save)
- Invalid input is rejected client-side with a clear message, never silently sent to the backend
- Only accessible to appropriately-roled users (coordinate with Spec 8)
- No changes to files outside what's listed above
