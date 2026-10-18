"""Keep tests and scripts off the owner's WSLg desktop (no Qt import: call it before Qt loads).

Only the owner runs anything on the real display. ``apply_display_guard`` switches Qt to the
offscreen platform (and PyVista to off-screen rendering) when a WSLg display is present, unless
``VORTEXCFD_ALLOW_REAL_DISPLAY=1``.
"""

import os
from collections.abc import MutableMapping
from pathlib import Path

ALLOW_VARIABLE = "VORTEXCFD_ALLOW_REAL_DISPLAY"
WSLG_ROOT = Path("/mnt/wslg")


def on_wslg_display(env: MutableMapping[str, str], wslg_root: Path = WSLG_ROOT) -> bool:
    """True when a window would reach the WSLg desktop: a Wayland display is set, or an X display
    is set while the WSLg mount (or a WSL distribution) is present."""
    if env.get("WAYLAND_DISPLAY"):
        return True
    if not env.get("DISPLAY"):
        return False
    return wslg_root.exists() or bool(env.get("WSL_DISTRO_NAME"))


def apply_display_guard(env: MutableMapping[str, str] | None = None, wslg_root: Path = WSLG_ROOT) -> bool:
    """Force offscreen rendering on the WSLg display unless the owner allowed it.

    Must run before PySide6 or pyvista is imported. Returns True when the guard switched the
    environment to offscreen.
    """
    env = os.environ if env is None else env
    if env.get(ALLOW_VARIABLE) == "1" or not on_wslg_display(env, wslg_root):
        return False
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYVISTA_OFF_SCREEN"] = "true"  # read by pyvista at import: plain Plotters open no window
    return True
