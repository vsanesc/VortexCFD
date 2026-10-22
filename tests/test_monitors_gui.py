"""Live residual chart, report slots and the Reference Values node (fake solver runner)."""

import shutil
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner, iteration
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from vortexcfd.core.model import Reports
from vortexcfd.core.project import Project
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.logparse import TimeStep
from vortexcfd.workflow import solving
from vortexcfd.gui.monitors import ResidualChart, nice_ticks
from vortexcfd.gui.properties_panel import REFERENCE_NOTE, parse_vector
from vortexcfd.gui.theme import DARK, RESIDUAL_STYLES, residual_style

RUN = Path(__file__).parent / "data" / "sphere_run"


def _select(w, kind: str) -> None:
    w.tree.setCurrentItem(w._items[(kind, None)])


# -- palette ---------------------------------------------------------------------------------------------


def test_residual_palette_is_derived_from_owner_tokens() -> None:
    assert {f: residual_style(DARK, f) for f in RESIDUAL_STYLES} == {
        "p": ("#D87403", "SolidLine"),
        "Ux": ("#309DCF", "SolidLine"), "Uy": ("#309DCF", "DashLine"), "Uz": ("#309DCF", "DotLine"),
        "k": ("#28AC61", "SolidLine"), "omega": ("#28AC61", "DashLine"),
    }
    assert {RESIDUAL_STYLES[f][0] for f in RESIDUAL_STYLES} == {"accent", "axis_z", "axis_y"}
    assert residual_style(DARK, "epsilon") == (DARK.muted_text, "DashDotLine")


# -- chart ---------------------------------------------------------------------------------------------------


def test_chart_empty_state_and_live_series(make_window, qtbot: QtBot) -> None:
    w = make_window()
    chart = w.monitors.chart
    assert chart.series == {} and chart.axis_labels() == [f"1e{d}" for d in range(0, -7, -1)]
    runner = use_runner(w, FakeRunner(iteration(1, p=1.0) + iteration(2, p=0.5), hold=True))
    w.run_solver()
    qtbot.waitUntil(lambda: len(chart.series.get("p", [])) == 2, timeout=5000)
    assert list(chart.series) == ["Ux", "Uy", "Uz", "p", "omega", "k"]
    assert [name for name, _, _ in chart.legend_entries()] == list(chart.series)
    assert chart.legend_entries()[3] == ("p", "#D87403", "SolidLine")
    assert chart.x_range() == (1.0, 2.0)
    runner.release(iteration(3, p=2e-8) + ["End\n"])
    wait_done(qtbot, w)
    assert chart.series["p"][-1] == (3.0, 2e-8)
    assert chart.x_range() == (1.0, 3.0)  # the x axis follows the latest iteration
    assert chart.axis_labels()[-1] == "1e-8"  # the decades widen to fit the data
    w.grab()  # paints the series and the legend without errors


def test_chart_decimates_long_runs(qtbot: QtBot) -> None:
    from vortexcfd.gui.monitors import MonitorsPanel

    panel = MonitorsPanel()
    qtbot.addWidget(panel)
    panel.resize(400, 300)
    for i in range(1, 6001):
        panel.add_step(TimeStep(float(i), residuals=[("p", 1.0 / i, 0.0, 1), ("k", 0.5 / i, 0.0, 1)]))
    panel.refresh()
    assert all(len(s) <= 2000 for s in panel.chart.series.values())
    assert panel.chart.series["p"][-1] == (6000.0, 1.0 / 6000)
    assert len(panel.history.series["p"]) == 6000
    panel.grab()
    panel.clear()
    assert panel.chart.series == {} and panel.chart.axis_labels()[0] == "1e0"


def test_nice_ticks() -> None:
    assert nice_ticks(1, 20) == [5, 10, 15, 20]
    assert nice_ticks(1, 3) == [1, 1.5, 2, 2.5, 3]
    assert ResidualChart.EMPTY_MESSAGE == "No solver run yet"


# -- report slots -------------------------------------------------------------------------------------------


