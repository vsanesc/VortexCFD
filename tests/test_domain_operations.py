"""The domain as an operation (D-078): Generate domain in the "Empty" analysis, the preset's shape on
the first import of an "External flow" project, shape edits as undoable steps that make the mesh out
of date, the Fluid Region node and the viewer highlight of a boundary role."""

from pathlib import Path

import numpy as np
import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Simulation
from vortexcfd.core.presets import BUILTIN_PRESETS, Preset, apply_preset
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_record import MeshRecord, write_mesh_record
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.geometry.domain_surface import ROLE_ARRAY
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.domain_dialog import GenerateDomainDialog
from vortexcfd.gui.main_window import MainWindow
from vortexcfd.gui.meshing import case_dir_for, inputs_hash, readiness
from tests.test_import import wait_geometry


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


@pytest.fixture
def make_window(qtbot: QtBot, tmp_path: Path):
    made: list[MainWindow] = []

    def make(preset: Preset = BUILTIN_PRESETS[1], with_part=True, with_viewer=False) -> MainWindow:
        sim = apply_preset(Simulation(name="Demo"), preset)
        project = Project.create(tmp_path, f"proj{len(made)}", sim)
        src = tmp_path / "src"
        src.mkdir(exist_ok=True)
        pv.Sphere(radius=0.5).save(str(src / "ball.stl"))
        w = MainWindow(project, FakeDialogs(import_path=src / "ball.stl", units="m"), with_viewer=with_viewer)
        w._qtbot = qtbot
        qtbot.addWidget(w)
        w.show()
        if with_part:
            w.act_import.trigger()
            wait_geometry(qtbot, w)
        made.append(w)
        return w

    yield make
    for w in made:
        w.geometry_worker.wait(60)
        assert not w.project.observer_errors
        w.close()


def _children(item) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]


def test_empty_analysis_creates_nothing_and_offers_generate_domain(make_window) -> None:
    w = make_window()
    assert not w.project.sim.domain.enabled  # the import did not create a domain
    fluid = w._items[("fluid_domain", None)]
    assert fluid.text(0) == "Fluid Domain (not generated)"
    assert _children(fluid) == ["Generate domain…", "ball (wall)"]
    region = w._items[("fluid_region", None)]
    assert region.text(0) == "Fluid Region (domain minus parts)"
    assert readiness(w.project) == "Generate the domain first (Regions > Domain)."
    w.tree.setCurrentItem(fluid)
    assert w.properties._rows["dom_generate"].isVisibleTo(w.properties)
    assert not w.properties._rows["dom_shape"].isVisibleTo(w.properties)
    w.tree.setCurrentItem(region)
    assert w.properties.fluid_definition.text() == "domain minus parts"
    assert w.properties.fluid_domain.text() == "not generated"


def test_generate_domain_is_one_undoable_step(make_window) -> None:
    w = make_window()
    w.dialogs.domain_fields = {"enabled": True, "shape": "bullet", "symmetry": "none", "parts": None,
                               "radius": 6.0, "downstream": 8.0}
    w.tree.setCurrentItem(w._items[("part", 0)])  # the selected part is offered checked
    before = len(w.project._undo)
    w._on_item_activated(w._items[("fluid_domain", None)].child(0))  # the Generate domain... node
    assert w.dialogs.domain_asked == [(["ball"], ["ball"])]
    domain = w.project.sim.domain
    assert (domain.enabled, domain.shape, domain.radius, domain.downstream) == (True, "bullet", 6.0, 8.0)
    assert len(w.project._undo) == before + 1 and w.project.undo_label == "Generate domain (Bullet)"
    assert _children(w._items[("fluid_domain", None)]) == ["inlet", "outlet", "farfield", "ball (wall)"]
    assert readiness(w.project) is None
    w.tree.setCurrentItem(w._items[("fluid_region", None)])
    assert w.properties.fluid_domain.text().startswith("Bullet, ")
    assert "locationInMesh" in w.properties.fluid_location.text()
    w.act_undo.trigger()
    assert not w.project.sim.domain.enabled
    assert _children(w._items[("fluid_domain", None)])[0] == "Generate domain…"


