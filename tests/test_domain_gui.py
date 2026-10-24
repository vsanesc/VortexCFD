"""Tests for the domain in the GUI: tree, properties, viewer, telemetry."""

from pathlib import Path

import pytest
import pyvista as pv
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
def make_window(qtbot: QtBot, tmp_path: Path):
    made: list[MainWindow] = []

    def make(with_part: bool = True, with_viewer: bool = True) -> MainWindow:
        folder = tmp_path / "proj"
        (folder / "geometry").mkdir(parents=True)
        project = Project.new("Demo")
        if with_part:
            # A 2 x 1 x 1 m box: L = 2 m.
            pv.Box(bounds=(0, 2, 0, 1, 0, 1)).triangulate().save(str(folder / "geometry" / "box.stl"))
            project.add_part(Part(name="box", source_file="geometry/box.stl", units="m"))
        project.save(folder / "p.json")
        w = MainWindow(project, FakeDialogs(), with_viewer=with_viewer)
        qtbot.addWidget(w)
        w.show()
        made.append(w)
        return w

    yield make
    for w in made:
        assert not w.project.observer_errors
        w.project.save = lambda *a, **k: None
        w.close()


def _children(item) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]


def test_tree_has_fluid_domain_with_boundaries_and_walls(make_window) -> None:
    w = make_window()
    fluid = w._items[("fluid_domain", None)]
    assert _children(fluid) == ["inlet", "outlet", "sides", "top", "bottom", "box (wall)"]
    w.project.update_domain(symmetry="y_min")
    fluid = w._items[("fluid_domain", None)]
    assert _children(fluid) == ["inlet", "outlet", "sides", "top", "bottom", "symmetry", "box (wall)"]
    w.project.update_domain(enabled=False)
    assert _children(w._items[("fluid_domain", None)]) == ["box (wall)"]


def test_domain_properties_show_values_and_read_only_box(make_window) -> None:
    w = make_window()
    w.tree.setCurrentItem(w._items[("fluid_domain", None)])
    p = w.properties
    assert p._rows["dom_upstream"].isVisible() and not p._rows["name"].isVisible()
    assert [p.domain_fields[k].value() for k in ("upstream", "downstream", "lateral", "vertical")] == [5, 10, 5, 5]
    assert p.domain_fields["upstream"].suffix() == " L"
    assert p.domain_enabled.isChecked() and p.domain_symmetry.currentData() == "none"
    assert p.domain_length.text() == "2 m: the parts' largest extent" and "largest extent" in p.domain_length.toolTip()
    assert p.domain_fields["upstream"].other.text() == "= 10 m"  # the physical form, live (D-148)
    assert p.domain_size.isReadOnly() and p.domain_size.text() == "32 × 21 × 21 m"
    assert not p.domain_warning.text()


def test_editing_a_multiplier_is_one_undo_step(make_window) -> None:
    w = make_window()
    w.tree.setCurrentItem(w._items[("fluid_domain", None)])
    p = w.properties
    before = len(w.project._undo)
    p.domain_fields["upstream"].setValue(3.0)
    p.domain_fields["upstream"].editingFinished.emit()
    assert w.project.sim.domain.upstream == 3.0
    assert len(w.project._undo) == before + 1
    assert p.domain_size.text() == "28 × 21 × 21 m"  # 3*2 + 2 + 10*2
    w.act_undo.trigger()
    assert w.project.sim.domain.upstream == 5.0 and p.domain_fields["upstream"].value() == 5.0


def test_symmetry_and_enabled_go_through_update_domain(make_window) -> None:
    w = make_window()
    w.tree.setCurrentItem(w._items[("fluid_domain", None)])
    p = w.properties
    p.domain_symmetry.setCurrentIndex(p.domain_symmetry.findData("y_min"))
    assert w.project.sim.domain.symmetry == "y_min"
    p.domain_enabled.setChecked(False)
    assert w.project.sim.domain.enabled is False
    assert w.project.undo_label == "Edit domain (enabled)"


def test_rejected_domain_edit_reverts_and_reports(make_window, monkeypatch) -> None:
    w = make_window()
    w.tree.setCurrentItem(w._items[("fluid_domain", None)])
    p = w.properties

    def boom(**fields):
        raise ValueError("domain rejected")

    monkeypatch.setattr(w.project, "update_domain", boom)
    p.domain_fields["lateral"].setValue(9.0)
    p.domain_fields["lateral"].editingFinished.emit()
    assert p.domain_fields["lateral"].value() == 5.0
    assert "domain rejected" in w.statusBar().currentMessage()


def test_warnings_in_warning_color(make_window) -> None:
    w = make_window(with_part=False)
    w.tree.setCurrentItem(w._items[("fluid_domain", None)])
    p = w.properties
    assert "No parts" in p.domain_warning.text() and p.domain_warning.property("warn") == "true"
    assert p.domain_length.text() == "— (import a part)" and p.domain_size.text() == "—"


def test_viewer_draws_translucent_wireframe_box(make_window) -> None:
    w = make_window()
    view = w.domain_view
    assert view.box_actor is not None and "domain_box" in w.viewer.renderer.actors
    prop = view.box_actor.prop
    assert prop.style.lower() == "wireframe" and prop.opacity < 1.0
    assert pv.Color(prop.color).hex_rgb.lower() == w._theme.border_active.lower()
    assert w.viewer.renderer.actors["domain_box"].GetBounds()[1] == pytest.approx(2 + 20)
    w.act_toggle_domain.trigger()  # View > Domain Box off
    assert view.box_actor is None and "domain_box" not in w.viewer.renderer.actors
    w.act_toggle_domain.trigger()
    assert view.box_actor is not None
    w.project.update_domain(enabled=False)  # synced from the Project observer
    assert view.box_actor is None
    w.act_undo.trigger()
    assert view.box_actor is not None


def test_no_box_without_parts(make_window) -> None:
    w = make_window(with_part=False)
    assert w.domain_view.box_actor is None


def test_selecting_a_boundary_highlights_its_face(make_window) -> None:
    w = make_window()
    assert w.domain_view.highlight_actor is None
    w.tree.setCurrentItem(w._items[("boundary_inlet", None)])
    actor = w.domain_view.highlight_actor
    assert actor is not None
    assert pv.Color(actor.prop.color).hex_rgb.lower() == w._theme.accent.lower()  # the selection colour (D-144)
    xmin, xmax, *_ = actor.GetBounds()
    assert xmin == xmax == pytest.approx(-10.0)  # x_min face: 0 - 5 * L
    w.tree.setCurrentItem(w._items[("boundary_sides", None)])
    ymin, ymax = w.domain_view.highlight_actor.GetBounds()[2:4]
    assert ymin < 0 < ymax  # both side faces
    w.tree.setCurrentItem(w._items[("part", 0)])
    assert w.domain_view.highlight_actor is None


def test_telemetry_domain_field(make_window) -> None:
    w = make_window()
    assert dict(w.telemetry_rows)["Domain"] == "32 × 21 × 21 m"
    w.project.update_domain(enabled=False)
    assert dict(w.telemetry_rows)["Domain"] == "—"
    assert "domain" in w.act_tel_fields and w.act_tel_fields["domain"].text() == "Domain"


def test_works_without_viewer(make_window) -> None:
    w = make_window(with_viewer=False)
    assert w.domain_view is None
    w.tree.setCurrentItem(w._items[("boundary_outlet", None)])
    assert not w.properties.info_label.isVisible()  # the face has its Boundary type row (D-147)
    assert w.properties._rows["face_type"].isVisible() and w.properties.face_type.currentData() == "pressure_outlet"