def test_slot_menu_assigns_and_the_assignment_is_saved(make_window, qtbot: QtBot) -> None:
    w = make_window()
    slots = w.monitors.kpis
    labels = [a.text() for a in slots.slot_actions(2)]
    assert labels == ["Not assigned", "Cd", "Cl", "Cm (pitch)", "Cd pressure", "Cd viscous", "Cl pressure",
                      "Cl viscous", "C_A (body axial)", "C_N (body normal)", "x_cp (m)", "Mass imbalance (%)", "y+ min (walls)", "y+ avg (walls)",
                      "y+ max (walls)"]
    assert [a.text() for a in slots.menus[2].actions()][:2] == ["Not assigned", "All walls"]  # submenu
    next(a for a in slots.slot_actions(2) if a.text() == "Cd").trigger()
    assert w.project.sim.reports.slots == [None, "Cd", None]
    assert slots.subtitles[2].text() == "Cd" and slots.values[2].text() == "—"  # no run yet
    assert w.project.undo_label == "Edit reports (slots)" and w.project.dirty
    assert not w.results_stale  # a slot choice does not change the results
    next(a for a in slots.slot_actions(3) if a.text() == "y+ avg (walls)").trigger()
    w.project.save()
    reopened = Project.open(w.project.path)
    assert reopened.sim.reports.slots == [None, "Cd", "yplus_avg"]
    w.act_undo.trigger()
    assert slots.subtitles[3].text() == "Not assigned"
    checked = [a.text() for a in slots.slot_actions(2) if a.isChecked()]
    assert checked == ["Cd"]
    next(a for a in slots.slot_actions(2) if a.text() == "Not assigned").trigger()
    assert w.project.sim.reports.slots == [None, None, None] and slots.subtitles[2].text() == "Not assigned"


def test_slot_values_update_live_from_the_postprocessing_files(make_window, qtbot: QtBot) -> None:
    w = make_window()
    w.project.update_reports(slots=["Cd", "Cl", "yplus_avg"])
    case = w.project.path.parent / "case"
    runner = use_runner(w, FakeRunner(iteration(1), hold=True))
    w.run_solver()
    qtbot.waitUntil(lambda: "Time = 1" in w.console.text(), timeout=5000)
    # simpleFoam writes the files while it runs: three rows, the last one half written
    rows = (RUN / "coefficient.dat").read_text().splitlines(keepends=True)
    header = [r for r in rows if r.startswith("#")]
    data = [r for r in rows if not r.startswith("#")]
    out = case / "postProcessing" / "forceCoeffs1" / "0"
    out.mkdir(parents=True)
    (out / "coefficient.dat").write_text("".join(header + data[:2]) + data[2][:20])
    slots = w.monitors.kpis
    qtbot.waitUntil(lambda: slots.values[1].text() == "1.405", timeout=5000)  # Cd of row 2
    assert slots.values[2].text() == "-0.04507" and slots.values[3].text() == "—"
    assert slots.sparks[1].values == pytest.approx([2.135677, 1.404513])
    with open(out / "coefficient.dat", "a") as fh:
        fh.write(data[2][20:])
    (case / "postProcessing" / "yPlus1" / "0").mkdir(parents=True)
    shutil.copy(RUN / "yPlus.dat", case / "postProcessing" / "yPlus1" / "0")
    qtbot.waitUntil(lambda: slots.values[3].text() == "172.2", timeout=5000)
    assert slots.values[1].text() == "1.018"
    runner.release(["End\n"])
    wait_done(qtbot, w)
    # reopen: the finished run's residuals and reports are shown again
    w.project.save()
    from tests.fakes import FakeDialogs
    from vortexcfd.gui.main_window import MainWindow

    w2 = MainWindow(Project.open(w.project.path), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w2)
    try:
        assert w2.monitors.kpis.values[1].text() == "1.018" and w2.monitors.kpis.values[3].text() == "172.2"
        assert list(w2.monitors.chart.series) == ["Ux", "Uy", "Uz", "p", "omega", "k"]
    finally:
        w2.project.save = lambda *a, **k: None
        w2.close()


# -- reference values -----------------------------------------------------------------------------------------


