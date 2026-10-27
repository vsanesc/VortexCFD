"""Shared fixtures: every test gets isolated QSettings so the user's real ones are never touched."""

from vortexcfd.core.display_guard import apply_display_guard

# Before Qt is imported: tests never open a window on the WSLg desktop (VORTEXCFD_ALLOW_REAL_DISPLAY=1
# lets the owner run them on the real display).
apply_display_guard()

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path_factory, monkeypatch):
    """User presets (D-077) go to a temporary config directory, never the user's ~/.config."""
    path = tmp_path_factory.mktemp("config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(path))
    return path


@pytest.fixture(autouse=True)
def isolated_settings(isolated_config, monkeypatch):
    path = str(isolated_config)  # one folder: QSettings files, presets, the OpenFOAM path
    # The app's own switch (core/user_dirs.py, D-141): QSettings and the config folder live here, and a
    # subprocess started by a test inherits it.
    monkeypatch.setenv("VORTEXCFD_SETTINGS_DIR", path)
    # QSettings(org, app) uses the native format; redirect both formats and both scopes.
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
            QSettings.setPath(fmt, scope, path)
    return path


@pytest.fixture
def allow_temporary_recent(monkeypatch):
    """Tests run in temporary folders, which the Recent list refuses (D-141): this lets a test record them."""
    from vortexcfd.core import user_dirs

    monkeypatch.setattr(user_dirs, "is_temporary", lambda path: False)


def focus_widget(qtbot, window, widget) -> None:
    """Activate ``window``, focus ``widget`` and wait until it really has the keyboard focus.

    Needed before sending keys: on a real display (WSLg) the window may not be active yet.
    If focus cannot be guaranteed on a non-offscreen platform, the test is skipped.
    """
    import os

    from PySide6.QtWidgets import QApplication

    window.activateWindow()
    widget.setFocus()
    try:
        qtbot.waitUntil(lambda: QApplication.focusWidget() is widget, timeout=3000)
    except Exception:
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            pytest.skip("keyboard focus cannot be guaranteed on this display (window not activated)")
        raise


@pytest.fixture(autouse=True)
def flush_deleted_widgets():
    """Really destroy the widgets a test created.

    pytest-qt closes widgets and calls deleteLater(), but the deferred deletes are only run by
    an event loop, so every test left its whole MainWindow (menus, VTK widgets) behind and
    each later test got slower (the application stylesheet is re-applied to every live widget).
    This autouse fixture is set up before qtbot, so it is torn down after qtbot closed them. A main window ends
    its worker threads' signals and its viewer before it is deleted (D-164). It also runs before the test: pytest-qt
    closes and deletes the widgets of qtbot.addWidget in a hook after this fixture's teardown, so the previous
    test's windows and their VTK objects are freed here, before this test opens one, with no OpenGL context current
    (D-193).
    """
    from vortexcfd.gui.teardown import close_plotters, flush_deletions

    flush_deletions()
    yield

    close_plotters()  # a plotter a test left open is finalized before Qt deletes its widget (D-164)
    flush_deletions()


@pytest.fixture(scope="session")
def sphere_mesh(tmp_path_factory):
    """A real mesh of a sphere with the DEFAULT sizing, built ONCE per session (per xdist worker).

    Default domain (5/10/5/5 L) and the v9 default mesh (``Mesh(**V9_MESH_BEHAVIOUR)``, the set-up the
    recorded data in tests/data describe; D-085, D-086): 100 000 background cells, 0.01 L surface
    cells, 3 relative layers, no curvature refinement. Tests that only read it use ``case_dir`` directly; a test that modifies the
    case must copy it first (``shutil.copytree(sphere_mesh.case_dir, tmp)``).
    """
    from dataclasses import dataclass, field
    from pathlib import Path

    import pyvista as pv

    from vortexcfd.core.model import Domain, Mesh
    from vortexcfd.core.project_io import V9_MESH_BEHAVIOUR
    from vortexcfd.foam.mesh_case import (
        TRI_SURFACE,
        MeshCaseInput,
        build_mesh_files,
        prepare_case_dir,
        safe_part_names,
    )
    from vortexcfd.foam.mesh_estimate import estimate_mesh
    from vortexcfd.foam.mesh_run import MeshRun
    from vortexcfd.geometry.domain import compute_domain

    @dataclass
    class SphereMesh:
        case_dir: Path
        inputs: MeshCaseInput
        result: object = None
        lines: list = field(default_factory=list)
        steps: list = field(default_factory=list)
        estimate: object = None

    sphere = pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24)
    box = compute_domain([tuple(sphere.bounds)], Domain())
    inputs = MeshCaseInput(box.bounds, False, tuple(safe_part_names(["Sphere"])), tuple(sphere.bounds),
                           box.reference_length, Mesh(**V9_MESH_BEHAVIOUR))
    case = tmp_path_factory.mktemp("sphere_mesh") / "case"
    prepare_case_dir(case, build_mesh_files(inputs))
    sphere.save(str(case / TRI_SURFACE / "Sphere.stl"))
    out = SphereMesh(case, inputs, estimate=estimate_mesh(inputs.domain_bounds, inputs.reference_length, inputs.mesh))
    run = MeshRun(case, on_line=out.lines.append, on_step=out.steps.append, step_timeout_s=100)
    run.start()
    out.result = run.wait(115)
    assert out.result is not None and out.result.success, "the shared sphere mesh failed to build"
    return out


def pytest_collection_modifyitems(config, items):
    """Validation tests (minutes of OpenFOAM), long tests (real runs above 60 s, D-043) and benchmark
    tests (real benchmark runs, D-082) run only when selected with ``-m validation`` / ``-m long`` /
    ``-m bench``."""
    expression = config.getoption("markexpr") or ""
    for marker in ("validation", "long", "bench"):
        if marker in expression and f"not {marker}" not in expression:
            continue
        skip = pytest.mark.skip(reason=f"{marker} test: run with `pytest -m {marker}`")
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)
