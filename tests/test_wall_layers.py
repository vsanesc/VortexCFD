"""Prism layers on a wall domain face (D-161, QUESTIONS 227; off by default) [NUMERICS-REVIEW]: the model, the
snappyHexMeshDict layers entry only for a ticked wall face, the mesh hash, Show in OpenFOAM file and the face node.
The public benchmarks' dictionaries are unchanged (scripts/validation/public_dicts.py, diff -r against main)."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from tests.test_boundary_types import sphere_project
from vortexcfd.core.model import Domain
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.workflow import foam_entries as fe
from vortexcfd.workflow import meshing


def snappy_layers(project) -> dict:
    job = meshing.prepare_job(project)
    return read_foam_file(job.case_dir / "system" / "snappyHexMeshDict")["addLayersControls"]["layers"]


def test_the_model_lists_known_faces_once() -> None:
    assert Domain().wall_layers == []  # off by default
    assert Domain(wall_layers=["top", "bottom", "top"]).wall_layers == ["bottom", "top"]
    with pytest.raises(ValidationError, match="unknown domain face"):
        Domain(wall_layers=["roof"])


def test_only_a_ticked_wall_face_gets_layers(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    default = snappy_layers(project)
    assert "bottom" not in default and "top" not in default
    project.set_face_type("bottom", "wall")
    assert snappy_layers(project) == default  # a wall face: still no layers until ticked
    project.set_face_layers("bottom", True)
    layers = snappy_layers(project)
    part = next(v for k, v in layers.items() if k != "bottom")
    assert layers["bottom"] == part  # the parts' count
    project.set_face_layers("top", True)  # ticked on a slip face: nothing written
    assert "top" not in snappy_layers(project)
    project.set_face_type("bottom", "moving_wall")  # a moving wall keeps them
    assert "bottom" in snappy_layers(project)
    project.set_face_type("bottom", "slip")  # no longer a wall: none, though still ticked
    assert "bottom" not in snappy_layers(project) and project.sim.domain.wall_layers == ["bottom", "top"]


def test_the_mesh_hash_changes_only_with_the_written_layers(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    base = meshing.inputs_hash(project)
    project.set_face_layers("top", True)  # a slip face: nothing written, the mesh stays up to date
    assert meshing.inputs_hash(project) == base
    project.set_face_type("top", "wall")
    wall = meshing.inputs_hash(project)
    project.set_face_layers("top", False)
    assert meshing.inputs_hash(project) != wall  # the layers on the wall are part of the mesh
    project.undo()
    assert meshing.inputs_hash(project) == wall


def test_show_in_openfoam_file(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    project.set_face_type("top", "wall")
    entries = fe.entries_for(project, "face_layers:top")
    assert entries == [fe.Entry("system/snappyHexMeshDict", ("addLayersControls", "layers"))]
    assert fe.is_mapped("face_layers:top")


def test_the_face_node_has_the_check_box_for_walls_only(qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.main_window import MainWindow

    w = MainWindow(sphere_project(tmp_path), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    try:
        p = w.properties
        w.tree.setCurrentItem(w._items[("boundary_top", None)])
        assert not p._rows["face_layers"].isVisible()  # a slip face
        w.set_boundary_type("top", "wall")
        w.tree.setCurrentItem(w._items[("boundary_top", None)])
        assert p._rows["face_layers"].isVisible() and not p.face_layers.isChecked()
        assert "prism layers" in p.face_layers.toolTip()
        p.face_layers.setChecked(True)
        assert w.project.sim.domain.wall_layers == ["top"]
        assert w.project.undo_label == "Prism layers on top: on"
        menu = p.row_menu("face_layers")
        menu.actions()[0].trigger()
        assert w.dialogs.foam_files[-1][0] == "face_layers:top"
        w.act_undo.trigger()
        assert w.project.sim.domain.wall_layers == [] and not p.face_layers.isChecked()
    finally:
        w.project.save = lambda *a, **k: None
        w.close()


def test_presets_and_snapshots_carry_the_layers(tmp_path: Path) -> None:
    from vortexcfd.core.model import Simulation
    from vortexcfd.core.presets import apply_preset, preset_from_simulation
    from vortexcfd.workflow.snapshots import setup_summary

    project = sphere_project(tmp_path)
    plain = setup_summary(project.sim)
    assert not any("prism layers" in k for k in plain)  # nothing new for a project without them
    project.set_face_type("bottom", "wall")
    project.set_face_layers("bottom", True)
    assert setup_summary(project.sim)["domain: bottom prism layers"] == "on"
    preset = preset_from_simulation(project.sim, "Road")
    assert preset.domain.wall_layers == ["bottom"]
    assert apply_preset(Simulation(name="t"), preset).domain.wall_layers == ["bottom"]
