"""Refinement volumes in the GUI (D-103): tree node, actions, properties editing, viewer outline."""

from pathlib import Path

import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import BoxShape, Part
from vortexcfd.core.project import Project
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import MainWindow
from vortexcfd.gui.scene import VolumeView
from vortexcfd.workflow import meshing


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path):
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    pv.Box(bounds=(0, 2, 0, 1, 0, 1)).triangulate().save(str(folder / "geometry" / "box.stl"))
    project = Project.new("Demo")
    project.add_part(Part(name="box", source_file="geometry/box.stl", units="m"))
    project.save(folder / "p.json")
    w = MainWindow(project, FakeDialogs(), with_viewer=True)
    qtbot.addWidget(w)
    w.show()
    yield w
    assert not w.project.observer_errors
    w.project.save = lambda *a, **k: None
    w.close()


def _children(item) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]


def test_volumes_node_under_mesh_and_add_by_shape(window: MainWindow) -> None:
    w = window
    mesh = w._items[("mesh", None)]
    assert _children(mesh) == ["Refinement volumes (0)"]
    for shape in ("box", "cylinder", "sphere", "cone"):
        w.add_refinement_volume(shape)
    assert _children(w._items[("refinement_volumes", None)]) == [
        "box (box)", "cylinder (cylinder)", "sphere (sphere)", "cone (cone)"]
    assert w._selection == ("refinement_volume", 3)  # the new volume is selected
    assert w.project.undo_label == "Add refinement volume 'cone'"
    w.project.undo()
    assert len(w.project.sim.refinement_volumes) == 3


def test_viewer_draws_enabled_volumes_and_highlights_the_selected_one(window: MainWindow) -> None:
    w = window
    w.add_refinement_volume("box")
    w.add_refinement_volume("sphere")
    view = w.volume_view
    assert isinstance(view, VolumeView)
    ids = [v.id for v in w.project.sim.refinement_volumes]
    assert set(view.actors) == set(ids) and view.selected_id == ids[1]
    assert f"{VolumeView.PREFIX}{ids[0]}" in w.viewer.actors
    face, edges = view.actors[ids[1]]
    assert edges.prop.line_width == 2  # selected
    w.tree.setCurrentItem(w._items[("refinement_volume", 0)])
    w.toggle_selected_volume()
    assert set(view.actors) == {ids[1]}  # a disabled volume is not drawn
    assert "(disabled)" not in w._items[("refinement_volume", 0)].text(0)
    assert w._items[("refinement_volume", 0)].toolTip(0).startswith("Disabled")


def test_properties_edit_every_field_with_one_undo_step_each(window: MainWindow) -> None:
    w = window
    w.add_refinement_volume("box")
    panel = w.properties
    assert panel._rows["vol_box_centre"].isVisibleTo(panel) and not panel._rows["vol_cone_point1"].isVisibleTo(panel)
    assert panel.vol_shape_fields[("box", "size")].spins[0].suffix() == " m"
    assert panel.vol_shape_fields[("box", "pitch_deg")].suffix() == "°"
    vid = w.project.sim.refinement_volumes[0].id
    spin = panel.vol_shape_fields[("box", "yaw_deg")]
    spin.setValue(30.0)
    spin.editingFinished.emit()
    assert w.project.volume(vid).shape.yaw_deg == 30.0
    assert w.project.undo_label == "Edit refinement volume 'box' (shape)"
    panel.vol_target.setValue(0.02)
    panel.vol_target.editingFinished.emit()
    assert w.project.volume(vid).target_size == 0.02
    assert "level" in panel.vol_achieved.text() and "requested 0.02 m" in panel.vol_achieved.text()
    assert panel.vol_cells.text().startswith("+")
    panel.vol_name.setText("near_body")
    panel.vol_name.editingFinished.emit()
    assert w._items[("refinement_volume", 0)].text(0) == "near_body (box)"
    panel.vol_name.setText("bad name")
    panel.vol_name.editingFinished.emit()
    assert w.project.volume(vid).name == "near_body" and panel.vol_name.text() == "near_body"  # reverted
    for _ in range(3):
        w.project.undo()
    assert w.project.volume(vid).shape.yaw_deg == 0.0


def test_viewer_previews_an_edit_before_it_is_committed(window: MainWindow) -> None:
    w = window
    w.add_refinement_volume("sphere")
    vid = w.project.sim.refinement_volumes[0].id
    before = w.volume_view.actors[vid][0].GetBounds()
    radius = w.properties.vol_shape_fields[("sphere", "radius")]
    radius.setValue(radius.value() * 2)  # valueChanged only: not committed
    after = w.volume_view.actors[vid][0].GetBounds()
    assert after[1] - after[0] > 1.9 * (before[1] - before[0])
    assert w.project.undo_label == "Add refinement volume 'sphere'"  # nothing committed yet


def test_wake_duplicate_delete_and_domain_status(window: MainWindow) -> None:
    w = window
    w.tree.setCurrentItem(w._items[("part", 0)])
    w.add_wake_volume()
    wake = w.project.sim.refinement_volumes[0]
    assert wake.name == "wake" and isinstance(wake.shape, BoxShape)
    # the 2 x 1 x 1 m part: 4 m long from its rear (x = 2), 1.1 m wide, 2 m high
    assert wake.shape.centre == pytest.approx((4.0, 0.5, 0.5)) and wake.shape.size == pytest.approx((4.0, 1.1, 2.0))
    assert w.properties.vol_status.text().startswith("inside the domain")
    w.duplicate_selected_volume()
    assert [v.name for v in w.project.sim.refinement_volumes] == ["wake", "wake_2"]
    vid = w.project.sim.refinement_volumes[1].id
    w.project.update_refinement_volume(vid, shape={"centre": (500.0, 0.0, 0.0)})
    w.tree.setCurrentItem(w._items[("refinement_volume", 1)])
    assert w.properties.vol_status.text() == "Ignored: outside the domain"
    assert w.properties.vol_status.property("warn") == "true"  # the warning style, never an error
    assert w._items[("refinement_volume", 1)].toolTip(0) == "Ignored: outside the domain"
    assert w.project.sim.refinement_volumes[1].enabled and meshing.readiness(w.project) is None  # not blocking
    w.delete_selected_volume()
    assert [v.name for v in w.project.sim.refinement_volumes] == ["wake"]
    assert w._selection == ("refinement_volumes", None)


def test_mesh_estimate_shows_the_volume_cells(window: MainWindow) -> None:
    w = window
    w.tree.setCurrentItem(w._items[("mesh", None)])
    assert w.properties.mesh_volume_cells.text() == "none"
    w.add_refinement_volume("box")
    w.tree.setCurrentItem(w._items[("mesh", None)])
    text = w.properties.mesh_volume_cells.text()
    assert text.startswith("+") and "1 volume" in text
    assert "counted twice" in w.properties.mesh_volume_cells.toolTip()
