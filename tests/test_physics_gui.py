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
    assert set(f) == {"iterations", "write_interval", "cores", "relaxation"}  # residual targets: Stopping Criteria node


def test_cores_field_is_limited_to_the_physical_cores(window: MainWindow) -> None:
    """D-063: the Cores row says how many physical cores the machine has and cannot exceed them;
    a project asking for more (edited elsewhere) cannot run."""
    from vortexcfd.foam.parallel import physical_cores
    from vortexcfd.gui import solving

    _select(window, "solvers")
    box = window.properties.group_fields["solvers"]["cores"]
    n = physical_cores()
    assert box.value() == 1 and box.maximum() == n and box.minimum() == 1
    from PySide6.QtWidgets import QLabel

    assert f"Cores ({n} physical)" in [label.text() for label in window.properties.findChildren(QLabel)]
    box.setValue(min(4, n))
    box.editingFinished.emit()
    assert window.project.sim.solvers.cores == min(4, n)
    assert window.project.undo_label == "Edit solver (cores)"
    window.project.update_solver(cores=n + 1)
    assert solving.physics_problem(window.project) == f"{n + 1} cores requested; this machine has {n} physical cores."


def test_mesh_node_has_layer_sizing_rows(window: MainWindow) -> None:
    _select(window, "mesh")
    p = window.properties
    f = p.mesh_fields
    assert f["layer_sizing"].currentText() == "relative" and f["target_yplus"].value() == 1.0
    assert not p.mesh_yplus_note.isVisible()  # relative sizing: no y+ guidance
    f["target_yplus"].setValue(30.0)
    f["target_yplus"].editingFinished.emit()
    assert window.project.sim.mesh.target_yplus == 30.0
    f["layer_sizing"].setCurrentText("absolute_yplus")
    assert window.project.sim.mesh.layer_sizing == "absolute_yplus"
    assert window.project.undo_label == "Edit mesh (layer_sizing)"
    assert p.mesh_yplus_note.isVisible() and p.mesh_yplus_note.objectName() == "muted"
    assert "Cf about 6% low at y+ 1, about 3.6% low at y+ 0.5" in p.mesh_yplus_note.text()
    _select(window, "physics")
    assert not p.mesh_yplus_note.isVisible()


def test_group_editors_are_hidden_on_other_nodes(window: MainWindow) -> None:
    _select(window, "geometry")
    p = window.properties
    for gkind in ("physics", "inflow", "solvers"):
        assert not any(p._rows[f"{gkind}_{k}"].isVisible() for k in p.group_fields[gkind])
    assert not p._rows["inflow_k"].isVisible() and p.info_label.isVisible()


def _project_with_sphere(tmp_path):
    import pyvista as pv

    from vortexcfd.core.model import Part

    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    pv.Sphere(radius=0.5, theta_resolution=16, phi_resolution=16).save(str(folder / "geometry" / "ball.stl"))
    project = Project.new("y")
    project.add_part(Part(name="Ball", source_file="geometry/ball.stl", units="m"))
    project.save(folder / "p.json")
    return project


def test_mesh_properties_show_the_computed_first_layer_thickness(qtbot: QtBot, tmp_path) -> None:
    from vortexcfd.foam.yplus import first_layer_thickness
    from vortexcfd.gui.scene import domain_box_for

    project = _project_with_sphere(tmp_path)
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    try:
        w.tree.setCurrentItem(w._items[("mesh", None)])
        p = w.properties
        assert p.mesh_first_layer.text() == "relative sizing"
        project.update_mesh(layer_sizing="absolute_yplus", target_yplus=30.0)
        length = domain_box_for(project).reference_length
        h = first_layer_thickness(30.0, 20.0, 1.5e-5, length)
        assert p.mesh_first_layer.text() == f"{h:.4g} m (for y+ 30)"
        project.update_inflow(speed=40.0)  # the computed value follows the flow
        assert p.mesh_first_layer.text() == f"{first_layer_thickness(30.0, 40.0, 1.5e-5, length):.4g} m (for y+ 30)"
    finally:
        w.project.save = lambda *a, **k: None
        w.close()


def test_absolute_layers_make_the_mesh_depend_on_the_flow(tmp_path) -> None:
    from vortexcfd.gui.meshing import inputs_hash

    project = _project_with_sphere(tmp_path)
    base = inputs_hash(project)
    project.update_inflow(speed=40.0)
    assert inputs_hash(project) == base  # relative layers do not depend on the flow
    project.update_mesh(layer_sizing="absolute_yplus")
    with_40 = inputs_hash(project)
    project.update_inflow(speed=20.0)
    assert inputs_hash(project) != with_40  # absolute layers do
    project.update_physics(nu=2e-5)
    assert inputs_hash(project) not in (with_40,)


def test_layer_count_rows_and_the_y_plus_warning(qtbot: QtBot, tmp_path) -> None:
    from vortexcfd.foam.yplus import WARNING_HINT, first_layer_thickness, plan_layers
    from vortexcfd.gui.scene import domain_box_for
    from vortexcfd.foam.mesh_estimate import estimate_mesh

    project = _project_with_sphere(tmp_path)
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    try:
        w.tree.setCurrentItem(w._items[("mesh", None)])
        p = w.properties
        assert p.mesh_layer_count.text() == "3 (set)" and p.mesh_layer_stack.text() == "—"  # relative
        box = domain_box_for(project)
        surface = estimate_mesh(box.bounds, box.reference_length, project.sim.mesh).surface_size
        project.update_mesh(layer_sizing="absolute_yplus", target_yplus=30.0)
        plan = plan_layers(first_layer_thickness(30.0, 20.0, 1.5e-5, box.reference_length),
                           project.sim.mesh.expansion_ratio, surface)
        assert plan.warning is None
        assert p.mesh_layer_count.text() == str(plan.count)
        assert p.mesh_layer_stack.text() == f"{plan.total:.4g} m / {plan.final:.4g} m"
        assert p.mesh_layer_count.property("warn") == "false"
        assert WARNING_HINT not in w.top_bar.mesh_button.toolTip() and w.top_bar.mesh_button.isEnabled()
        project.update_mesh(target_yplus=1.0)  # y+ 1 on this surface mesh: the stack cannot reach 0.5 h
        assert p.mesh_layer_count.text() == "30 (limit 30)"
        assert p.mesh_layer_count.property("warn") == "true" and p.mesh_layer_stack.property("warn") == "true"
        assert WARNING_HINT in p.mesh_layer_count.toolTip()
        tip = w.top_bar.mesh_button.toolTip()
        assert w.top_bar.mesh_button.isEnabled() and "Warning" in tip and WARNING_HINT in tip
        project.update_mesh(layer_sizing="relative")
        assert "Warning" not in w.top_bar.mesh_button.toolTip()
    finally:
        w.project.save = lambda *a, **k: None
        w.close()
