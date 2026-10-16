"""Shared fixtures: every test gets isolated QSettings so the user's real ones are never touched."""

import pytest
from PySide6.QtCore import QSettings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("qsettings"))
    # QSettings(org, app) uses the native format; redirect both formats and both scopes.
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
            QSettings.setPath(fmt, scope, path)
    return path


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
    This autouse fixture is set up before qtbot, so it is torn down after qtbot closed them.
    """
    yield
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(scope="session")
def sphere_mesh(tmp_path_factory):
    """A real mesh of a sphere with the DEFAULT sizing, built ONCE per session (per xdist worker).

    Default domain (5/10/5/5 L) and default ``Mesh()``: 100 000 background cells, 0.01 L surface
    cells, 3 layers. Tests that only read it use ``case_dir`` directly; a test that modifies the
    case must copy it first (``shutil.copytree(sphere_mesh.case_dir, tmp)``).
    """
    from dataclasses import dataclass, field
    from pathlib import Path

    import pyvista as pv

    from vortexcfd.core.model import Domain, Mesh
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
                           box.reference_length, Mesh())
    case = tmp_path_factory.mktemp("sphere_mesh") / "case"
    prepare_case_dir(case, build_mesh_files(inputs))
    sphere.save(str(case / TRI_SURFACE / "Sphere.stl"))
    out = SphereMesh(case, inputs, estimate=estimate_mesh(inputs.domain_bounds, inputs.reference_length, inputs.mesh))
    run = MeshRun(case, on_line=out.lines.append, on_step=out.steps.append, step_timeout_s=100)
    run.start()
    out.result = run.wait(115)
    assert out.result is not None and out.result.success, "the shared sphere mesh failed to build"
    return out
