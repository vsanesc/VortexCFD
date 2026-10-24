"""The simulation tree's context menus, Delete / F2 / double-click and the imported refinement regions in the window
(D-145)."""

from pathlib import Path

import pytest
import pyvista as pv
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part, SurfaceShape
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_case import MARKER_NAME, MESH_RECORD_FILE
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import MainWindow

@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path):
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    pv.Sphere(radius=0.5).save(str(folder / "geometry" / "ball.stl"))
    pv.Box(bounds=(0.8, 2.2, -0.5, 0.5, -0.5, 0.5)).triangulate().save(str(folder / "geometry" / "blob.stl"))
    project = Project.new("Demo")
    project.add_part(Part(name="ball", source_file="geometry/ball.stl", units="m"))
    project.add_part(Part(name="blob", source_file="geometry/blob.stl", units="m"))
    project.save(folder / "p.vcfd")
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    yield w
    assert not w.project.observer_errors
    w.project.save = lambda *a, **k: None
    w.close()


def texts(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def submenu(menu, title: str) -> list[str]:
    action = next(a for a in menu.actions() if a.text() == title)
    return texts(action.menu())


def test_every_node_has_a_menu(window: MainWindow) -> None:
    for key in window._items:
        if key[0] == "root":
            continue
        menu = window.tree_menu_for(key)
        assert menu is not None and texts(menu), key


def test_menus_offer_the_actions_that_apply(window: MainWindow) -> None:
    w = window
    geometry = texts(w.tree_menu_for(("geometry", None)))
    assert {"&Import Geometry...", "Show all", "Hide all"} <= set(geometry)
    part = texts(w.tree_menu_for(("part", 0)))
    assert ["Hide", "Isolate", "Rename", "Delete", "Use as refinement region"] == part[:5]
    assert "Properties" in part
    domain = texts(w.tree_menu_for(("fluid_domain", None)))
    assert "&Generate Domain..." in domain and "Edit" in domain
    assert "Boundary type" in texts(w.tree_menu_for(("boundary_inlet", None)))
    mesh = w.tree_menu_for(("mesh", None))
    assert {"&Generate Mesh", "C&lear Mesh...", "Mesh report"} <= set(texts(mesh))
    assert w.act_generate_mesh in mesh.actions() and w.act_clear_mesh in mesh.actions()  # the same actions (D-173)
    volumes = w.tree_menu_for(("refinement_volumes", None))
    assert submenu(volumes, "Add refinement volume") == ["Box", "Cylinder", "Sphere", "Cone"]
    assert "Add from imported geometry…" in texts(volumes)
    results = w.tree_menu_for(("results", None))
    assert submenu(results, "Add results object") == ["Clip", "Isosurface", "Streamlines", "Line plot"]


def test_show_hide_and_isolate_parts(window: MainWindow) -> None:
    w = window
    w.isolate_part(1)
    assert w.part_visibility == {"ball": False, "blob": True}
    menu = w.tree_menu_for(("part", 0))
    assert texts(menu)[0] == "Show"
    w.show_all_parts()
    assert all(w.part_visibility.values())
    w.hide_all_parts()
    assert not any(w.part_visibility.values())
    w.toggle_part_visibility(0)
    assert w.part_visibility == {"ball": True, "blob": False}


def test_delete_key_asks_first(window: MainWindow, qtbot: QtBot) -> None:
    w = window
    w.tree.setCurrentItem(w._items[("part", 1)])
    w.dialogs.confirm_answer = False
    w.tree.setFocus()
    w.act_delete.trigger()
    assert len(w.project.sim.geometry.parts) == 2 and "blob" in w.dialogs.confirmed[-1][1]
    w.dialogs.confirm_answer = True
    w.act_delete.trigger()
    assert [p.name for p in w.project.sim.geometry.parts] == ["ball"]
    assert w.act_delete.shortcut().toString() == "Del" and w.act_rename.shortcut().toString() == "F2"


def test_f2_and_double_click(window: MainWindow, qtbot: QtBot) -> None:
    w = window
    item = w._items[("part", 0)]
    w.tree.itemDoubleClicked.emit(item, 0)
    assert w._selection == ("part", 0)
    w.act_rename.trigger()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is w.properties.name_edit, timeout=2000)
    assert w.properties.name_edit.selectedText() == "ball"


