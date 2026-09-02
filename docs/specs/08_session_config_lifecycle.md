# raph-vision — Session Lifecycle & Config Architecture

Consolidates the actual runtime flow: app startup → login → part selection → config load → session start → live inspection → data persistence → dashboard analytics.

---

## 1. One architectural clarification needed before this is fully consistent

You described config files as holding **stations, cameras, rejection stations** — i.e. machine topology — but also said PLC/camera **connections happen at app start**, independent of any part being selected (confirmed: this is what makes Health Check/Device Settings meaningful before a session exists). These two statements only fit together cleanly if there are actually **two levels of config**, not one:

| Level | File | Defines | When loaded |
|---|---|---|---|
| **Machine-level** | `machine_config.yaml` (or `default_config.yaml`) | Physical hardware truth: total installed stations, camera mounts, encoder specs, PLC register map, actuator map — **fixed for this tower, doesn't change per part** | Once, at app startup — this is what the PLC/camera connection threads and Health Check page actually use |
| **Part-level (recipe)** | `config/{part_number}.yaml` | Which of those physical stations are *active* for this part, camera→pipeline mapping, rpm/pulses, tolerances, rejection severity routing — **changes per part** | On part selection, layered on top of the machine-level config |

**This is the proposed reconciliation — flag if this doesn't match your intent.** Without this split, "connect to cameras at app start" and "camera count comes from the part's recipe" contradict each other, since there's no part selected yet at app start. With the split: the machine config tells the app what hardware physically exists and connects to all of it at startup; the part recipe tells the app which of that hardware to *use* and *how* for the currently selected part (e.g. a simple part might only need 2 of the machine's 4 camera mounts active).

This also directly answers what `default_config.yaml` is for: **it's the machine-level config**, always present, always loaded — not "under discussion," it's structurally required for startup/Health Check to work at all before any part is chosen. Worth locking this in rather than leaving it open.

---

## 1a. Testing without full hardware — same config, sim swaps the source only

The temptation is to run a smaller config on your desk (fewer stations/cameras) than what actually ships. Don't — it means testing a different shape of app than the one that deploys. Instead: **`default_config.yaml` always describes the real, final tower topology**, even before you physically have all the hardware. `sim.enabled` (globally, or per-device as an override) decides where each camera's frames / each PLC register's values come from — not how many the app thinks exist:

- `sim.enabled: true` for a camera → a mock source (cycling through a folder of sample images) stands in, same `camera_id`, same place in the topology.
- `sim.enabled: false` → the real Arena SDK device for that ID.
- Same pattern for PLC (`plc_sim` vs real Modbus TCP target).

