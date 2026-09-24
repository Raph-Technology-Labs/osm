"""discover_device(): fast scan first, shared between cameras in one
session start, slow scan only when the camera wasn't seen. Fake arena
system -- no hardware."""

import pytest

import app.camera.lucid_camera as lucid
from app.camera.lucid_camera import (
    DISCOVERY_FAST_TIMEOUT_MS,
    DISCOVERY_SLOW_TIMEOUT_MS,
    discover_device,
)

CAM1 = {"ip": "192.168.6.41", "model": "TRT023S-M"}
CAM2 = {"ip": "192.168.7.41", "model": "TRI023S-C"}


class FakeSystem:
    """device_infos answers depend on the timeout in force, like the real
    broadcast: `late` devices only reply within the slow timeout."""

    def __init__(self, fast=(CAM1, CAM2), late=()):
        self.fast, self.late = list(fast), list(late)
        self.DEVICE_INFOS_TIMEOUT_MILLISEC = 1000
        self.scans: list[int] = []

    @property
    def device_infos(self):
        self.scans.append(self.DEVICE_INFOS_TIMEOUT_MILLISEC)
        if self.DEVICE_INFOS_TIMEOUT_MILLISEC >= DISCOVERY_SLOW_TIMEOUT_MS:
            return self.fast + self.late
        return list(self.fast)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def _clear_cache():
    lucid._discovery_cache = None
    yield
    lucid._discovery_cache = None


def test_found_with_one_fast_scan():
    system = FakeSystem()
    match, _ = discover_device(system, CAM2["ip"], clock=Clock())
    assert match == CAM2
    assert system.scans == [DISCOVERY_FAST_TIMEOUT_MS]


def test_second_camera_in_same_session_start_reuses_the_scan():
    system, clock = FakeSystem(), Clock()
    discover_device(system, CAM1["ip"], clock=clock)
    clock.t += 1.0  # next camera, a second later
    match, _ = discover_device(system, CAM2["ip"], clock=clock)
    assert match == CAM2
    assert system.scans == [DISCOVERY_FAST_TIMEOUT_MS]  # still one scan


def test_stale_cache_triggers_a_fresh_scan():
    system, clock = FakeSystem(), Clock()
    discover_device(system, CAM1["ip"], clock=clock)
    clock.t += 60.0  # next session start, a minute later
    discover_device(system, CAM1["ip"], clock=clock)
    assert system.scans == [DISCOVERY_FAST_TIMEOUT_MS, DISCOVERY_FAST_TIMEOUT_MS]


def test_late_answering_camera_found_by_slow_fallback():
    system = FakeSystem(fast=[CAM1], late=[CAM2])
    match, _ = discover_device(system, CAM2["ip"], clock=Clock())
    assert match == CAM2
    assert system.scans == [DISCOVERY_FAST_TIMEOUT_MS, DISCOVERY_SLOW_TIMEOUT_MS]


def test_missing_camera_returns_none_with_everything_seen():
    system = FakeSystem(fast=[CAM1])
    match, infos = discover_device(system, "192.168.7.99", clock=Clock())
    assert match is None
    assert [d["ip"] for d in infos] == [CAM1["ip"]]
    assert system.scans == [DISCOVERY_FAST_TIMEOUT_MS, DISCOVERY_SLOW_TIMEOUT_MS]


def test_cached_scan_missing_the_camera_is_not_trusted():
    # Camera 2 was off during the first scan and powered up since: a cache
    # miss must rescan rather than report it missing.
    system, clock = FakeSystem(fast=[CAM1]), Clock()
    discover_device(system, CAM1["ip"], clock=clock)
    system.fast = [CAM1, CAM2]
    match, _ = discover_device(system, CAM2["ip"], clock=clock)
    assert match == CAM2
