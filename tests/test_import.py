"""Tests for surface import and the viewer showing Parts (picking, visibility, undo/redo)."""

from pathlib import Path

import numpy as np
import pytest
import pyvista as pv
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import ROLE_EYE, MainWindow


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


@pytest.fixture
def sphere_stl(tmp_path: Path) -> Path:
    path = tmp_path / "src" / "wing.stl"
    path.parent.mkdir()
    pv.Sphere(radius=1.0, theta_resolution=16, phi_resolution=16).save(str(path))
    return path


@pytest.fixture
def make_window(qtbot: QtBot, tmp_path: Path):
    made: list[MainWindow] = []

    def make(import_path=None, units="m", with_viewer=True, saved=True, save_path=None) -> MainWindow:
        project = Project.new("Demo")
        if saved:
            (tmp_path / "proj").mkdir(exist_ok=True)
            project.save(tmp_path / "proj" / "proj.json")
        dialogs = FakeDialogs(import_path=import_path, units=units, save_path=save_path)
        window = MainWindow(project, dialogs, with_viewer=with_viewer)
        qtbot.addWidget(window)
        window.show()
        made.append(window)
        return window

    yield make
    for w in made:
        assert not w.project.observer_errors
        w.project.save = lambda *a, **k: None
        w.close()


def test_import_copies_file_and_is_one_undo_step(make_window, sphere_stl: Path, tmp_path: Path) -> None:
    w = make_window(import_path=sphere_stl, units="mm")
    before = len(w.project._undo)
    w.act_import.trigger()
    project_dir = tmp_path / "proj"
    assert (project_dir / "geometry" / "wing.stl").is_file()
    assert sphere_stl.is_file()  # the original is untouched
    parts = w.project.sim.geometry.parts
    assert [(p.name, p.source_file, p.units) for p in parts] == [("wing", "geometry/wing.stl", "mm")]
    assert len(w.project._undo) == before + 1
    assert w.project.undo_label == "Add part 'wing'"
    assert w._selection == ("part", 0)
    text = w.console.text()
    assert "Imported wing.stl" in text and "Checks for 'wing'" in text and "watertight: yes" in text
    w.project.undo()
    assert w.project.sim.geometry.parts == []
    assert (project_dir / "geometry" / "wing.stl").is_file()  # the copy stays on disk


def test_import_on_unsaved_project_runs_save_as_first(make_window, sphere_stl: Path, tmp_path: Path) -> None:
    target = tmp_path / "new" / "p.json"
    target.parent.mkdir()
    w = make_window(import_path=sphere_stl, saved=False, save_path=target)
    w.act_import.trigger()
    assert target.is_file() and (target.parent / "geometry" / "wing.stl").is_file()
    assert w.project.path == target
    assert w.project.sim.geometry.parts[0].source_file == "geometry/wing.stl"


def test_import_aborts_when_save_as_is_cancelled(make_window, sphere_stl: Path, tmp_path: Path) -> None:
    w = make_window(import_path=sphere_stl, saved=False, save_path=None)
    w.act_import.trigger()
    assert w.project.sim.geometry.parts == [] and w.project.path is None
    assert not (tmp_path / "geometry").exists()


def test_second_import_gets_unique_names(make_window, sphere_stl: Path, tmp_path: Path) -> None:
    w = make_window(import_path=sphere_stl)
    w.act_import.trigger()
    w.act_import.trigger()
    parts = w.project.sim.geometry.parts
    assert [p.name for p in parts] == ["wing", "wing_2"]
    assert [p.source_file for p in parts] == ["geometry/wing.stl", "geometry/wing_2.stl"]


def test_import_of_unsupported_file_leaves_nothing_behind(make_window, tmp_path: Path) -> None:
    bad = tmp_path / "src" / "model.x_t"
    bad.parent.mkdir()
    bad.write_text("**PARASOLID")
    w = make_window(import_path=bad)
    w.act_import.trigger()
    assert w.project.sim.geometry.parts == []
    assert not (tmp_path / "proj" / "geometry" / "model.x_t").exists()
    assert "Unsupported file type" in w.statusBar().currentMessage()
    assert w.statusBar().property("level") == "error"


def test_import_cancelled_dialogs_do_nothing(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=None)
    w.act_import.trigger()
    assert w.project.sim.geometry.parts == []
    w2 = make_window(import_path=sphere_stl, units=None)
    w2.act_import.trigger()
    assert w2.project.sim.geometry.parts == []


def test_viewer_shows_part_and_hides_empty_state(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl)
    assert w.scene.actors == [] and w._grid_actors[0].GetVisibility()
    w.act_import.trigger()
    assert len(w.scene.actors) == 1
    assert not w._grid_actors[0].GetVisibility() and not w._empty_message.actor.GetVisibility()
    xmin, xmax, *_ = w.scene.visible_bounds()
    assert xmax - xmin == pytest.approx(2.0, abs=0.1)


