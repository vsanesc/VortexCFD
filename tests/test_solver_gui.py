"""Run Solver from the GUI: disabled reasons, Stop, signals, end states, run record and staleness.

The solver process is a FakeRunner (tests/fake_solver.py); the mesh is a fake meshed case
(marker, empty constant/polyMesh and a mesh record with the project's inputs hash).
"""

from pathlib import Path

import pytest
import pyvista as pv
from PySide6.QtCore import QThread
from pytestqt.qtbot import QtBot

from tests.fake_solver import CRASH_BLOCK, FakeRunner, iteration
from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.mesh_case import MARKER_NAME, MARKER_TEXT
from vortexcfd.foam.mesh_record import MeshRecord, write_mesh_record
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.foam.run_record import read_run_record
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.workflow import solving
from vortexcfd.gui.main_window import MainWindow
from vortexcfd.workflow.meshing import inputs_hash

REPORT = MeshReport(points=10, faces=40, cells=1234, max_non_orthogonality=30.5, avg_non_orthogonality=10.0,
                    max_skewness=0.5, failed_checks=0, mesh_ok=True)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def fake_mesh(project: Project) -> Path:
    """A meshed case for ``project`` as Generate Mesh would leave it (without running OpenFOAM)."""
    case = project.path.parent / "case"
    (case / "constant" / "polyMesh").mkdir(parents=True, exist_ok=True)
    (case / MARKER_NAME).write_text(MARKER_TEXT)
    (case / "constant" / "polyMesh" / "points").write_text("mesh stays\n")
    write_mesh_record(case, MeshRecord(REPORT, inputs_hash(project), ("Ball",)))
    return case


@pytest.fixture
def make_window(qtbot: QtBot, tmp_path: Path):
    made: list[MainWindow] = []

    def make(save=True, mesh=True, surface=None) -> MainWindow:
        folder = tmp_path / f"proj{len(made)}"
        (folder / "geometry").mkdir(parents=True, exist_ok=True)
        project = Project.new("s")
        surface = surface if surface is not None else pv.Sphere(radius=0.5, theta_resolution=12, phi_resolution=12)
        surface.save(str(folder / "geometry" / "ball.stl"))
        project.add_part(Part(name="Ball", source_file="geometry/ball.stl", units="m"))
        if save:
            project.save(folder / "p.json")
            if mesh:
                fake_mesh(project)
        w = MainWindow(project, FakeDialogs(), with_viewer=False)
        qtbot.addWidget(w)
        w.show()
        made.append(w)
        return w

    yield make
    for runner in FakeRunner.instances:
        runner.release()
    for w in made:
        if w.solver_worker.is_running():
            w.solver_worker.request_stop()
            qtbot.waitUntil(lambda w=w: not w.solver_worker.is_running(), timeout=10000)
        assert not w.project.observer_errors
        w.project.save = lambda *a, **k: None
        w.close()


def use_runner(w: MainWindow, runner: FakeRunner) -> FakeRunner:
    FakeRunner.instances.append(runner)
    w.solver_worker.runner_factory = lambda: runner
    return runner


def wait_done(qtbot: QtBot, w: MainWindow) -> None:
    qtbot.waitUntil(lambda: w.run_record is not None and not w.solver_worker.is_running(), timeout=30000)


# -- disabled reasons ---------------------------------------------------------------------------------


def test_run_is_enabled_when_meshed_and_physics_valid(make_window) -> None:
    w = make_window()
    b = w.top_bar.run_button
    assert w.solve_readiness() is None
    assert b.isEnabled() and b.text() == "Run Solver" and "simpleFoam" in b.toolTip()