This means pagination, dashboard aggregation, `PipelineRegistry` fan-out, and rejection routing all get tested against the real station/camera count from day one — switching to production is a `sim.enabled: false` flip plus real device identifiers, not a restructure. Mixed real/sim (some hardware arrived, some hasn't) works naturally via per-device overrides during commissioning.

---



```
backend/app/config/
├── machine_config.yaml          # (= default_config.yaml) machine-level, always present, required to start the app
└── recipes/
    ├── P001.yaml                # part-number-keyed recipe
    ├── P002.yaml
    └── ...
```

**Recipe file (`{part_number}.yaml`) — example shape:**
```yaml
part_number: P001
rpm: 45
pulses_per_rev: 3600            # encoder resolution for this recipe's timing
active_stations:
  - station_id: S1
    cameras:
      - camera_id: cam1
        pipeline: dimension_check_v2
        defect_code: DIM
        severity: critical
  - station_id: S3
    cameras:
      - camera_id: cam1
        pipeline: surface_scratch_v1
        defect_code: SCRATCH
        severity: cosmetic
rejection_routing:
  critical: R1
  cosmetic: R2
```

`active_stations` references station/camera **IDs that must exist** in `machine_config.yaml` — a recipe can use a subset of the machine's physical stations/cameras, never more. Validate this at load time (see §4).

---

## 3. Config activation mechanism — file-copy, confirmed, with persistence as the key benefit

**Decided: `part.yaml` is copied to `config.yaml` on part selection — literal file, not in-memory state.** Revisiting the earlier concern: file-copy actually has a real advantage over the in-memory alternative that was proposed — **persistence across reboots for free**. Since `config.yaml` is a real file on disk, whatever part was last selected stays active even after the machine is power-cycled, with zero extra code needed to save/restore state. An in-memory approach would lose the active recipe on every restart and force re-selecting a part before the app is usable again — worse for your actual use case (a floor machine that gets rebooted and should resume where it left off). Good call.

**Two files, two different roles:**
- `default_config.yaml` — the machine-level config (per §1), **never overwritten**, used only to bootstrap `config.yaml` the very first time the app ever runs on a tower (no part selected yet).
- `config.yaml` — the **active** config: starts as a copy of `default_config.yaml` on first boot, then gets overwritten with `{part_number}.yaml` every time a part is selected. This is what `StationManager`/Coordinator actually load at startup and on every part change.

**Startup logic:**
```
On app start:
  if config.yaml exists:
    load config.yaml           # whichever part was last active, or default
                                 # if no part has ever been selected yet
  else:
    copy default_config.yaml → config.yaml   # first-ever boot on this tower
    load config.yaml
```

**On part selection:**
```
1. Look up config/recipes/{part_number}.yaml
2. Not found → error, do not proceed, config.yaml is left untouched
3. Found → validate against machine-level topology (station/camera IDs
   must exist physically)
4. Valid → write to a temp file, then atomically replace config.yaml
   (os.replace(tmp_path, "config.yaml") — avoids a half-written/corrupted
   config.yaml if the write is interrupted, e.g. power loss mid-write)
5. Reload StationManager/active recipe from the new config.yaml
```

This means: **the machine always boots into whatever part was last run**, with no special "nothing selected yet" state to handle beyond the very first boot ever.

---

## 4. App startup sequence

```
1. Backend process starts (uvicorn)
2. Resolve config.yaml per §3 (load existing, or bootstrap from
   default_config.yaml on first-ever boot)
   → if default_config.yaml itself is missing: app does NOT start,
     fails loudly with a clear error (this file must always exist)
3. StationManager initialized — machine-level topology from
   default_config.yaml's structure, active recipe from config.yaml
4. PLC poll thread starts, connects (real or sim per sim.enabled)
5. Camera capture thread(s) start, connect to all physically configured
   cameras (real or sim per sim.enabled/per-camera override)
6. Health Check / Device Settings pages now have live data to show,
   even with zero sessions and using whatever part was last active
```

**No part-specific recipe needs to be freshly loaded here** — `config.yaml` already reflects the last-active part (or the default, on true first boot), so the app is immediately in a sensible, working state after a reboot.

---

## 4a. Health Check — sim vs real, shown per device, not collapsed into OK/NOK

Sim/mock status and health status are two different facts — keep them separate rather than replacing OK/NOK with a sim indicator, so an operator can see both "is this connected/healthy" and "is this real hardware or a stand-in" at once:

```json
{
  "plc": {
    "connected": true,
    "mode": "sim",
    "last_seen": "2026-09-02T17:14:00Z"
  },
  "cameras": [
    {"id": "cam1", "connected": true, "mode": "real"},
    {"id": "cam2", "connected": true, "mode": "sim"}
  ]
}
```

`mode` reflects whichever `sim.enabled` value actually applied to that specific device (global default or a per-camera override — relevant during partial-hardware commissioning, when some cameras have arrived and some haven't). This is what backs the Health Check page — each device row shows both connectivity and mode, not one collapsed indicator.

---

## 5. Login → New Session → part selection → config load

```
1. User logs in → sidebar options become available
   (per your screenshot: New Session, Add Item, Dashboard, Part Details,
   Health Check, Device Settings)

2. New Session → select Category → select Part

3. On part selection:
   → backend looks for config/recipes/{part_number}.yaml
   → FOUND: load + validate against machine_config.yaml
       (every station_id/camera_id referenced must exist physically)
     → valid: recipe becomes the active recipe for this session-to-be
     → invalid (references a station/camera that doesn't physically exist):
       reject with a clear error, do not proceed
   → NOT FOUND: error shown to user — "No recipe configured for part {X}",
     do not allow session creation to proceed

4. Create Session
   → POST /sessions — creates the CompanySession DB row
     (part_id, mode, counting_type, etc. — existing schema)
   → Session Coordinator is told "session N is pending, recipe = {loaded recipe}"
   → Coordinator does NOT yet persist inspection data or route cameras/PLC
     for this recipe — it's staged, not running
```

## 6. Start button → the indexer actually runs

```
5. User presses "Start" (a SEPARATE action from Create Session, per your
   description — confirms the two-step flow: create, then start)
   → POST /sessions/{id}/start
   → PLC actuator write: start indexer rotation
   → Coordinator switches from "staged" to "active" for session N:
       - encoder position now monitored against the active recipe's
         station offsets
       - as each active station's trigger point is reached, the
         corresponding camera(s) fire, pipeline(s) run
       - verdicts arbitrated per recipe's rejection_routing
       - results persisted to session_measurements / part_defects,
         tied to session N
       - reject-station actuators triggered per verdict
   → Live events published (per doc 06: inproc:// → ipc:// → Electron IPC)
     for the Inspection page to consume
```

## 7. Session end

```
6. User stops the session (explicit stop, or a configured run-length reached)
   → PLC actuator write: stop indexer rotation
   → Coordinator switches session N back to "inactive" — stops persisting
     to it, but PLC/camera background monitoring keeps running (per §4,
     this never stops just because a session ended)
   → CompanySession.session_end set, aggregate counts finalized
```

---

## 8. Live Inspection page — dynamic layout (the part you flagged as tricky)

Since the active recipe's station/camera count varies per part, this page can't be a fixed layout — it has to be **generated from the active recipe** at render time.

**Structure:**
```
Inspection Page
├── Digital twin visualization (top or side panel)
│     — live version of the reference sim's rotating-disc view:
│       station positions, part-in-flight markers, driven by
│       real encoder position + real verdicts, not scripted data
│
├── Station/camera grid, paginated by tab
│     Page/Tab 1: Station 1 [cam1] [cam2]   Station 2 [cam3] [cam4]
│     Page/Tab 2: Station 3 [cam5] [cam6]   ...
│     (however many placeholders fit per page — see layout decision below)
│
└── Counters (shown on every page/tab, not just once):
      This page:  OK: N   NOK: N   Total: N
      Overall:    OK: N   NOK: N   Total: N
```

**Layout sizing — computed from real screen resolution, not hardcoded:** since target screen size varies by tower/monitor, the grid must be computed at render time, not fixed. `ResizeObserver` on the grid container gives real pixel dimensions; combined with a minimum readable cell width and each camera feed's native aspect ratio, this yields exactly how many placeholders fit right now:

```
columns = floor(containerWidth / (cellMinWidth + gap))
cellHeight = (containerWidth / columns) / cellAspectRatio
rows = floor(containerHeight / (cellHeight + gap))
cellsPerPage = columns × rows
```

Group `active_stations` (keeping each station's cameras together, per the Station1→cam1,cam2 / Station2→cam3,cam4 grouping) into pages of up to `cellsPerPage` each, without splitting a station's cameras across pages where avoidable — each page becomes a tab, each tab shows per-page + overall OK/NOK/total counters. Recomputes live via `ResizeObserver` if the Electron window is resized mid-session, so pagination never goes stale.

**Each placeholder shows:** the live/preview frame for that camera (per doc 06 — downscaled JPEG via ZMQ→Electron IPC, not full-res), plus the part ID currently under that camera (from the latest event for that station/camera).

---

## 9. Data → Dashboard

```
session_measurements / part_defects (per-session, per-camera results)
   → Dashboard queries aggregate across sessions:
       - counts by part, by date range, by defect type
       - OK/NOK ratios → pie charts
       - throughput over time → line/bar charts
   → This is a straightforward read/aggregate API on top of existing
     schema — no new tables needed, just aggregation queries + endpoints
```

---

## 10. What needs to be built — task breakdown

**Backend**
- [ ] Pydantic schemas: `MachineConfig` (default_config.yaml shape), `RecipeConfig` (per-part shape)
- [ ] Config loader + validator (recipe's station/camera IDs must exist in machine-level topology)
- [ ] `config.yaml` bootstrap-from-default logic (first boot only) + atomic write on part-selection copy
- [ ] `StationManager` — holds machine-level topology (from default_config.yaml structure) + active recipe (from config.yaml), reloadable on part change
- [ ] Camera mock source (per doc discussion above) — same interface as the real Arena SDK wrapper, reads sample images, so full topology testable without hardware
- [ ] `PipelineRegistry` (per doc 06 — unchanged)
- [ ] Part selection endpoint — validate + atomically write config.yaml, error clearly if recipe missing
- [ ] `POST /sessions` — create (staged, not running)
- [ ] `POST /sessions/{id}/start` — actually start indexer + begin persisting
- [ ] `POST /sessions/{id}/stop` — stop indexer + finalize session
- [ ] `GET /health` — per-device connected + mode (sim/real), per §4a schema
- [ ] Live event stream content: per-camera verdict + part ID + preview frame handle
- [ ] Dashboard aggregation endpoints (counts, defect breakdown, throughput)

**Frontend**
- [ ] New Session flow: Category → Part (existing placeholders, needs real data + recipe-missing error handling)
- [ ] Inspection page: dynamic grid generator from active recipe, station-grouped pagination/tabs, per-page + overall OK/NOK/total counters
- [ ] Digital twin component — adapt the reference sim's visual approach, driven by live encoder position + verdicts instead of scripted playback
- [ ] Health Check page: per-device connected/mode display (§4a)
- [ ] Dashboard charts (pie/bar) wired to the new aggregation endpoints
- [ ] `useGridCapacity` hook (ResizeObserver-driven column/row calculation) + pagination logic grouping stations into tabs

**Resolved this round**
1. ~~Two-level config model~~ — confirmed: `default_config.yaml` (machine-level, immutable) + `config.yaml` (active, overwritten on part selection)
2. ~~default_config.yaml purpose~~ — confirmed: loaded only when `config.yaml` doesn't exist yet (true first boot); never read again once `config.yaml` is populated
3. ~~In-memory vs file-copy~~ — confirmed: file-copy, specifically because it gives reboot persistence (last-active part resumes automatically) for free
4. ~~Sim testing without real hardware~~ — confirmed: same `machine_config`/`config.yaml` topology in dev and prod, `sim.enabled` (global or per-device) swaps data source only, never the shape
5. ~~config.yaml revert path~~ — confirmed: changes only via part selection, no separate "revert to default" action
6. ~~Camera placeholders per page~~ — confirmed: computed live from actual screen resolution (`ResizeObserver` + aspect ratio + min cell width), not a fixed number — see §8

**Still open**
- None currently — revisit if new questions surface while building
