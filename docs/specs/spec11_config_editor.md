# Spec 11 — Config Editor Page

Per `CLAUDE.md` Section 3, page 7: "recipe editor (part name, category with
add-new, indexer pitch/CPR editable) — this is the authoring UI for the
same YAML schema already established, must stay in sync with it, not
diverge into a separate shape." This spec follows `docs/specs/TEMPLATE.md`'s
format and targets the actual, currently-running config system
(`backend/app/config/config_loader.py` + `machine_config.yaml`) — **not**
the `default_config.yaml`/`recipes/`/`config.yaml` design in spec01–09,
which was never built (see the open question in `08_session_config_lifecycle.md`
and `frozen_architecture_chart.md`: those describe an architecture that
doesn't exist in this repo and was superseded before implementation).

## 1. Problem Statement

Every field in `machine_config.yaml` is currently hand-edited on disk —
indexer geometry, PLC connection/registers, stations, cameras, pipelines
(defect/measurement config). There is no UI for it, and `CLAUDE.md` Section
3 lists this as page 7 of the required page set. Right now, changing
anything (a station offset, a camera's ROI, a defect model's confidence
threshold) means SSHing into the tower and hand-editing YAML with no
validation until the next backend restart fails or silently misbehaves.

**Open question, must be resolved before implementation, not during it:**
`PartConfig.config_yaml` (in the `part_configs` DB table, versioned via
`PartConfig.version`/`is_active`, already populated by `app/seed.py`) is
**not** what the running app actually reads — `resolve_config_for_part()`
reads `machine_config.yaml` directly from disk, ignoring `PartConfig`
entirely. `seed.py`'s `build_config_yaml()` even produces a different
shape (`station_1`/`station_2`/`mode_of_operation`) than
`machine_config.yaml`'s real shape (`stations[]` with
`pipeline.defect`/`pipeline.measurement`). Building this editor against
`PartConfig.config_yaml` as it stands today would edit something the app
doesn't run against — exactly what `CLAUDE.md`'s "must stay in sync with
it, not diverge into a separate shape" warns against. Decide one of:

- (a) Retire `PartConfig.config_yaml`'s current shape; repurpose the
  table to store versioned snapshots of the *real* `machine_config.yaml`
  shape instead (gives the audit-log/version-history requirement below
  for free via existing columns), or
- (b) Keep `PartConfig` for whatever it's actually for today (its
  `dimensions`/`defects` JSON columns on `Part` already round-trip through
  `seed.py` and `config_loader._merge_part_overrides`'s seam) and have
  this editor write `machine_config.yaml` directly, with its own separate
  versioning/audit mechanism.

(a) is recommended — it reuses schema that already exists (`version`,
`is_active`, `created_by`, `created_at`, `notes` on `PartConfig`) for the
audit-log requirement below, rather than building a second one.

## 2. Functional Requirements

- View and edit the full resolved config: machine info (`part_code`,
  `part_name`), indexer geometry (`diameter_mm`, `part_size_mm`,
  `tolerance_pct`, `encoder_cpr` — **not** a raw `n_slots` field; that's
  derived, see Constraints), PLC connection (`ip`, `port`, `vendor`,
  `speed_setpoint_rpm`, `watchdog_timeout_ms`), stations (add/remove/
  reorder, `station_offset_pulses`, `source.type`), cameras per station
  (`ip`, `vendor`, `resolution`, `roi`, `fps`, `sim` block), and each
  station's `pipeline.defect`/`pipeline.measurement` blocks.
- Category management: list, add-new (matches `Category` table, already
  read by `GET /parts/categories`).
- Part management: list by category (already `GET /parts`), add-new,
  edit `part_name`/`part_weight`/`dimensions`/`defects` (all already
  columns on `Part`).