def test_reference_values_node_defaults_are_auto(make_window) -> None:
    w = make_window()
    item = w._items[("reference_values", None)]
    assert item.parent() is w._items[("reports", None)] and item.text(0) == "Reference Values"
    _select(w, "reference_values")
    p = w.properties
    assert all(p._rows[k].isVisible() for k in ("ref_rho", "ref_u", "ref_basis", "ref_area", "ref_length",
                                                "ref_cofr"))
    assert p.ref_rho.value() == pytest.approx(1.225)
    assert p.ref_u.text() == "20 m/s (inflow speed)"
    assert p.ref_basis.currentText() == "planform" and not p.ref_area.isEnabled()
    assert p.ref_area.text() == "auto" and p.ref_length.text() == "auto" and p.ref_cofr.text() == ""
    # the auto labels state the basis exactly
    assert p.ref_area_used.text().endswith("m\u00b2 \u2014 auto: bounding-box planform, x * y")
    assert p.ref_length_used.text().endswith("m \u2014 auto: bounding-box length, x extent")
    assert p.ref_cofr_used.text().endswith("\u2014 auto: bounding-box centre")
    assert p.ref_note.isVisible() and p.ref_note.text() == REFERENCE_NOTE and p.ref_note.objectName() == "muted"
    assert not p.info_label.isVisible()
    _select(w, "solvers")
    assert not p._rows["ref_area"].isVisible() and not p.ref_note.isVisible()


def test_area_basis_frontal_and_custom(make_window) -> None:
    from vortexcfd.foam.physics_case import bounding_box_area
    from vortexcfd.workflow.meshing import parts_layout

    w = make_window()
    _, _, bounds = parts_layout(w.project)
    planform, frontal = bounding_box_area(bounds, "planform"), bounding_box_area(bounds, "frontal")
    _select(w, "reference_values")
    p = w.properties
    p.ref_basis.setCurrentText("frontal")
    reports = w.project.sim.reports
    assert reports.reference_area_basis == "frontal" and reports.reference_area is None
    assert p.ref_area_used.text() == f"{frontal:.4g} m\u00b2 \u2014 auto: bounding-box frontal, y * z"
    case = solving.prepare_solver_case(w.project)
    fc = read_foam_file(case / "system" / "controlDict")["functions"]["forceCoeffs1"]
    assert fc["Aref"] == pytest.approx(frontal) and frontal != pytest.approx(planform, rel=1e-6)
    # custom starts from the area in use and makes the field editable
    p.ref_basis.setCurrentText("custom")
    assert w.project.sim.reports.reference_area == pytest.approx(frontal) and p.ref_area.isEnabled()
    p.ref_area.setValue(0.785)
    p.ref_area.editingFinished.emit()
    assert w.project.sim.reports == Reports(reference_area_basis="custom", reference_area=0.785)
    assert p.ref_area_used.text() == "0.785 m\u00b2 (set)"
    p.ref_area.setValue(p.ref_area.minimum())  # "auto" is not a custom area: rejected, reverted
    p.ref_area.editingFinished.emit()
    assert w.project.sim.reports.reference_area == 0.785 and "custom" in w.statusBar().currentMessage()
    p.ref_basis.setCurrentText("planform")
    assert w.project.sim.reports == Reports()
    w.act_undo.trigger()
    assert w.project.sim.reports.reference_area == 0.785 and p.ref_basis.currentText() == "custom"


def test_reference_overrides_are_stored_and_used_by_force_coeffs(make_window) -> None:
    w = make_window()
    _select(w, "reference_values")
    p = w.properties
    p.ref_basis.setCurrentText("custom")
    p.ref_area.setValue(0.785)
    p.ref_area.editingFinished.emit()
    p.ref_length.setValue(1.0)
    p.ref_length.editingFinished.emit()
    p.ref_cofr.setText("0.25, 0, 0")
    p.ref_cofr.editingFinished.emit()
    p.ref_rho.setValue(1.0)
    p.ref_rho.editingFinished.emit()
    sim = w.project.sim
    assert sim.reports == Reports(reference_area_basis="custom", reference_area=0.785, reference_length=1.0,
                                  center_of_rotation=(0.25, 0, 0))
    assert sim.physics.rho_ref == 1.0
    assert p.ref_area_used.text() == "0.785 m\u00b2 (set)" and p.ref_cofr_used.text() == "(0.25 0 0) m (set)"
    assert not p.ref_note.isVisible()  # both A_ref and l_ref are set
    assert w.results_stale is False  # no run yet
    case = solving.prepare_solver_case(w.project)
    functions = read_foam_file(case / "system" / "controlDict")["functions"]
    fc = functions["forceCoeffs1"]
    assert fc["Aref"] == 0.785 and fc["lRef"] == 1.0 and list(fc["CofR"]) == [0.25, 0, 0] and fc["rhoInf"] == 1.0
    assert list(functions["forces1"]["CofR"]) == [0.25, 0, 0]
    # invalid text reverts with a message; empty text goes back to auto
    p.ref_cofr.setText("1 2")
    p.ref_cofr.editingFinished.emit()
    assert w.project.sim.reports.center_of_rotation == (0.25, 0, 0) and p.ref_cofr.text() == "0.25 0 0"
    assert "three numbers" in w.statusBar().currentMessage()
    p.ref_cofr.setText("")
    p.ref_cofr.editingFinished.emit()
    p.ref_length.setValue(p.ref_length.minimum())
    p.ref_length.editingFinished.emit()
    assert w.project.sim.reports.center_of_rotation is None and w.project.sim.reports.reference_length is None
    assert p.ref_note.isVisible() and "auto: bounding-box length" in p.ref_length_used.text()


