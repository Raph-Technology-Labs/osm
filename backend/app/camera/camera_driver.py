"""Vendor-agnostic camera driver contract. Every camera SDK integration
(LucidCamera today, any future make) implements this -- station_registry.py
and inspection_session.py only ever talk to CameraDriver, never to a
vendor's SDK directly. See driver_registry.py for the vendor-name -> class
lookup that keeps them decoupled, and lucid_camera.py for the first real
implementation (Lucid Vision Labs, via their Arena SDK).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from app.config.config_loader import CameraConfig


class CameraConnectionError(RuntimeError):
    """A real camera failed to connect, or a capture failed mid-session.
    Callers must degrade gracefully -- mark the station unavailable, don't
    crash the dispatcher thread or session start over one bad camera
    (CLAUDE.md's camera-disconnect-mid-session rule)."""


class CameraDriver(ABC):
    """One instance per physical camera. connect() runs once, at
    session-wiring time; read_frame() once per capture trigger; close() on
    session teardown/app shutdown -- must be safe to call even if connect()
    was never called or failed."""

    def __init__(self, camera_id: str, config: "CameraConfig"):
        self.camera_id = camera_id
        self.config = config

    @abstractmethod
    def connect(self) -> None:
        """Raise CameraConnectionError on failure."""

    @abstractmethod
    def read_frame(self) -> np.ndarray:
        """Grab and return one frame as a BGR ndarray -- same convention as
        cv2.imread/sim_frame_provider, so pipeline/defect.py and
        pipeline/measurement.py need no vendor-specific branching."""

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...