def test_every_disabled_reason_is_the_tooltip(make_window, qtbot: QtBot) -> None:
    b = make_window(save=False).top_bar.run_button
    assert not b.isEnabled() and b.toolTip() == "Save the project first."
    b = make_window(mesh=False).top_bar.run_button
    assert not b.isEnabled() and b.toolTip() == "Generate the mesh first."
    w = make_window()
    w.project.update_domain(upstream=3.0)  # the mesh no longer matches the inputs
    assert w.mesh_stale and not w.top_bar.run_button.isEnabled()
    assert w.top_bar.run_button.toolTip() == "The mesh is out of date: generate it again."
    w.act_undo.trigger()
    assert w.top_bar.run_button.isEnabled()
    # Meshing running: the meshing worker is busy
    w.mesh_worker.is_running = lambda: True
    w._update_run_button()
    assert not w.top_bar.run_button.isEnabled() and w.top_bar.run_button.toolTip() == "Meshing is running."
    del w.mesh_worker.is_running
    # Physics invalid: a flat part (no extent along y) gives a zero reference area
    flat = make_window(surface=pv.Plane(i_size=1.0, j_size=1.0, direction=(0, 1, 0)).triangulate())
    assert not flat.top_bar.run_button.isEnabled()
    assert flat.top_bar.run_button.toolTip().startswith("The reference area is zero")


def test_invalid_model_values_are_a_physics_problem(make_window, monkeypatch) -> None:
    w = make_window()
    sim = w.project.sim
    sim.inflow.speed = -5.0  # bypasses validation (no Project API path can do this)
    monkeypatch.setattr(type(w.project), "sim", property(lambda self: sim))
    reason = solving.physics_problem(w.project)
    assert reason.startswith("Invalid physics: inflow.speed")


# -- running -----------------------------------------------------------------------------------------------


