"""Mesh Study and Polar Sweep nodes (D-066, D-067): settings commit through the Project, the level
estimate, Run / Stop with fake runners, the busy rules, the results windows and CSV export."""

from pathlib import Path

import pytest

from tests.test_mesh_study import FakeMeshRun, FakeSolverRun
from tests.test_polar_sweep import FakeSolver
from tests.test_solver_gui import make_window  # noqa: F401 (fixture)
from vortexcfd.foam.solver_run import CRITERIA_MET, ITERATION_LIMIT


def _select(w, kind: str) -> None:
    w.tree.setCurrentItem(w._items[(kind, None)])


def test_study_nodes_exist_and_commit_settings(make_window) -> None:
    w = make_window()
    _select(w, "mesh_study")
    p = w.properties
    assert not p._rows["ms_ratio"].isHidden() and p._rows["ps_mode"].isHidden()
    p.ms_ratio.setValue(1.5)
    p.ms_ratio.editingFinished.emit()
    assert w.project.sim.studies.mesh.ratio == 1.5
    p.ms_current.setCurrentText("medium")
    assert w.project.sim.studies.mesh.current_as == "medium"
    w.project.undo()
    assert w.project.sim.studies.mesh.current_as == "fine"
    actions = {a.text(): a for a in p.ms_menu.actions()}
    actions["Cl"].setChecked(True)
    assert w.project.sim.studies.mesh.quantities == ["Cd", "Cl"]
    # three level estimates, the shared layer stack, Run enabled
    texts = [label.text() for label in p.ms_levels]
    assert all("cells" in t for t in texts)
    assert "same on every level" in p.ms_layers.text()
    assert p.ms_run.isEnabled() and p.ms_run.text() == "Run mesh study"
    _select(w, "polar_sweep")
    assert not p._rows["ps_start"].isHidden() and p._rows["ps_values"].isHidden()
    p.ps_mode.setCurrentText("list")
    assert p._rows["ps_values"].isVisibleTo(p) and p._rows["ps_start"].isHidden()
    p.ps_values.setText("0, 5 10")
    p.ps_values.editingFinished.emit()
    assert w.project.sim.studies.polar.values == [0.0, 5.0, 10.0]
    assert p.ps_alphas.text().startswith("3:")
    p.ps_values.setText("a b")
    p.ps_values.editingFinished.emit()
    assert w.project.sim.studies.polar.values == [0.0, 5.0, 10.0]


def test_studies_need_a_saved_project(make_window) -> None:
    w = make_window(save=False)
    _select(w, "mesh_study")
    assert not w.properties.ms_run.isEnabled() and w.properties.ms_run.toolTip() == "Save the project first."
    _select(w, "polar_sweep")
    assert w.properties.ps_run.toolTip() == "Save the project first."


def test_mesh_study_runs_through_the_window(make_window, qtbot) -> None:
    w = make_window()
    w.project.update_study("mesh", quantities=["Cd"])
    FakeMeshRun.calls, FakeSolverRun.n = [], 0
    w.study_mesh_run_factory, w.study_solver_run_factory = FakeMeshRun, FakeSolverRun
    _select(w, "mesh_study")
    w.properties.ms_run.click()
    qtbot.waitUntil(lambda: w.study_record is not None and w.study_record.status == "finished", timeout=10000)
    qtbot.waitUntil(lambda: not w.study_worker.is_running(), timeout=5000)
    study = w.project.path.parent / "case_study"
    for n in (1, 2, 3):
        assert (study / f"level_{n}" / "system" / "snappyHexMeshDict").is_file()
        assert (study / f"level_{n}" / "constant" / "triSurface" / "Ball.stl").is_file()
    assert (study / "study.json").is_file()
    w.properties.ms_results.click()
    win = w.study_window
    assert win.table.rowCount() == 1 and win.table.item(0, 0).text() == "Cd"
    assert win.levels.rowCount() == 3 and win.levels.item(2, 1).text() == "8,000"
    assert len(win.chart.series) == 1 and len(win.chart.markers[0]) == 3
    assert "actual h ratios 1.41 and 1.42" in win.status.text()  # from the fake cell counts 1000, 2800, 8000