def test_undo_redo_add_and_remove_the_actor(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl)
    w.act_import.trigger()
    first = w.scene.actors[0]
    assert w.viewer.renderer.actors  # registered with the renderer
    w.act_undo.trigger()
    assert w.scene.actors == [] and w._grid_actors[0].GetVisibility()
    assert first not in w.viewer.renderer.actors.values()
    w.act_redo.trigger()
    assert len(w.scene.actors) == 1 and not w._grid_actors[0].GetVisibility()
    w.tree.setCurrentItem(w._items[("part", 0)])
    w.act_remove_part.trigger()
    assert w.scene.actors == []


def test_units_change_rescales_the_actor(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl, units="m")
    w.act_import.trigger()
    width_m = np.ptp(w.scene.visible_bounds()[:2])
    w.project.update_part(0, units="mm")
    assert np.ptp(w.scene.visible_bounds()[:2]) == pytest.approx(width_m / 1000, rel=1e-3)
    w.project.update_part(0, name="renamed")  # a rename keeps the actor
    assert len(w.scene.actors) == 1 and w.tree is not None


def test_missing_file_warns_without_crashing(make_window, tmp_path: Path) -> None:
    w = make_window()
    w.project.add_part(Part(name="gone", source_file="geometry/gone.stl", units="m"))
    item = w._items[("part", 0)]
    assert item.toolTip(0) == "File not found"
    assert w.scene.actors == []
    w.tree.setCurrentItem(item)
    p = w.properties
    assert p.status_value.text() == "File not found"
    assert p.status_value.property("warn") == "true" and p._rows["status"].isVisible()
    assert not p.checks_title.isVisible()
    assert dict(w.telemetry_rows)["Triangles"] == "—"


def test_placeholder_part_without_file_is_not_a_warning(make_window) -> None:
    w = make_window()
    w.act_add_part.trigger()
    assert w._items[("part", 0)].toolTip(0) == ""
    assert not w.properties._rows["status"].isVisible()


def test_picking_selects_the_part_in_the_tree(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl)
    w.act_import.trigger()
    w.act_import.trigger()
    w._select_root()
    assert w.scene.pick_actor(w.scene.actors[1]) is True
    assert w._selection == ("part", 1)
    assert w.props_name.text() == "wing_2"
    assert w.scene.pick_actor(w._grid_actors[0]) is False  # not a part
    assert w._selection == ("part", 1)


def test_selection_highlights_the_actor(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl)
    w.act_import.trigger()
    w.act_import.trigger()
    t = w._theme
    hexes = [pv.Color(a.prop.color).hex_rgb.lower() for a in w.scene.actors]
    assert hexes == [t.part_surface.lower(), t.part_selected.lower()]  # the last import is selected
    w.tree.setCurrentItem(w._items[("part", 0)])
    hexes = [pv.Color(a.prop.color).hex_rgb.lower() for a in w.scene.actors]
    assert hexes == [t.part_selected.lower(), t.part_surface.lower()]
    assert t.part_selected == t.accent_secondary


