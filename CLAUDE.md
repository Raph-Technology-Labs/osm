# OSM (Optical Sorting Machine) — Project Context

## 1. Project Overview

Rotary-indexer machine vision inspection system, built on the raph-vision
platform. Inspects parts at multiple camera stations, aggregates results, and
drives a PLC-actuated reject via Modbus TCP.

## 2. Architecture

- `app/models/models.py` — SQLAlchemy schema (7 tables: users, categories,
  parts, part_configs/CategoryRecipe, part_sessions, session_results,
  camera_results)
- `app/indexer/tracker.py` — `IndexerSlotTracker`: pulse handling, slot math
- `app/indexer/dispatcher.py` — routes by station type (camera / reject / exit)
- `app/plc/modbus_client.py` — register R/W
- `app/plc/watchdog.py` — heartbeat + ACK timeout monitoring, owns `STOP_COMMAND`
- `app/pipeline/` — `PipelineContext`, `ModelRegistry`, defect/measurement steps
- `recipes/*.yaml` — human-authored category recipes, imported via
  `recipe_import.py`, never read live by the engine
- `config.yaml` — debug snapshot only, written after `resolve_config_for_part()`,
  never read back

*(Adjust paths above to match the actual repo once code lands — these are
best-guess from design discussion, not verified against the real tree.)*

## 3. Code Style

- Python: PEP 8, type hints on all public functions
- Docstrings explain *why* for anything touching the register list or slot
  math, not just *what*
- Prefer targeted diffs over full-file rewrites when fixing existing code
- Threading, not multiprocessing, for the vision pipeline — GPU/OpenCV ops
  release the GIL; `ModelRegistry` is a thread-safe singleton specifically to
  avoid duplicating GPU memory across stations

## 4. Preferred Libraries & Tools

FastAPI, PostgreSQL, Redis, ZeroMQ, Modbus TCP (pymodbus), React 19,
PyTorch/YOLO/TensorRT, OpenCV. Don't introduce a new web framework, ORM, or
message broker without discussing it first — this stack is settled.

## 5. Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server
uvicorn app.main:app --reload

# Run tests
pytest

# Run only the indexer tracker tests
pytest tests/test_indexer_tracker.py -q
```

## 6. Critical Rules — do not violate without flagging it explicitly

1. **The PC owns all slot tracking. The PLC does not run its own copy of the
   ring buffer.** PLC only streams pulse count/heartbeat + entry sensor +
   reject/OK acks. Camera stations never wait on a PLC trigger register — the
   PC fires them itself.

2. **`PULSE_COUNT` resets to 0 every revolution.** Never divide this register
   directly for slot-boundary math. Always route through the wrap-corrected
   internal accumulator (see `indexer-ring-math` skill).

3. **The reject decision (`part_aggregation.pass_if`) is evaluated at the R1
   (reject) station tick — never at Exit.** R1 physically discards NOK parts
   via a blower; the part is gone from the ring at that point. Exit only ever
   sees parts that already passed.

4. **Every `_CMD` register gets a matching `_ACK`, with a timeout.** Missed
   `REJECT_ACK` escalates to `STOP_COMMAND` (a NOK part may have escaped —
   safety-critical). Missed `OK_ACK` only raises `FAULT_STATUS` (likely a jam).

5. **Machine spec is config-driven, not hardcoded.** `n_slots`, `encoder_cpr`,
   `heartbeats_per_slot`, and every station's `pulse_offset` come from
   `machine_config.yaml` / `CategoryRecipe`, computed per part size.

6. Never commit `.env`, PATs, or DB connection strings. They're gitignored —
   keep it that way.

## When context is missing

If a task needs actual current register addresses, part spec, or station
layout and they're not in this repo's recipe YAML, ask rather than inventing
plausible-looking values — register addresses in particular must match the
real PLC program, not just be internally consistent.
