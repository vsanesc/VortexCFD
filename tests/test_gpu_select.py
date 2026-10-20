"""GPU adapter selection under WSL at start-up (D-104). No display: the environment logic only."""

import ast
import logging
from pathlib import Path

from vortexcfd.core.gpu_select import GPU_VARIABLES, renderer_string, running_under_wsl, select_gpu


def test_sets_both_variables_under_wsl() -> None:
    env = {"DISPLAY": ":0"}
    assert select_gpu(env, wsl=True) == GPU_VARIABLES
    assert env["GALLIUM_DRIVER"] == "d3d12" and env["MESA_D3D12_DEFAULT_ADAPTER_NAME"] == "NVIDIA"


def test_keeps_what_the_user_already_set() -> None:
    env = {"GALLIUM_DRIVER": "llvmpipe"}
    assert select_gpu(env, wsl=True) == {"MESA_D3D12_DEFAULT_ADAPTER_NAME": "NVIDIA"}
    assert env["GALLIUM_DRIVER"] == "llvmpipe"
    env = {"GALLIUM_DRIVER": "d3d12", "MESA_D3D12_DEFAULT_ADAPTER_NAME": "AMD"}
    assert select_gpu(env, wsl=True) == {} and env["MESA_D3D12_DEFAULT_ADAPTER_NAME"] == "AMD"


def test_never_outside_wsl_or_offscreen() -> None:
    env: dict[str, str] = {}
    assert select_gpu(env, wsl=False) == {} and env == {}
    env = {"QT_QPA_PLATFORM": "offscreen"}
    assert select_gpu(env, wsl=True) == {} and "GALLIUM_DRIVER" not in env


def test_wsl_detection_is_faked_from_the_environment_or_the_kernel_version(tmp_path: Path) -> None:
    linux = tmp_path / "version_linux"
    linux.write_text("Linux version 6.8.0-45-generic (buildd@lcy02) #45-Ubuntu SMP\n")
    wsl = tmp_path / "version_wsl"
    wsl.write_text("Linux version 6.6.87.2-microsoft-standard-WSL2 (root@builder)\n")
    assert not running_under_wsl({}, linux)
    assert running_under_wsl({}, wsl)
    assert running_under_wsl({"WSL_DISTRO_NAME": "Ubuntu-24.04"}, linux)
    assert running_under_wsl({"WSL_INTEROP": "/run/WSL/1_interop"}, linux)
    assert not running_under_wsl({}, tmp_path / "missing")
    env: dict[str, str] = {"WSL_DISTRO_NAME": "Ubuntu"}
    assert select_gpu(env) == GPU_VARIABLES  # detected, not passed


def test_the_gui_package_selects_before_importing_qt_or_vtk() -> None:
    """vortexcfd/gui/__init__.py (run before any GUI module, also by the installed console script, which
    imports vortexcfd.gui.main_window) calls select_gpu before its first import that loads Qt or VTK."""
    source = Path(__file__).parents[1] / "src" / "vortexcfd" / "gui" / "__init__.py"
    body = ast.parse(source.read_text()).body
    order = []
    for node in body:
        if isinstance(node, ast.ImportFrom):
            order.append(("import", node.module))
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            order.append(("call", getattr(node.value.func, "id", "")))
    assert order.index(("call", "select_gpu")) < order.index(("import", "vortexcfd.gui.main_window"))
    assert order[0] == ("import", "vortexcfd.core.gpu_select")
    gpu_tree = ast.parse((Path(__file__).parents[1] / "src" / "vortexcfd" / "core" / "gpu_select.py").read_text())
    imported = {alias.name for n in ast.walk(gpu_tree) if isinstance(n, ast.Import) for alias in n.names}
    imported |= {n.module for n in ast.walk(gpu_tree) if isinstance(n, ast.ImportFrom)}
    assert not any(m.split(".")[0] in ("PySide6", "vtk", "vtkmodules", "pyvista", "pyvistaqt", "vortexcfd")
                   for m in imported)


def test_renderer_string_parsing() -> None:
    caps = "OpenGL vendor string:  Microsoft Corporation\nOpenGL renderer string:  D3D12 (NVIDIA GeForce RTX 3080)\n"
    assert renderer_string(caps) == "D3D12 (NVIDIA GeForce RTX 3080)"
    assert renderer_string("no context") is None


def test_the_renderer_is_logged_once_the_viewer_exists(qtbot, caplog, tmp_path: Path) -> None:
    from tests.fakes import FakeDialogs
    from vortexcfd.core.project import Project
    from vortexcfd.gui.main_window import MainWindow

    project = Project.new("Demo")
    project.save(tmp_path / "p.json")
    with caplog.at_level(logging.INFO, logger="vortexcfd"):
        w = MainWindow(project, FakeDialogs(), with_viewer=True)
        qtbot.addWidget(w)
        w.show()
        qtbot.waitUntil(lambda: any("OpenGL renderer:" in r.getMessage() for r in caplog.records), timeout=5000)
    w.project.save = lambda *a, **k: None
    w.close()