def test_eye_toggles_actor_visibility(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl)
    w.act_import.trigger()
    item = w._items[("part", 0)]
    rect = w.tree.visualItemRect(item)
    pos = QPoint(w.tree.viewport().width() - 4, rect.center().y())
    QTest.mouseClick(w.tree.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert w._items[("part", 0)].data(0, ROLE_EYE) is False
    assert not w.scene.actors[0].GetVisibility()
    assert w._grid_actors[0].GetVisibility()  # no visible part: the empty state is back
    QTest.mouseClick(w.tree.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert w.scene.actors[0].GetVisibility() and not w._grid_actors[0].GetVisibility()


def test_wireframe_applies_to_part_actors(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl)
    w.act_import.trigger()
    w.top_bar.wireframe_button.click()
    assert w.scene.actors[0].prop.style.lower() == "wireframe"
    w.top_bar.wireframe_button.click()
    assert w.scene.actors[0].prop.style.lower() == "surface"


def test_checks_group_for_a_watertight_part(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl)
    w.act_import.trigger()
    p = w.properties
    assert p.checks_title.isVisible()
    v = {k: lab.text() for k, lab in p.check_values.items()}
    assert v["watertight"] == "yes" and v["open"] == "0" and v["non_manifold"] == "0"
    assert int(v["triangles"]) > 0
    assert all(lab.property("warn") == "false" for lab in p.check_values.values())
    assert dict(w.telemetry_rows)["Triangles"] == v["triangles"]


def test_checks_group_warns_for_an_open_surface(make_window, tmp_path: Path) -> None:
    box = pv.Box(level=0).triangulate().clean()
    faces = np.asarray(box.faces).reshape(-1, 4)[:-1]
    path = tmp_path / "src" / "open.stl"
    path.parent.mkdir()
    pv.PolyData(box.points, faces=faces.ravel()).save(str(path))
    w = make_window(import_path=path)
    w.act_import.trigger()
    p = w.properties
    assert p.check_values["watertight"].text() == "no"
    assert p.check_values["watertight"].property("warn") == "true"
    assert p.check_values["open"].text() == "3" and p.check_values["open"].property("warn") == "true"
    assert p.check_values["triangles"].property("warn") == "false"
    assert "watertight: no" in w.console.text()


def test_telemetry_has_a_triangles_field(make_window) -> None:
    w = make_window()
    assert "triangles" in w.act_tel_fields and w.act_tel_fields["triangles"].text() == "Triangles"


def test_import_action_is_in_the_file_menu(make_window) -> None:
    w = make_window()
    file_menu = w.menuBar().actions()[0].menu()
    assert w.act_import in file_menu.actions() and w.act_import.text() == "&Import Geometry..."


def test_works_without_viewer(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl, with_viewer=False)
    w.act_import.trigger()
    assert len(w.project.sim.geometry.parts) == 1 and w.scene is None
    assert w.properties.check_values["watertight"].text() == "yes"


def test_selecting_a_part_twice_runs_the_check_once(make_window, sphere_stl: Path, monkeypatch) -> None:
    import vortexcfd.geometry.checks as checks

    calls = []
    original = checks.check_surface
    monkeypatch.setattr(checks, "check_surface", lambda mesh: (calls.append(1), original(mesh))[1])
    w = make_window(import_path=sphere_stl)
    w.act_import.trigger()  # the report is computed here
    for _ in range(2):
        w._select_root()
        w.tree.setCurrentItem(w._items[("part", 0)])
    w.properties.refresh()
    assert len(calls) == 1


def test_part_edges_are_off_until_wireframe(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl)
    w.act_import.trigger()
    actor = w.scene.actors[0]
    assert not actor.prop.show_edges
    w.top_bar.wireframe_button.click()
    assert actor.prop.show_edges
    w.top_bar.wireframe_button.click()
    assert not actor.prop.show_edges


def test_part_properties_show_the_read_only_patch_name(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl)
    w.act_import.trigger()
    w.act_import.trigger()
    w.tree.setCurrentItem(w._items[("part", 0)])
    p = w.properties
    assert p._rows["patch"].isVisible() and p.patch_label.isReadOnly() and p.patch_label.text() == "wing"
    # Different part names can sanitize to the same patch name: first free suffix.
    w.project.update_part(0, name="Wing 1")
    w.project.update_part(1, name="Wing_1")
    assert p.patch_label.text() == "Wing_1"
    w.tree.setCurrentItem(w._items[("part", 1)])
    assert p.patch_label.text() == "Wing_1_1"
    w.project.update_part(1, name="inlet")  # a domain boundary name
    assert p.patch_label.text() == "inlet_1"
    w._select_root()
    assert not p._rows["patch"].isVisible()


# -- inward normals (docs/QUESTIONS.md item 56) ------------------------------------------------------------


def test_signed_volume_flags_inward_normals_without_flipping() -> None:
    from vortexcfd.geometry.checks import check_surface

    sphere = pv.Sphere(radius=1.0, theta_resolution=32, phi_resolution=32)
    out = check_surface(sphere)
    assert out.watertight and out.signed_volume == pytest.approx(4 / 3 * np.pi, rel=0.02)
    assert not out.normals_inward and "inward" not in out.summary()
    inward = check_surface(sphere.flip_faces())
    assert inward.signed_volume == pytest.approx(-out.signed_volume) and inward.normals_inward
    assert inward.summary().endswith("normals point inward")
    ellipsoid = pv.ParametricEllipsoid(0.3, 0.2, 0.2, u_res=32, v_res=16, w_res=16).triangulate().clean()
    assert check_surface(ellipsoid).normals_inward  # the item 54 body: inward as generated
    open_disc = check_surface(pv.Disc().triangulate().flip_faces())
    assert not open_disc.watertight and not open_disc.normals_inward  # only for closed surfaces


def test_import_warns_about_inward_normals(make_window, tmp_path: Path) -> None:
    path = tmp_path / "src" / "inside_out.stl"
    path.parent.mkdir()
    pv.Sphere(radius=1.0, theta_resolution=16, phi_resolution=16).flip_faces().save(str(path))
    w = make_window(import_path=path, with_viewer=False)
    w.act_import.trigger()
    text = w.console.text()
    assert "WARNING" in text and "normals point inward" in text and "not changed" in text
    w.tree.setCurrentItem(w._items[("part", 0)])
    p = w.properties
    label = p.check_values["normals"]
    assert p._rows["check_normals"].isVisible() and label.text() == "point inward"
    assert label.property("warn") == "true"
    # the copied file is untouched: still inside out
    from vortexcfd.geometry.checks import check_surface

    copied = w.project.resolve_part_path(w.project.sim.geometry.parts[0])
    assert check_surface(pv.read(str(copied))).normals_inward


def test_outward_surface_shows_outward(make_window, sphere_stl: Path) -> None:
    w = make_window(import_path=sphere_stl, with_viewer=False)
    w.act_import.trigger()
    w.tree.setCurrentItem(w._items[("part", 0)])
    assert w.properties.check_values["normals"].text() == "outward"
    assert w.properties.check_values["normals"].property("warn") == "false"
    assert "inward" not in w.console.text()
