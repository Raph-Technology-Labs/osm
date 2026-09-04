"""Loads and caches inference models by model_path, so N cameras on the
same weights (e.g. cam1's measurement and cam2's defect both on
yolo11n.pt) share one loaded model instead of loading it N times -- per
CLAUDE.md's "avoid duplicating GPU memory across stations" rule.

Sharing the model is not the same as running it concurrently: ultralytics'
YOLO object keeps mutable per-call state (its internal Predictor reuses
batch/results buffers across .predict() calls), so two camera threads
calling .predict() on the *same* shared model at once can corrupt each
other's results. predict() below takes a per-model_path lock to serialize
calls to a shared model, while cameras on *different* models still run
fully in parallel.
"""

from __future__ import annotations

import os
import threading

import torch

# machine_config.yaml uses container-style absolute paths (e.g.
# /models/pt/yolo11n.pt) matching a future Docker bind-mount of
# backend/models/ at /models -- resolve that prefix against the local dir.
MODELS_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "models")


def resolve_model_path(model_path: str) -> str:
    if model_path.startswith("/models/"):
        return os.path.join(MODELS_ROOT, model_path[len("/models/"):])
    return model_path


_models: dict = {}
_model_locks: dict[str, threading.Lock] = {}
# Camera stations each fire on their own thread (station_registry.fire_station)
# -- guards _models/_model_locks themselves (dict writes), not inference.
_registry_lock = threading.Lock()


def get_model(model_path: str, model_type: str):
    """Return the cached model for model_path, loading it on first use."""
    if model_type != "yolo":
        raise ValueError(f"only model_type='yolo' is supported today, got {model_type!r}")

    with _registry_lock:
        model = _models.get(model_path)
        if model is None:
            from ultralytics import YOLO  # deferred: heavy import, only pay for it if used

            resolved_path = resolve_model_path(model_path)
            if not os.path.isfile(resolved_path):
                raise FileNotFoundError(f"model_path {model_path!r} not found: {resolved_path}")

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = YOLO(resolved_path).to(device)
            _models[model_path] = model
            _model_locks[model_path] = threading.Lock()

        return model


def predict(model_path: str, model_type: str, frame, conf: float, verbose: bool = False):
    """Run inference on a shared model. Loads/caches via get_model(), then
    serializes calls to that specific model_path -- cameras on other models
    aren't blocked by this."""
    model = get_model(model_path, model_type)
    with _model_locks[model_path]:
        return model.predict(frame, conf=conf, verbose=verbose)