- **Station-offset preview**: given the current `stations[]` list and
  derived `n_slots`/`pulses_per_slot`, show each station's position in
  slot units (`round(station_offset_pulses / pulses_per_slot)` — the
  exact formula `IndexerSlotTracker.station_offsets` and
  `GET /inspection/config`'s `stations[].slot_offset` already use) before
  saving, so a bad `station_offset_pulses` value is visible before it's
  live.
- **Validation before save**, surfaced in the UI, not just a 500 on
  submit: every `pipeline.defect.allowed_defects`/`measurement.allowed_classes`
  reference must resolve; `encoder_cpr` must be evenly divisible by the
  *derived* `n_slots` (see Constraints — this already raises a clear
  `pydantic.ValidationError` server-side via `IndexerConfig.cpr_divisible_by_slots`,
  the editor's job is to surface that error inline against the right
  field, not just show a raw 422 body); exactly one `type: exit` station.
- **Audit log**: every saved change recorded (who, when, what changed) —
  see the recommended resolution to the Open Question above for how this
  reuses existing schema.
- Changes take effect on the *next* session start (`resolve_config_for_part()`
  already caches by `part_code` — see Constraints), not live mid-session.

## 3. API / Interface Contract

| Aspect | Description |
|---|---|
| Input | `GET /config/machine` — full resolved config, editable-field shape. `PUT /config/machine` — full replacement, validated server-side via the existing `ResolvedMachineConfig` pydantic model before any write. `GET /config/history` / `POST /config/{version}/restore` — audit log per the Open Question's recommended resolution. `POST /parts`, `PUT /parts/{part_id}`, `POST /parts/categories` — extends the existing read-only `app/routers/parts.py`. |
| Output | `PUT /config/machine` returns the re-resolved config (so the UI can show the *actual* derived `n_slots`/station slot-offsets after save, not just echo the input) or a structured validation error keyed by field path. |

## 4. Constraints

- **`n_slots` is derived, never a direct input field** — `IndexerConfig.n_slots`
  (`backend/app/config/config_loader.py`) is a computed `@property`
  (`floor(π × diameter_mm / (part_size_mm × (1 + tolerance_pct/100)))`),
  not a stored value, as of tonight's work. `CHECKLIST.md`'s original
  "n_slots override with validation" line predates this and is stale —
  the editor exposes `diameter_mm`/`part_size_mm`/`tolerance_pct` and
  shows the *resulting* `n_slots` read-only, it does not let someone type
  a conflicting `n_slots` directly.
- **`resolve_config_for_part()` caches by `part_code`** (also from
  tonight's work) — after a save, the editor must account for this cache
  when deciding when the new config actually takes effect (next session
  start reads fresh only if the cache is invalidated for that part_code;
  decide whether `PUT /config/machine` clears the cache immediately or a
  restart is required, and say so in the UI).
- No real hardware limits to encode yet — every numeric field in
  `machine_config.yaml` today is explicitly commented `PLACEHOLDER`. The
  editor validates shape/consistency (divisibility, reference integrity),
  not real physical limits nobody has confirmed (`CLAUDE.md`'s "ask,
  don't invent" rule).
- Role-gated: per `CLAUDE.md` Section 2's table, config editing is a
  Super Admin action, not Admin or Operator — apply
  `Depends(require_role("superadministrator"))` (see `app/auth/dependencies.py`,
  built earlier tonight) to every write endpoint here.

## 5. Edge Cases & Error Handling

| Edge case | How to handle |
|---|---|
| Edited `encoder_cpr` no longer divisible by the derived `n_slots` | Reject with the existing `IndexerConfig.cpr_divisible_by_slots` validator's message, surfaced against the `encoder_cpr` field specifically |
| Pipeline block references a camera not in that station's `cameras` map | Reject — mirrors `InspectionStation.validate_camera_refs`'s existing check |
| Two `type: exit` stations, or zero | Reject — mirrors `ResolvedMachineConfig.exactly_one_exit_station`'s existing check |
| Save while a session is active | Reject, or queue-and-apply-on-stop — decide explicitly, don't leave implicit; a live station/camera topology change mid-session is undefined behavior today |
| Concurrent edits (two Super Admins editing at once) | Optimistic concurrency check against the audit log's latest version, reject the second save with a conflict rather than silently overwriting |
| PLC ACK never arrives | Not applicable — this spec is pure config editing, no live PLC register write happens here (that's `POST /inspection/speed` and the actuator endpoints, already built) |

## 6. Acceptance Criteria

The feature is considered complete if:

- [ ] The Open Question in Section 1 is explicitly resolved (which
      storage the editor writes to) before any code is written
- [ ] Editing and saving `diameter_mm`/`part_size_mm`/`tolerance_pct`
      shows the resulting derived `n_slots` and per-station slot-offset
      preview before commit
- [ ] Saving a config with `encoder_cpr` not divisible by the derived
      `n_slots` is rejected with a clear, field-targeted error, not a raw
      500/422
- [ ] Every save is recorded in a retrievable audit log (who, when, diff
      or full snapshot)
- [ ] Category/part add-new works end-to-end against the existing
      `Category`/`Part` tables, consistent with `app/routers/parts.py`'s
      existing read endpoints
- [ ] Only `superadministrator`-role tokens can reach any write endpoint
      (verified the same way `test_role_enforcement`-style checks were
      done for actuators tonight — 403 for lower roles, 200 for
      superadmin)
- [ ] No changes to `machine_config.yaml`'s on-disk schema itself — this
      spec is a UI/API layer on top of the schema already established by
      `config_loader.py`, not a redesign of it

---

*Per `TEMPLATE.md`: this spec is reviewed before a Technical Design Plan
is written, and that Plan is reviewed before implementation begins. The
Open Question in Section 1 is the one thing in here that most needs a
human decision before either of those next steps — it changes which
tables/files the whole feature touches.*
