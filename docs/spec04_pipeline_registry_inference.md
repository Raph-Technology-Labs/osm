# Spec 4 — Pipeline Registry & Inference Worker

## Context

Defect detection uses an already-trained model — this spec wraps it behind a common interface and runs it in a separate OS process (per doc 06: CPU/GPU-bound inference must not run inside the FastAPI event loop or the PLC/camera threads, since it would block them under the GIL). Adding a new client's model later should mean writing one new pipeline class and adding one config line — nothing else in the system changes.

Read `specs/06_frozen_architecture_chart.md` before starting, and the model registry discussion from the architecture conversation (dispatch by name, one worker process holding the whole registry, loaded once at startup). Read `10_pipeline_runtime_simulator.py`'s `inference_worker()` function — it's a working reference for the process structure and ZMQ wiring this spec implements for real. Read `CLAUDE.md` for project context.

**Process: present a plan first (files to add/change, function signatures, no full implementations) and wait for confirmation before writing code.**

## Existing files relevant to this task

- `backend/app/runtime/camera_thread.py` (from spec 3) — this spec adds the ZMQ PUSH from the camera thread to the inference process; coordinate with spec 3's structure rather than duplicating the camera thread.
- `backend/app/schemas/recipe_config.py` (from spec 1) — recipe camera entries reference a `pipeline` name by string; this spec is what makes that string resolve to actual code.

## What to build

**New files:**
- `backend/app/pipelines/base.py` — `Verdict` dataclass (`pass_fail: bool`, `defect_code: str | None`, `severity: str | None`, `confidence: float | None`, `measured_values: dict | None`) and `DefectPipeline` protocol/ABC with a `run(frame) -> Verdict` method.
- `backend/app/pipelines/<model_name>.py` — one file wrapping the actual already-trained model. Ask before writing: what format is the model in (file path, framework), and what does its existing `predict`/inference call currently look like? Wrap that existing call inside `run()`, translating its output into a `Verdict`. Do not retrain or modify the model itself.
- `backend/app/pipelines/registry.py` — `PIPELINE_REGISTRY: dict[str, DefectPipeline]`, built once at worker startup (instantiating each pipeline class — this is where model weights actually get loaded into memory, so it must happen once, not per frame).
- `backend/app/runtime/inference_worker.py` — the `multiprocessing.Process` target function: binds a ZMQ PULL socket (`ipc://.../frames.sock`) and a ZMQ PUSH socket (`ipc://.../verdicts.sock`), builds `PIPELINE_REGISTRY` once, then loops: receive a frame job (`{station_id, camera_id, pipeline, part_id, frame_ref}`), look up the pipeline by name, call `.run()`, push the resulting verdict back.
- Update `backend/app/runtime/camera_thread.py` (from spec 3) — when a frame is captured, look up which pipeline(s) apply (from the active recipe, per camera) and PUSH a frame job to the inference worker's frame-input socket, instead of just publishing a status notice.
- Update `backend/app/runtime/lifecycle.py` (from spec 3) — start the inference worker process alongside the existing threads, with the same clean-shutdown discipline (`process.terminate()` + `join(timeout=...)`).

**Behavior:**
- Frame data handoff: for this spec, passing frame bytes directly through the ZMQ message is acceptable (simplicity first, per earlier discussion) — do not implement `multiprocessing.shared_memory` in this spec unless frame sizes turn out to make this a measured problem. Note this as a possible future optimization in a code comment, not something to build preemptively.
- If a `pipeline` name in a job doesn't exist in `PIPELINE_REGISTRY`, log clearly and return an error verdict rather than crashing the worker process.
- The worker process must be resilient to a single bad frame/job — one failure should not take down the whole process (wrap the per-job handling in a try/except that logs and continues).

**Tests:**
- `test_pipeline_registry_loads_all_registered_pipelines`
- `test_wrapped_model_returns_valid_verdict_shape` — run the actual wrapped model against a sample frame, confirm the `Verdict` fields are populated sensibly (exact accuracy isn't the test here, shape/plumbing correctness is)
- `test_inference_worker_end_to_end` — send a frame job in, confirm a verdict comes out on the verdicts socket
- `test_inference_worker_handles_unknown_pipeline_gracefully`
- `test_inference_worker_survives_bad_frame`

## Explicitly out of scope for this spec

- `multiprocessing.shared_memory` zero-copy frame transport — deferred, note as a comment only
- Multiple inference worker processes / pooling — one persistent worker process is sufficient for this spec unless you discover during planning that the existing model(s) are too heavy to share one process (flag this during the plan step if so, don't decide unilaterally)
- Coordinator logic that consumes these verdicts and persists to DB — spec 5
- Training or modifying the model itself

## Definition of done

- `pytest` passes all tests listed above
- Running the backend, a captured (mock) frame results in a verdict appearing on the verdicts ZMQ socket within a reasonable time
- Killing/restarting the inference process (simulate a crash) doesn't crash the main backend process — document current behavior even if full auto-restart isn't built yet (flag as a follow-up if out of scope for this pass)
- No changes to files outside what's listed above