def test_generate_domain_without_parts_asks_for_a_part(make_window) -> None:
    w = make_window(with_part=False)
    w.act_generate_domain.trigger()
    assert w.dialogs.domain_asked == [] and "Import a part first" in w.statusBar().currentMessage()


def test_external_flow_generates_the_presets_shape_on_import(make_window) -> None:
    preset = Preset(name="Bullets", analysis_type="external", domain={"shape": "c_type", "radius": 4.0})
    w = make_window(preset)
    domain = w.project.sim.domain
    assert domain.enabled and (domain.shape, domain.radius) == ("c_type", 4.0)
    assert _children(w._items[("fluid_domain", None)]) == ["inlet", "outlet", "farfield", "sides", "ball (wall)"]
    assert w._domain_box.shape == "c_type" and w._domain_box.volume > 0


def test_shape_and_size_edits_are_undoable_and_make_the_mesh_out_of_date(make_window) -> None:
    w = make_window(BUILTIN_PRESETS[0])
    project = w.project
    report = MeshReport(100, 300, 50, 10.0, 5.0, 0.5, 0, True)
    write_mesh_record(case_dir_for(project), MeshRecord(report, inputs_hash(project), ("ball",)))
    w._load_mesh_record(project)
    w._update_mesh_stale()
    assert not w.mesh_stale
    w.tree.setCurrentItem(w._items[("fluid_domain", None)])
    props = w.properties
    before = len(project._undo)
    props.domain_shape.setCurrentIndex(props.domain_shape.findData("bullet"))
    assert project.sim.domain.shape == "bullet" and len(project._undo) == before + 1
    assert w.mesh_stale
    assert props._rows["dom_radius"].isVisibleTo(props) and not props._rows["dom_upstream"].isVisibleTo(props)
    props.domain_fields["radius"].setValue(7.0)
    props.domain_fields["radius"].editingFinished.emit()
    assert project.sim.domain.radius == 7.0 and len(project._undo) == before + 2
    props.domain_shape.setCurrentIndex(props.domain_shape.findData("c_type"))
    assert props._row_labels["dom_lateral"].full_text() == "Half-width"
    w.act_undo.trigger()
    w.act_undo.trigger()
    assert project.sim.domain.shape == "bullet" and project.sim.domain.radius == 5.0
    w.act_undo.trigger()
    assert project.sim.domain.shape == "box" and not w.mesh_stale


@pytest.mark.parametrize("shape", ["box", "bullet", "c_type"])
def test_viewer_draws_the_surface_and_highlights_a_role(make_window, shape: str) -> None:
    w = make_window(Preset(name="P", domain={"shape": shape}), with_viewer=True)
    view = w.domain_view
    assert view.box_actor is not None and view.highlight_actor is None
    surface = view.surface(w._domain_box)
    w.tree.setCurrentItem(w._items[("boundary_inlet", None)])
    inlet = int(np.count_nonzero(np.asarray(surface.cell_data[ROLE_ARRAY]) == w._domain_box.roles.index("inlet")))
    assert view.highlight_actor is not None and view.highlight_cells == inlet > 0
    w.tree.setCurrentItem(w._items[("part", 0)])
    assert view.highlight_actor is None


def test_generate_domain_dialog(qtbot: QtBot) -> None:
    from vortexcfd.core.model import Domain

    dialog = GenerateDomainDialog(["a", "b"], ["a"], Domain())
    qtbot.addWidget(dialog)
    assert dialog.checked_parts() == ["a"]
    dialog.set_shape("c_type")
    assert dialog._labels["lateral"].text() == "Half-width" and not dialog.spins["upstream"].isVisibleTo(dialog)
    fields = dialog.fields()
    assert fields == {"enabled": True, "shape": "c_type", "symmetry": "none", "parts": ["a"], "radius": 5.0,
                      "downstream": 10.0, "lateral": 5.0}
    dialog.set_checked(["a", "b"])
    assert dialog.fields()["parts"] is None  # every part: None
    dialog.set_checked([])
    assert dialog.fields() is None and not dialog.ok.isEnabled()