def test_run_streams_through_signals_and_converges(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = w.project.path.parent / "case"
    (case / "400").mkdir()  # results of an earlier run are cleared
    (case / "postProcessing" / "forceCoeffs1").mkdir(parents=True)
    runner = use_runner(w, FakeRunner(iteration(1) + iteration(2), hold=True))
    threads: list = []
    w.solver_worker.line.connect(lambda _l: threads.append(QThread.currentThread()))
    w.top_bar.run_button.click()
    # the step signal of iteration 2 follows its ExecutionTime line: wait for both (a race under load)
    qtbot.waitUntil(lambda: "Time = 2" in w.console.text() and len(w.monitors.history.series.get("p", [])) == 2,
                    timeout=20000)
    # while running: Stop, Solving badge, mesh button blocked
    assert w.top_bar.run_button.text() == "Stop" and w.top_bar.run_button.isEnabled()
    assert w.top_bar.state_badge.text() == "Solving"
    assert not w.top_bar.mesh_button.isEnabled() and "solver is running" in w.top_bar.mesh_button.toolTip()
    # the solver files were written next to the untouched mesh, with clean stop enabled
    assert runner.clean_stop is True and runner.case_dir == case
    control = read_foam_file(case / "system" / "controlDict")
    assert control["application"] == "simpleFoam" and control["OptimisationSwitches"]["stopAtWriteNowSignal"] == 10
    assert (case / "0" / "U").is_file() and (case / "constant" / "turbulenceProperties").is_file()
    assert (case / "constant" / "polyMesh" / "points").read_text() == "mesh stays\n"
    assert not (case / "400").exists() and not (case / "postProcessing").exists()
    assert [t for t, _ in w.monitors.history.series["p"]] == [1.0, 2.0]  # steps reached the chart
    runner.release(iteration(3) + ["\n", "SIMPLE solution converged in 3 iterations\n", "End\n"])
    wait_done(qtbot, w)
    assert all(t is w.thread() for t in threads)  # slots ran in the GUI thread
    record = w.run_record
    assert record.state == "criteria_met" and record.iterations == 3
    assert record.final_residuals["p"] == pytest.approx(0.1)
    assert w.top_bar.run_button.text() == "Run Solver" and w.top_bar.run_button.isEnabled()
    assert w.top_bar.state_badge.text() in ("Saved", "Modified")
    assert w.top_bar.mesh_button.isEnabled()
    assert "Criteria met after 3 iterations" in w.statusBar().currentMessage()
    saved = read_run_record(case)
    assert saved == record and saved.inputs_hash == solving.results_hash(w.project)


def test_stop_button_stops_the_run(make_window, qtbot: QtBot) -> None:
    w = make_window()
    runner = use_runner(w, FakeRunner(iteration(1), hold=True, stop_lines=iteration(2) + ["End\n"]))
    w.run_solver()
    qtbot.waitUntil(lambda: "Time = 1" in w.console.text(), timeout=5000)
    w.top_bar.run_button.click()  # "Stop"
    wait_done(qtbot, w)
    assert runner.stop_requested
    assert w.run_record.state == "stopped" and w.run_record.iterations == 2
    assert "Stopped after 2 iterations" in w.statusBar().currentMessage()


def test_iteration_limit_end_state(make_window, qtbot: QtBot) -> None:
    w = make_window()
    use_runner(w, FakeRunner(iteration(1) + iteration(2) + ["End\n"]))
    w.run_solver()
    wait_done(qtbot, w)
    assert w.run_record.state == "iteration_limit"
    w.tree.setCurrentItem(w._items[("solvers", None)])
    p = w.properties
    assert p._rows["run_state"].isVisible() and p.run_state.text() == "Iteration limit"
    assert p.run_iterations.text() == "2" and "p 0.1" in p.run_residuals.text()
    assert p.run_status.text() == "Up to date" and not p.run_empty.isVisible()


def test_crash_prints_the_block_in_the_error_colour(make_window, qtbot: QtBot) -> None:
    w = make_window()
    use_runner(w, FakeRunner(iteration(1) + ["Time = 2\n"] + CRASH_BLOCK, exit_code=-8))
    w.run_solver()
    wait_done(qtbot, w)
    assert w.run_record.state == "crashed" and w.run_record.exit_code == -8
    html = w.console.view.document().toHtml()
    error = w._theme.error.lower()
    assert "sigFpe::sigHandler" in w.console.text()
    tail = html[html.rfind("[stack trace]") - 200:]
    assert error in tail.lower()  # the crash block is in the error colour
    assert "Crashed" in w.statusBar().currentMessage()


# -- record, reload and staleness --------------------------------------------------------------------------


def test_results_go_out_of_date_and_the_record_reloads(make_window, qtbot: QtBot) -> None:
    w = make_window()
    use_runner(w, FakeRunner(iteration(1) + ["End\n"]))
    w.run_solver()
    wait_done(qtbot, w)
    assert not w.results_stale and w.top_bar.results_badge.isHidden()
    w.project.update_inflow(speed=35.0)
    assert w.results_stale and not w.top_bar.results_badge.isHidden()
    assert w.top_bar.results_badge.text() == "Results out of date"
    w.tree.setCurrentItem(w._items[("solvers", None)])
    assert w.properties.run_status.text() == "Results out of date"
    w.act_undo.trigger()
    assert not w.results_stale and w.top_bar.results_badge.isHidden()
    w.project.update_solver(iterations=50)  # solver settings are results inputs too
    assert w.results_stale
    w.project.save()
    # reload: a new window on the same project file shows the saved run, still out of date
    w2 = MainWindow(Project.open(w.project.path), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w2)
    try:
        assert w2.run_record == w.run_record and w2.results_stale
        assert not w2.top_bar.results_badge.isHidden()
        w2.project.update_solver(iterations=1000)
        assert not w2.results_stale
    finally:
        w2.project.save = lambda *a, **k: None
        w2.close()


def test_no_run_record_shows_the_empty_state(make_window) -> None:
    w = make_window()
    w.tree.setCurrentItem(w._items[("solvers", None)])
    p = w.properties
    assert w.run_record is None and p.run_empty.isVisible() and not p._rows["run_state"].isVisible()
    assert w.top_bar.results_badge.isHidden()


def test_results_hash_tracks_the_inputs(make_window) -> None:
    w = make_window()
    base = solving.results_hash(w.project)
    w.project.update_physics(rho_ref=1.0)
    assert solving.results_hash(w.project) != base
    w.act_undo.trigger()
    assert solving.results_hash(w.project) == base
    w.project.rename("other name")  # not an input
    assert solving.results_hash(w.project) == base
