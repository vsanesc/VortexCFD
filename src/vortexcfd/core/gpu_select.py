"""Select the NVIDIA adapter for OpenGL under WSL (no Qt, no VTK: runs before either is imported, D-104).

Under WSL2, Mesa renders OpenGL through the d3d12 Gallium driver on a Windows GPU adapter; on a PC with
an integrated and a discrete GPU it may pick the integrated one. ``select_gpu`` sets
GALLIUM_DRIVER=d3d12 and MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA, each only when the user has not set it,
and only under WSL. Nothing is changed outside WSL or in an offscreen run (no display to render to).
"""

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

GPU_VARIABLES = {"GALLIUM_DRIVER": "d3d12", "MESA_D3D12_DEFAULT_ADAPTER_NAME": "NVIDIA"}
PROC_VERSION = Path("/proc/version")


def running_under_wsl(env: MutableMapping[str, str], proc_version: Path = PROC_VERSION) -> bool:
    """True under WSL: WSL_DISTRO_NAME or WSL_INTEROP is set, or the kernel version names Microsoft."""
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in proc_version.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False


def select_gpu(env: MutableMapping[str, str] | None = None, wsl: bool | None = None) -> dict[str, str]:
    """Set the GPU_VARIABLES the user has not set, under WSL and with a real display only; returns the
    variables it set (empty when nothing changed). ``wsl``: None detects it (running_under_wsl)."""
    env = os.environ if env is None else env
    if wsl is None:
        wsl = running_under_wsl(env)
    if not wsl or env.get("QT_QPA_PLATFORM") == "offscreen":
        return {}
    applied = {}
    for name, value in GPU_VARIABLES.items():
        if name not in env:
            env[name] = value
            applied[name] = value
    return applied


def renderer_string(capabilities: str) -> str | None:
    """The "OpenGL renderer string" line of VTK's vtkRenderWindow.ReportCapabilities(), or None."""
    match = re.search(r"OpenGL renderer string:\s*(.+)", capabilities)
    return match.group(1).strip() if match else None
