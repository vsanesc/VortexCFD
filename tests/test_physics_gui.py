"""Physics, Inflow and Solvers editors and the y+ / layer sizing rows of the Mesh node."""

import pytest
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.project import Project
from vortexcfd.foam.physics_case import inlet_turbulence
from vortexcfd.gui.main_window import MainWindow


@pytest.fixture
def window(qtbot: QtBot):
    w = MainWindow(Project.new("phys"), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    yield w
    assert not w.project.observer_errors
    w.project.save = lambda *a, **k: None
    w.close()


def _select(w: MainWindow, kind: str) -> None:
    w.tree.setCurrentItem(w._items[(kind, None)])


def test_tree_has_inflow_under_physics(window: MainWindow) -> None:
    physics = window._items[("physics", None)]
    assert [physics.child(i).text(0) for i in range(physics.childCount())] == ["Inflow"]
    assert window._items[("inflow", None)].parent() is physics


def test_physics_editor_shows_and_commits(window: MainWindow) -> None:
    _select(window, "physics")
    p = window.properties
    f = p.group_fields["physics"]
    assert p._rows["physics_nu"].isVisible() and not p._rows["inflow_speed"].isVisible()
    assert f["flow"].currentText() == "incompressible_steady"
    assert f["turbulence_model"].currentText() == "kOmegaSST"
    assert f["nu"].value() == pytest.approx(1.5e-5) and f["nu"].text() == "1.5e-05"
    assert f["rho_ref"].value() == pytest.approx(1.225)
    f["nu"].setText("2e-5")
    f["nu"].editingFinished.emit()
    assert window.project.sim.physics.nu == pytest.approx(2e-5)
    assert window.project.undo_label == "Edit physics (nu)" and f["nu"].text() == "2e-05"
    f["rho_ref"].setValue(1.0)
    f["rho_ref"].editingFinished.emit()
    assert window.project.sim.physics.rho_ref == 1.0
    window.act_undo.trigger()
    assert window.project.sim.physics.rho_ref == pytest.approx(1.225)


def test_invalid_physics_value_reverts_with_a_message(window: MainWindow) -> None:
    _select(window, "physics")
    f = window.properties.group_fields["physics"]
    f["nu"].setText("-3")
    f["nu"].editingFinished.emit()
    assert window.project.sim.physics.nu == pytest.approx(1.5e-5) and f["nu"].text() == "1.5e-05"
    assert "nu" in window.statusBar().currentMessage()
    f["nu"].setText("")  # not a number
    f["nu"].editingFinished.emit()
    assert window.project.sim.physics.nu == pytest.approx(1.5e-5)


def test_inflow_editor_and_computed_turbulence(window: MainWindow) -> None:
    _select(window, "inflow")
    p = window.properties
    f = p.group_fields["inflow"]
    assert [f[k].value() for k in ("speed", "alpha_deg", "turbulence_intensity", "viscosity_ratio")] == [20, 0, 0.01, 10]
    assert f["speed"].suffix() == " m/s" and f["alpha_deg"].suffix() == "°"
    k, omega = inlet_turbulence(20, 0.01, 1.5e-5, 10)
    assert k == pytest.approx(0.06) and omega == pytest.approx(0.06 / 1.5e-4)
    assert p.inflow_k.text().startswith("0.06 ") and p.inflow_omega.text().startswith("400 ")
    assert p._rows["inflow_k"].isVisible()
    f["speed"].setValue(40.0)
    f["speed"].editingFinished.emit()
    assert window.project.sim.inflow.speed == 40.0
    assert p.inflow_k.text().startswith("0.24 ")  # k = 1.5 (V I)^2 follows the speed
    f["alpha_deg"].setValue(5.0)
    f["alpha_deg"].editingFinished.emit()
    assert window.project.sim.inflow.alpha_deg == 5.0
    assert window.project.undo_label == "Edit inflow (alpha_deg)"
    window.act_undo.trigger()
    assert f["alpha_deg"].value() == 0.0


def test_solvers_editor(window: MainWindow) -> None:
    _select(window, "solvers")
    p = window.properties
    f = p.group_fields["solvers"]
    assert (f["iterations"].value(), f["write_interval"].value(), f["relaxation"].currentText()) == (1000, 200, "robust")
    assert not p.info_label.isVisible()
    f["iterations"].setValue(250)
    f["iterations"].editingFinished.emit()
    assert window.project.sim.solvers.iterations == 250
    assert window.project.undo_label == "Edit solver (iterations)"


def test_mesh_node_has_layer_sizing_rows(window: MainWindow) -> None:
    _select(window, "mesh")
    p = window.properties
    f = p.mesh_fields
    assert f["layer_sizing"].currentText() == "relative" and f["target_yplus"].value() == 1.0
    f["target_yplus"].setValue(30.0)
    f["target_yplus"].editingFinished.emit()
    assert window.project.sim.mesh.target_yplus == 30.0
    f["layer_sizing"].setCurrentText("absolute_yplus")
    assert window.project.sim.mesh.layer_sizing == "absolute_yplus"
    assert window.project.undo_label == "Edit mesh (layer_sizing)"


def test_group_editors_are_hidden_on_other_nodes(window: MainWindow) -> None:
    _select(window, "geometry")
    p = window.properties
    for gkind in ("physics", "inflow", "solvers"):
        assert not any(p._rows[f"{gkind}_{k}"].isVisible() for k in p.group_fields[gkind])
    assert not p._rows["inflow_k"].isVisible() and p.info_label.isVisible()
