"""With the auto-update timer off, every visible change must render explicitly."""

from pathlib import Path

import pytest
import pyvista as pv
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import MainWindow


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path):
    src = tmp_path / "src" / "wing.stl"
    src.parent.mkdir()
    pv.Sphere(radius=1.0, theta_resolution=12, phi_resolution=12).save(str(src))
    folder = tmp_path / "proj"
    folder.mkdir()
    project = Project.new("r")
    project.save(folder / "p.json")
    w = MainWindow(project, FakeDialogs(import_path=src, units="m"), with_viewer=True)
    qtbot.addWidget(w)
    w.show()
    w.renders = 0
    original = w.viewer.render

    def counting(*args, **kwargs):
        w.renders += 1
        return original(*args, **kwargs)

    w.viewer.render = counting  # instance attribute: the window calls self.viewer.render()
    yield w
    w.project.save = lambda *a, **k: None
    w.close()


def renders_after(w: MainWindow, action) -> int:
    w.renders = 0
    action()
    return w.renders


def test_viewer_auto_update_timer_is_off(window: MainWindow) -> None:
    assert not window.viewer.render_timer.isActive()


def test_every_change_path_renders(window: MainWindow, qtbot: QtBot) -> None:
    w = window
    steps = {
        "import a part": w.act_import.trigger,
        "select the root": w._select_root,
        "select the part": lambda: w.tree.setCurrentItem(w._items[("part", 0)]),
        "select a boundary": lambda: w.tree.setCurrentItem(w._items[("boundary_inlet", None)]),
        "toggle visibility (eye)": lambda: w._on_eye_clicked(w._items[("part", 0)]),
        "toggle visibility back": lambda: w._on_eye_clicked(w._items[("part", 0)]),
        "change the domain": lambda: w.project.update_domain(upstream=3.0),
        "undo": w.act_undo.trigger,
        "redo": w.act_redo.trigger,
        "domain box toggle": w.act_toggle_domain.trigger,
        "wireframe on": w.top_bar.wireframe_button.click,
        "wireframe off": w.top_bar.wireframe_button.click,
        "view button": lambda: w.top_bar.view_buttons["view_xy"].click(),
        "fit button": lambda: w.top_bar.view_buttons["reset_camera"].click(),
        "telemetry field": lambda: w.act_tel_fields["parts"].trigger(),
        "telemetry show": w.act_tel_show.trigger,
        "mesh scene tab": w.mesh_tab.click,
        "geometry scene tab": w.scene_tab.click,
        "zoom in": w.act_zoom_in.trigger,
        "zoom reset": w.act_zoom_reset.trigger,
        "viewer resize": lambda: (w.resize(w.width() + 80, w.height() + 40), qtbot.wait(50)),
        "remove the part": lambda: (w.tree.setCurrentItem(w._items[("part", 0)]), w.act_remove_part.trigger()),
        "new part (placeholder)": w.add_placeholder_part,
    }
    silent = [name for name, action in steps.items() if renders_after(w, action) < 1]
    assert not silent, f"changes that did not render: {silent}"


def test_one_change_does_not_render_in_a_storm(window: MainWindow) -> None:
    """Rendering is explicit but bounded: a single import renders a handful of times at most."""
    n = renders_after(window, window.act_import.trigger)
    assert 1 <= n <= 20


def test_mesh_load_renders(window: MainWindow, monkeypatch) -> None:
    """Loading a mesh into the viewer ends in a render (the load itself is stubbed)."""
    window._mesh_patches = ("wing",)
    case = window.project.path.parent / "case"
    monkeypatch.setattr(window.mesh_view, "load", lambda case_dir, patches, symmetric=False: True)
    assert renders_after(window, window._load_mesh_view) >= 1
    assert window._scene_mode == "mesh"
