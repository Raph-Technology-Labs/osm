# Spec 10: Inspection Page — Dynamic Camera Grid + Digital Twin

## Goal
Render the inspection page fully from the active recipe (config.yaml), with no
hardcoded station/camera counts. Must scale from 2 cameras to 20+ without
layout breakage, and show the digital twin (slot-based part flow) driven by
live encoder/verdict events.

## Inputs
- Active recipe (stations -> cameras mapping), loaded via config_loader
- Live event stream (per-camera verdict + part_id + preview frame handle),
  delivered Electron main (ZMQ SUB) -> ipcRenderer -> renderer

## Layout rules (grid + pagination)
- Group cameras by station. Never split a station's cameras across pages.
- Fixed page capacity: 2x2 or 3x2 stations per page (decide based on target
  screen resolution — 1920x1080 assumed unless told otherwise). Each station
  cell shows its N cameras side by side within that cell.
- If total stations > capacity for one page: render tabs (Page 1, Page 2, ...)
  above the grid. Tab switch is a pure client-side state change — no refetch.
- Each camera placeholder shows: downscaled preview frame (not full-res),
  current part_id under that camera, live OK/NOK verdict badge.
- Page-level and overall counters: OK / NOK / TOTAL, computed from event
  stream, not re-fetched from DB.
- If a station has more cameras than fit legibly in one cell (design pass:
  probably >4), stack them in a sub-grid within the cell rather than shrinking
  below a legible thumbnail size — flag this case explicitly if hit, don't
  silently shrink to unreadable size.

## Component breakdown (React)
- `InspectionGridPage.jsx` — top-level, owns active recipe + tab state
- `useLiveEvents.js` — hook wrapping ipcRenderer subscription, returns
  per-camera live state keyed by camera_id
- `StationCell.jsx` — renders one station's cameras
- `CameraPlaceholder.jsx` — single camera tile (frame + part_id + verdict)
- `PageTabs.jsx` — tab bar, only rendered if stations > page capacity
- `DigitalTwin.jsx` — SVG-based slot visualization (adapt doc09/doc11
  simulator's SVG approach), driven by live encoder position + verdicts,
  not scripted playback. Legend: empty / in-process / ok-exiting /
  failed-rejecting.
- Wire into `AppRoutes.jsx` replacing the current `/counting/:sessionId`
  and `/batching/:sessionId` PlaceholderPage routes.

## Config reload correctness (bug fix, prerequisite for this spec)
Current `config_loader` reloads `ResolvedMachineConfig` from disk on every
call, even when part_code hasn't changed, and camera hardware objects are
not torn down before new ones are created on reload — this leaks Arena SDK
camera handles.

Fix:
- Cache resolved config keyed by `part_code` (module-level or a small
  `ConfigCache` class); only re-read YAML + rebuild `ResolvedMachineConfig`
  when `part_code` actually changes.
- Camera manager must explicitly close/release existing camera device
  handles (Arena SDK `device.stop_stream()` / de-init) before opening new
  ones on a config change — never let hot-reload silently orphan
  previously-opened camera objects. This must be a proper context-managed
  lifecycle (`__enter__`/`__exit__` or explicit `close()` called in a
  `finally`), not fire-and-forget re-init.
- This fix belongs in `config_loader.py` + wherever camera device objects
  are constructed (Suvendu's Arena SDK layer) — coordinate the interface
  (a `reload(part_code)` method) rather than duplicating cache logic in
  both places.

## Out of scope
- Dashboard charts (separate, already scoped elsewhere)
- Actual Arena SDK strobe/enumeration internals (Suvendu's code — only the
  teardown/lifecycle contract is this spec's concern)
- Backend session/measurement schema changes (none needed — this consumes
  existing live event stream)

## Acceptance criteria
- Recipe with 2 stations / 4 cameras renders correctly, no tabs
- Recipe with 6 stations / 14 cameras renders with tabs, no station split
  across pages
- Switching part (recipe reload) does not leak camera handles — verify via
  process handle count before/after 10 consecutive reloads
- Digital twin reflects live verdict color changes within one polling
  interval of the event arriving