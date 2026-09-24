"""LucidCamera config handling against a fake GenICam nodemap -- no
arena_api or hardware needed. Covers the camera-driven strobe
(CameraConfig.strobe), color / pixel-format selection and Bayer conversion,
and fixed exposure/gain."""

import numpy as np
import pytest

from app.camera.lucid_camera import LucidCamera, select_pixel_format, to_bgr
from app.config.config_loader import CameraConfig, load_machine_config, resolve_config_for_part


class FakeNode:
    def __init__(self, name, value, writable=True, log=None):
        self.name = name
        self._value = value
        self.is_writable = writable
        self._log = log

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        if not self.is_writable:
            raise RuntimeError(f"{self.name} is not writable")
        self._log.append((self.name, v))
        self._value = v


class FakeNodemap:
    def __init__(self, line_mode_writable=True):
        self.writes = []
        self.nodes = {
            "LineSelector": FakeNode("LineSelector", "Line0", log=self.writes),
            "LineMode": FakeNode("LineMode", "Output", line_mode_writable, log=self.writes),
            "LineSource": FakeNode("LineSource", "Off", log=self.writes),
            "LineInverter": FakeNode("LineInverter", False, log=self.writes),
        }

    def get_node(self, name):
        return self.nodes[name]


def _camera(**strobe) -> LucidCamera:
    cfg = CameraConfig(
        ip="192.168.7.41",
        resolution={"x": 1920, "y": 1080},
        roi={"x1": 0, "y1": 0, "x2": 1920, "y2": 1080},
        strobe=strobe,
    )
    return LucidCamera("cam2", cfg)


def test_strobe_defaults_to_disabled():
    cfg = CameraConfig(
        ip="192.168.6.41",
        resolution={"x": 1920, "y": 1080},
        roi={"x1": 0, "y1": 0, "x2": 1920, "y2": 1080},
    )
    assert cfg.strobe.enabled is False
    assert cfg.strobe.line == "Line1"


def test_enabled_strobe_drives_line_with_exposure_active():
    nm = FakeNodemap()
    _camera(enabled=True)._configure_strobe(nm)
    assert nm.writes == [
        ("LineSelector", "Line1"),
        ("LineMode", "Output"),
        ("LineSource", "ExposureActive"),
        ("LineInverter", False),
    ]


def test_inverted_strobe_sets_line_inverter():
    nm = FakeNodemap()
    _camera(enabled=True, inverted=True, line="Line2")._configure_strobe(nm)
    assert ("LineSelector", "Line2") in nm.writes
    assert nm.nodes["LineInverter"].value is True


def test_disabled_strobe_leaves_lines_untouched():
    nm = FakeNodemap()
    _camera(enabled=False)._configure_strobe(nm)
    assert nm.writes == []


def test_read_only_line_mode_is_skipped_not_fatal():
    nm = FakeNodemap(line_mode_writable=False)
    _camera(enabled=True)._configure_strobe(nm)
    assert ("LineMode", "Output") not in nm.writes
    assert nm.nodes["LineSource"].value == "ExposureActive"


def test_rejected_write_fails_loudly():
    nm = FakeNodemap()
    nm.nodes["LineSource"].is_writable = False
    with pytest.raises(RuntimeError):
        _camera(enabled=True)._configure_strobe(nm)


def test_machine_config_station1_strobe_is_off_until_wired():
    part_code = load_machine_config()["machine"]["part_code"]
    config = resolve_config_for_part(part_code)
    s1 = next(s for s in config.inspection_stations() if s.id == "s1")
    assert all(not cam.strobe.enabled for cam in s1.cameras.values())


# --------------------------------------------------------------------------- #
# color / pixel format
# --------------------------------------------------------------------------- #
COLOR_CAM = ["Mono8", "Mono16", "BayerRG8", "BayerRG16", "RGB8"]
COLOR_CAM_NO_MONO = ["BayerRG8", "BayerRG16", "RGB8"]
MONO_CAM = ["Mono8", "Mono10", "Mono12", "Mono16"]


def test_color_false_uses_mono8_even_on_color_camera():
    assert select_pixel_format(COLOR_CAM, color=False) == "Mono8"
    assert select_pixel_format(MONO_CAM, color=False) == "Mono8"


def test_color_false_falls_back_to_bayer_without_mono8():
    assert select_pixel_format(COLOR_CAM_NO_MONO, color=False) == "BayerRG8"


def test_color_true_uses_bayer():
    assert select_pixel_format(COLOR_CAM, color=True) == "BayerRG8"


def test_color_true_on_mono_camera_fails_loudly():
    with pytest.raises(ValueError, match="mono sensor"):
        select_pixel_format(MONO_CAM, color=True)


def _red_scene_rggb() -> np.ndarray:
    """A pure-red scene as an RGGB (GenICam BayerRG8) sensor records it."""
    raw = np.zeros((8, 8), np.uint8)
    raw[0::2, 0::2] = 200  # R sites
    return raw


def test_to_bgr_color_keeps_red_red():
    b, g, r = to_bgr(_red_scene_rggb(), "BayerRG8", color=True)[4, 4]
    assert r > 150 and b < 50


def test_to_bgr_bayer_as_mono_is_three_channel_gray():
    out = to_bgr(_red_scene_rggb(), "BayerRG8", color=False)
    assert out.shape == (8, 8, 3)
    assert (out[..., 0] == out[..., 1]).all() and (out[..., 1] == out[..., 2]).all()