def test_use_part_as_refinement_region(window: MainWindow) -> None:
    w = window
    w.project.update_domain(enabled=True)
    w.use_part_as_region(1)
    sim = w.project.sim
    assert [p.name for p in sim.geometry.parts] == ["ball"]
    volume = sim.refinement_volumes[0]
    assert volume.shape == SurfaceShape(file="geometry/blob.stl") and volume.name == "blob"
    assert w._selection == ("refinement_volume", 0)
    assert w.properties._rows["vol_surface_mode"].isVisibleTo(w.properties)
    w.project.undo()
    assert len(w.project.sim.geometry.parts) == 2 and w.project.sim.refinement_volumes == []


def test_add_region_from_a_file(window: MainWindow, tmp_path: Path) -> None:
    w = window
    w.project.update_domain(enabled=True)
    source = tmp_path / "outside" / "Wake region.stl"
    source.parent.mkdir()
    pv.Box(bounds=(0.6, 3.0, -0.6, 0.6, -0.6, 0.6)).triangulate().save(str(source))
    w.dialogs.import_path = source
    w.add_region_from_file()
    volume = w.project.sim.refinement_volumes[0]
    assert volume.name == "Wake_region" and volume.shape.file == "geometry/Wake region.stl"
    assert (w.project.folder / "geometry" / "Wake region.stl").is_file()
    assert w._items[("refinement_volume", 0)].text(0) == "Wake_region (surface)"
    assert volume.shape.mode == "inside"  # a closed surface: refined inside
    # an open surface is added to refine within a distance of it (one surface cell); inside is refused for it (D-159)
    pv.Plane(center=(1.0, 0, 0)).triangulate().save(str(source))
    w.add_region_from_file()
    assert len(w.project.sim.refinement_volumes) == 2
    sheet = w.project.sim.refinement_volumes[1]
    assert sheet.shape.mode == "distance" and sheet.shape.distance == pytest.approx(sheet.target_size)
    assert "within a distance: the surface is open" in w.console.text()
    w.tree.setCurrentItem(w._items[("refinement_volume", 1)])
    p = w.properties
    p.vol_surface_mode.setCurrentIndex(p.vol_surface_mode.findData("inside"))
    assert w.project.volume(sheet.id).shape.mode == "distance"  # refused, back to the distance mode
    assert p.vol_surface_mode.currentData() == "distance"
    assert "not a closed surface" in w.statusBar().currentMessage()


def test_clear_mesh_and_mesh_report(window: MainWindow) -> None:
    w = window
    case = w.project.folder / "case"
    for folder in ("constant/polyMesh", "system", "100", "postProcessing"):
        (case / folder).mkdir(parents=True)
    (case / MARKER_NAME).write_text("x")
    (case / MESH_RECORD_FILE).write_text("{}")
    from vortexcfd.foam.mesh_report import MeshReport

    w.mesh_report = MeshReport(points=8, faces=12, cells=1, max_non_orthogonality=0.0, avg_non_orthogonality=0.0,
                               max_skewness=0.1, failed_checks=0, mesh_ok=True)
    w.show_mesh_report()
    assert w.dialogs.texts[-1][0] == "Mesh report" and "1" in w.dialogs.texts[-1][1]
    w.dialogs.confirm_answer = False
    w.clear_mesh()
    assert (case / "constant" / "polyMesh").is_dir()
    w.dialogs.confirm_answer = True
    w.clear_mesh()
    assert sorted(p.name for p in case.iterdir()) == [MARKER_NAME, "constant", "system"]
    assert w.mesh_report is None


def test_right_click_pops_the_menu(window: MainWindow, qtbot: QtBot) -> None:
    w = window
    item = w._items[("mesh", None)]
    w._tree_context_menu(w.tree.visualItemRect(item).center())
    assert w._selection == ("mesh", None)
    assert Qt.ContextMenuPolicy.CustomContextMenu == w.tree.contextMenuPolicy()