def test_reference_values_change_the_results_hash(make_window) -> None:
    w = make_window()
    base = solving.results_hash(w.project)
    w.project.update_reports(reference_area_basis="frontal")
    assert solving.results_hash(w.project) != base
    w.project.update_reports(reference_area_basis="planform", slots=["Cd", None, None])
    assert solving.results_hash(w.project) == base


def test_parse_vector() -> None:
    assert parse_vector("1 2 3") == (1.0, 2.0, 3.0)
    assert parse_vector("(0.5, -1; 2e-3)") == (0.5, -1.0, 0.002)
    assert parse_vector("") is None and parse_vector(" auto ") is None
    for bad in ("1 2", "a b c", "1 2 3 4"):
        with pytest.raises(ValueError):
            parse_vector(bad)


# -- end to end (real simpleFoam) ---------------------------------------------------------------------------


@pytest.mark.slow
def test_end_to_end_solver_run_on_the_shared_sphere_mesh(sphere_mesh, qtbot: QtBot, tmp_path: Path) -> None:
    """Run Solver from the window on a copy of the shared coarse sphere mesh, 60 iterations."""
    import pyvista as pv

    from tests.fakes import FakeDialogs
    from vortexcfd.core.model import Part
    from vortexcfd.foam.mesh_record import MeshRecord, write_mesh_record
    from vortexcfd.foam.run_record import read_run_record
    from vortexcfd.gui.main_window import MainWindow
    from vortexcfd.workflow.meshing import inputs_hash

    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24).save(str(folder / "geometry" / "sphere.stl"))
    project = Project.new("sphere")
    project.add_part(Part(name="Sphere", source_file="geometry/sphere.stl", units="m"))
    project.update_solver(iterations=60, write_interval=30)
    project.update_reports(slots=["Cd", "yplus_avg", "Cl"])
    project.save(folder / "p.json")
    case = folder / "case"
    shutil.copytree(sphere_mesh.case_dir, case)
    write_mesh_record(case, MeshRecord(sphere_mesh.result.report, inputs_hash(project), sphere_mesh.inputs.parts))
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.solver_timeout_s = 150
    lines: list[str] = []
    w.solver_worker.line.connect(lines.append)
    try:
        assert w.top_bar.run_button.isEnabled(), w.top_bar.run_button.toolTip()
        w.top_bar.run_button.click()
        assert w.top_bar.state_badge.text() == "Solving"
        qtbot.waitUntil(lambda: w.run_record is not None and not w.solver_worker.is_running(), timeout=170_000)
    finally:
        if w.solver_worker.is_running():
            w.solver_worker.request_stop()
            qtbot.waitUntil(lambda: not w.solver_worker.is_running(), timeout=30_000)
    record = w.run_record
    assert record.exit_code == 0, (case / "log.simpleFoam").read_text()[-1500:]
    assert record.state in ("criteria_met", "iteration_limit") and record.iterations == 60
    assert any(l.startswith("Time = 60") for l in lines) and any("Solving for p" in l for l in lines)
    assert len(w.monitors.history.series["p"]) == 60
    cd = w.monitors.reports.series("Cd")
    yplus = w.monitors.reports.series("yplus_avg")
    assert len(cd) == 60 and cd[-1][1] > 0
    assert [t for t, _ in yplus] == [30.0, 60.0]
    assert w.monitors.kpis.values[1].text() == f"{cd[-1][1]:.4g}"
    assert read_run_record(case) == record
    print(f"\nsphere run: state={record.state} iterations={record.iterations} "
          f"final residuals={record.final_residuals} Cd={cd[-1][1]:.4g} y+ avg={yplus[-1][1]:.4g}")
    w.project.save = lambda *a, **k: None
    w.close()
