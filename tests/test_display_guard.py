"""The display guard keeps tests and scripts off the WSLg desktop."""

import os

from vortexcfd.core.display_guard import ALLOW_VARIABLE, apply_display_guard, on_wslg_display


def test_wayland_display_is_guarded(tmp_path):
    env = {"WAYLAND_DISPLAY": "wayland-0"}
    assert apply_display_guard(env, wslg_root=tmp_path / "absent")
    assert env["QT_QPA_PLATFORM"] == "offscreen" and env["PYVISTA_OFF_SCREEN"] == "true"


def test_x_display_is_guarded_only_on_wslg(tmp_path):
    assert on_wslg_display({"DISPLAY": ":0"}, wslg_root=tmp_path)  # the mount exists
    assert not on_wslg_display({"DISPLAY": ":0"}, wslg_root=tmp_path / "absent")
    assert on_wslg_display({"DISPLAY": ":0", "WSL_DISTRO_NAME": "Ubuntu-24.04"}, wslg_root=tmp_path / "absent")


def test_owner_can_allow_the_real_display(tmp_path):
    env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", ALLOW_VARIABLE: "1", "QT_QPA_PLATFORM": "wayland"}
    assert not apply_display_guard(env, wslg_root=tmp_path)
    assert env["QT_QPA_PLATFORM"] == "wayland"


def test_overrides_a_real_platform_request(tmp_path):
    env = {"DISPLAY": ":0", "QT_QPA_PLATFORM": "xcb"}
    assert apply_display_guard(env, wslg_root=tmp_path)
    assert env["QT_QPA_PLATFORM"] == "offscreen"


def test_no_display_is_left_alone(tmp_path):
    env = {}
    assert not apply_display_guard(env, wslg_root=tmp_path)
    assert env == {}


def test_this_session_is_offscreen(qapp):
    """conftest applied the guard before Qt was imported."""
    if os.environ.get(ALLOW_VARIABLE) == "1" or not on_wslg_display(os.environ):
        return
    assert qapp.platformName() == "offscreen"