def test_to_bgr_mono8_passthrough():
    raw = np.full((4, 6), 77, np.uint8)
    out = to_bgr(raw, "Mono8", color=False)
    assert out.shape == (4, 6, 3) and (out == 77).all()


# --------------------------------------------------------------------------- #
# exposure / gain
# --------------------------------------------------------------------------- #
class RangeNode(FakeNode):
    def __init__(self, name, value, lo, hi, log):
        super().__init__(name, value, log=log)
        self.min, self.max = lo, hi


def _exposure_nodemap() -> FakeNodemap:
    nm = FakeNodemap()
    nm.nodes.update(
        ExposureAuto=FakeNode("ExposureAuto", "Continuous", log=nm.writes),
        ExposureTime=RangeNode("ExposureTime", 5000.0, 20.0, 33000.0, nm.writes),
        GainAuto=FakeNode("GainAuto", "Continuous", log=nm.writes),
        Gain=RangeNode("Gain", 0.0, 0.0, 24.0, nm.writes),
    )
    return nm


def _camera_cfg(**kw) -> LucidCamera:
    cfg = CameraConfig(
        ip="192.168.7.41",
        resolution={"x": 1920, "y": 1080},
        roi={"x1": 0, "y1": 0, "x2": 1920, "y2": 1080},
        **kw,
    )
    return LucidCamera("cam2", cfg)


def test_exposure_and_gain_applied_with_auto_off():
    nm = _exposure_nodemap()
    _camera_cfg(exposure_us=3300, gain_db=3.4)._configure_exposure_gain(nm)
    assert nm.writes == [
        ("ExposureAuto", "Off"),
        ("ExposureTime", 3300.0),
        ("GainAuto", "Off"),
        ("Gain", 3.4),
    ]


def test_unset_exposure_gain_leave_camera_untouched():
    nm = _exposure_nodemap()
    _camera_cfg()._configure_exposure_gain(nm)
    assert nm.writes == []


def test_exposure_out_of_range_fails_loudly():
    nm = _exposure_nodemap()
    with pytest.raises(ValueError, match="outside this camera's range"):
        _camera_cfg(exposure_us=50_000)._configure_exposure_gain(nm)


def test_strobe_line_must_be_a_line_name():
    with pytest.raises(ValueError):
        _camera_cfg(strobe={"enabled": True, "line": "1"})
    assert _camera_cfg(strobe={"enabled": True, "line": "Line3"}).config.strobe.line == "Line3"


# --------------------------------------------------------------------------- #
# throughput limit
# --------------------------------------------------------------------------- #
def _throughput_nodemap(max_fps: float) -> FakeNodemap:
    nm = FakeNodemap()
    nm.nodes.update(
        DeviceLinkThroughputLimitMode=FakeNode("DeviceLinkThroughputLimitMode", "Off", log=nm.writes),
        DeviceLinkThroughputLimit=RangeNode(
            "DeviceLinkThroughputLimit", 125_000_000, 31_250_000, 125_000_000, nm.writes
        ),
        AcquisitionFrameRate=RangeNode("AcquisitionFrameRate", 30.0, 1.0, max_fps, nm.writes),
    )
    return nm


def test_throughput_limit_applied_in_bytes_per_second():
    nm = _throughput_nodemap(max_fps=40.0)
    _camera_cfg(throughput_limit_mbps=600)._configure_throughput(nm)
    assert nm.writes == [
        ("DeviceLinkThroughputLimitMode", "On"),
        ("DeviceLinkThroughputLimit", 75_000_000),
    ]


def test_unset_throughput_limit_leaves_camera_untouched():
    nm = _throughput_nodemap(max_fps=40.0)
    _camera_cfg()._configure_throughput(nm)
    assert nm.writes == []


def test_throughput_limit_below_camera_minimum_fails_loudly():
    nm = _throughput_nodemap(max_fps=40.0)
    with pytest.raises(ValueError, match="below this camera's minimum"):
        _camera_cfg(throughput_limit_mbps=100)._configure_throughput(nm)


def test_throughput_limit_above_link_speed_is_capped_at_link_speed():
    # Real case: cam2 on a 100 Mbit link -> camera range 25-100 Mbit/s.
    nm = _throughput_nodemap(max_fps=5.4)
    nm.nodes["DeviceLinkThroughputLimit"].min = 3_125_000
    nm.nodes["DeviceLinkThroughputLimit"].max = 12_500_000
    _camera_cfg(throughput_limit_mbps=600, fps=5)._configure_throughput(nm)
    assert nm.nodes["DeviceLinkThroughputLimit"].value == 12_500_000


def test_fps_too_high_for_slow_link_names_the_link_speed():
    nm = _throughput_nodemap(max_fps=5.4)
    nm.nodes["DeviceLinkThroughputLimit"].min = 3_125_000
    nm.nodes["DeviceLinkThroughputLimit"].max = 12_500_000
    with pytest.raises(ValueError, match="camera link is 100 Mbit/s"):
        _camera_cfg(throughput_limit_mbps=600, fps=30)._configure_throughput(nm)


def test_fps_that_no_longer_fits_under_the_limit_fails_loudly():
    nm = _throughput_nodemap(max_fps=12.5)  # camera's max fps after the cap
    with pytest.raises(ValueError, match="fps=30 doesn't fit through 300 Mbit/s"):
        _camera_cfg(throughput_limit_mbps=300)._configure_throughput(nm)
