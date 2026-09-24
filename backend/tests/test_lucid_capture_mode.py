"""LucidCamera capture_mode against a fake arena device -- no hardware.

single_shot: software trigger, one exposure per read_frame(), stale frames
drained first, TriggerArmed awaited. continuous: free-run, trigger off."""

import ctypes
import threading

import pytest

import app.camera.lucid_camera as lucid
from app.camera.camera_driver import CameraConnectionError
from app.camera.lucid_camera import LucidCamera
from app.config.config_loader import CameraConfig


class Node:
    def __init__(self, name, value=None, log=None):
        self.name, self.value, self._log = name, value, log

    def __setattr__(self, key, v):
        object.__setattr__(self, key, v)
        if key == "value" and getattr(self, "_log", None) is not None:
            self._log.append((self.name, v))


class Command:
    def __init__(self, on_execute):
        self._on_execute = on_execute

    def execute(self):
        self._on_execute()


class Buffer:
    def __init__(self, fill, w=4, h=3):
        self.width, self.height = w, h
        self.pbytes = (ctypes.c_ubyte * (w * h))(*([fill] * (w * h)))


class FakeDevice:
    """Frames only appear when triggered (or pre-queued as 'stale')."""

    def __init__(self, armed_after_polls=0):
        self.writes = []
        self.queue: list[Buffer] = []
        self.triggers = 0
        self.requeued = 0
        self._next_fill = 100
        self._armed_polls = armed_after_polls
        self.nodes = {
            n: Node(n, log=self.writes)
            for n in ("TriggerSelector", "TriggerMode", "TriggerSource")
        }
        self.nodes["TriggerArmed"] = self
        self.nodes["TriggerSoftware"] = Command(self._on_trigger)
        self.nodemap = self

    # TriggerArmed node: becomes True after N polls
    @property
    def value(self):
        if self._armed_polls > 0:
            self._armed_polls -= 1
            return False
        return True

    def get_node(self, name):
        return self.nodes[name]

    def _on_trigger(self):
        self.triggers += 1
        self.queue.append(Buffer(self._next_fill))
        self._next_fill += 1

    def get_buffer(self, timeout):
        if not self.queue:
            raise TimeoutError(f"no buffer within {timeout} ms")
        return self.queue.pop(0)

    def requeue_buffer(self, _buf):
        self.requeued += 1


def _camera(mode, device) -> LucidCamera:
    cfg = CameraConfig(
        ip="192.168.7.41",
        resolution={"x": 1920, "y": 1080},
        roi={"x1": 0, "y1": 0, "x2": 1920, "y2": 1080},
        capture_mode=mode,
    )
    cam = LucidCamera("cam2", cfg)
    cam._device = device
    cam._configure_trigger(device.nodemap)
    return cam


def test_single_shot_configures_software_trigger():
    dev = FakeDevice()
    _camera("single_shot", dev)
    assert dev.writes == [
        ("TriggerSelector", "FrameStart"),
        ("TriggerMode", "Off"),
        ("TriggerSource", "Software"),
        ("TriggerMode", "On"),
    ]


def test_continuous_turns_trigger_off_and_never_triggers():
    dev = FakeDevice()
    cam = _camera("continuous", dev)
    assert dev.writes == [("TriggerSelector", "FrameStart"), ("TriggerMode", "Off")]
    dev.queue.append(Buffer(55))  # a free-run frame
    frame = cam.read_frame()
    assert dev.triggers == 0 and frame.shape == (3, 4, 3) and (frame == 55).all()


def test_single_shot_read_triggers_exactly_one_frame():
    dev = FakeDevice()
    cam = _camera("single_shot", dev)
    f1, f2 = cam.read_frame(), cam.read_frame()
    assert dev.triggers == 2
    assert (f1 == 100).all() and (f2 == 101).all()  # each read got its own exposure


def test_single_shot_drains_stale_frame_before_triggering():
    # A late frame from an earlier (timed-out) trigger is waiting: it must be
    # thrown away, not returned as this part's image.
    dev = FakeDevice()
    cam = _camera("single_shot", dev)
    dev.queue.append(Buffer(7))
    frame = cam.read_frame()
    assert (frame == 100).all()
    assert dev.triggers == 1


def test_single_shot_waits_for_trigger_armed():
    dev = FakeDevice(armed_after_polls=3)
    cam = _camera("single_shot", dev)
    cam.read_frame()
    assert dev.triggers == 1


def test_single_shot_not_armed_in_time_fails_loudly(monkeypatch):
    monkeypatch.setattr(lucid, "TRIGGER_ARMED_TIMEOUT_S", 0.01)
    dev = FakeDevice(armed_after_polls=10**9)
    cam = _camera("single_shot", dev)
    with pytest.raises(CameraConnectionError, match="not armed"):
        cam.read_frame()
    assert dev.triggers == 0


def test_single_shot_concurrent_reads_each_get_their_own_frame():
    dev = FakeDevice()
    cam = _camera("single_shot", dev)
    results = []
    threads = [threading.Thread(target=lambda: results.append(int(cam.read_frame()[0, 0, 0]))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == list(range(100, 106))  # no frame returned twice, none lost
    assert dev.triggers == 6


def test_single_shot_is_the_default_capture_mode():
    cfg = CameraConfig(
        ip="192.168.6.41",
        resolution={"x": 1920, "y": 1080},
        roi={"x1": 0, "y1": 0, "x2": 1920, "y2": 1080},
    )
    assert cfg.capture_mode == "single_shot"