def test_a_running_study_blocks_the_solver_and_meshing(make_window, qtbot) -> None:
    """While a level runs, Run Solver and Generate Mesh are disabled; Stop ends the study."""
    import threading

    gate = threading.Event()

    class HoldingMeshRun(FakeMeshRun):
        def wait(self, timeout=None):
            gate.wait(10)
            return super().wait(timeout)

    w = make_window()
    FakeMeshRun.calls, FakeSolverRun.n = [], 0
    w.study_mesh_run_factory, w.study_solver_run_factory = HoldingMeshRun, FakeSolverRun
    _select(w, "mesh_study")
    w.properties.ms_run.click()
    qtbot.waitUntil(lambda: len(FakeMeshRun.calls) == 1, timeout=5000)
    assert w.solve_readiness() == "A mesh study is running: stop it first."
    assert w.properties.ms_run.text() == "Stop"
    w.properties.ms_run.click()  # Stop
    gate.set()
    qtbot.waitUntil(lambda: not w.study_worker.is_running(), timeout=10000)
    assert w.study_record.status == "stopped"
    assert w.solve_readiness() is None


def test_polar_sweep_runs_through_the_window(make_window, qtbot, tmp_path: Path) -> None:
    w = make_window()
    w.project.update_study("polar", mode="list", values=[0.0, 5.0, 10.0], cores=1)
    FakeSolver.states, FakeSolver.alphas, FakeSolver.created, FakeSolver.hold_index = (
        [CRITERIA_MET, ITERATION_LIMIT, CRITERIA_MET], [0.0, 5.0, 10.0], [], None)
    w.study_solver_run_factory = FakeSolver
    _select(w, "polar_sweep")
    w.properties.ps_run.click()
    qtbot.waitUntil(lambda: w.sweep_record is not None and w.sweep_record.status == "finished", timeout=10000)
    qtbot.waitUntil(lambda: not w.sweep_worker.is_running(), timeout=5000)
    sweep = w.project.path.parent / "case_sweep"
    assert (sweep / "sweep.json").is_file() and (sweep / "mesh" / "polyMesh" / "points").is_file()
    assert not (w.project.path.parent / "case" / "0").exists()  # case/ untouched
    assert "1 without meeting the stopping criteria" in w.properties.ps_status.text()
    assert w.properties.ps_results.isEnabled()
    w.properties.ps_results.click()
    win = w.sweep_window
    assert win.table.rowCount() == 3 and win.table.item(1, 6).text() == "Iteration limit"
    assert win.cl_alpha.markers[0][1] == (5.0, pytest.approx(0.5), True)  # hollow
    w.dialogs.csv_path = tmp_path / "polar.csv"
    win.export.click()
    assert (tmp_path / "polar.csv").read_text().startswith("alpha_deg,CL,CD")


def test_a_running_sweep_blocks_the_solver_and_the_mesh_study(make_window, qtbot) -> None:
    w = make_window()
    w.project.update_study("polar", mode="list", values=[0.0, 5.0], cores=1)
    FakeSolver.states, FakeSolver.alphas, FakeSolver.created, FakeSolver.hold_index = (
        [CRITERIA_MET, CRITERIA_MET], [0.0, 5.0], [], 0)
    w.study_solver_run_factory = FakeSolver
    _select(w, "polar_sweep")
    w.properties.ps_run.click()
    qtbot.waitUntil(lambda: len(FakeSolver.created) == 1, timeout=5000)
    assert w.solve_readiness() == "A polar sweep is running: stop it first."
    assert w.properties.ps_run.text() == "Stop"
    _select(w, "mesh_study")
    assert w.properties.ms_run.toolTip() == "A polar sweep is running: stop it first."
    _select(w, "polar_sweep")
    w.properties.ps_run.click()  # Stop
    qtbot.waitUntil(lambda: not w.sweep_worker.is_running(), timeout=10000)
    assert w.sweep_record.status == "stopped"
    assert w.solve_readiness() is None
