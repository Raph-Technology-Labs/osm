# raph-vision-toolkit — optional, not wired up yet

This is a **draft plugin**, not part of the active OSM `.claude/` setup. It's
here because you have several raph-vision projects (bolt-detection-sks,
kc-diapers-anomaly, lug-inspection, venus-project, ...) that likely share the
same Modbus/PLC register conventions and vision-pipeline config shape — this
packages the *reusable* pieces once instead of copy-pasting them into every
repo.

## What's in it, and what's deliberately left out

- `modbus-register-design.md`, `vision-pipeline-config.md` — copied as-is,
  these are already general (CMD/ACK pairing rules, serial/parallel inference
  convention) — nothing OSM-specific in them.
- `plc-safety-reviewer.md` (renamed from `osm-plc-safety-reviewer`) — same
  reasoning, generally applicable wherever there's a Modbus register layer.
- **Not included:** `indexer-ring-math` skill and `osm-ring-math-reviewer`
  agent. These encode OSM's *specific* slot-count/pulse-offset math and the
  bugs found in *this* project's history — they'd need generalizing (or
  each project keeping its own copy) before belonging in a shared toolkit.
  Don't copy them in here without checking whether every other raph-vision
  project's indexer model actually matches OSM's — if any of them use a
  different tracking approach, this skill would give wrong guidance there.

## To actually use this

1. Turn this into its own GitHub repo (e.g.
   `Raph-Technology-Labs/raph-vision-toolkit`).
2. Add a `.claude-plugin/marketplace.json` at the repo root listing this
   plugin, so other raph-vision repos can add it as a marketplace and install
   from it — see the plugins chapter of the Claude Code guide for the exact
   `marketplace.json` shape.
3. In each project (OSM included, if you want to de-duplicate later), run
   `/plugin` → add this marketplace → install `raph-vision-toolkit`.

This wasn't set up automatically because it's a team/process decision (do you
want one shared toolkit repo, or per-project copies that can drift
independently) — worth deciding deliberately rather than defaulting into it.
