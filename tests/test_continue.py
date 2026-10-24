"""Continue the solver instead of restarting it (D-171), with fake runners: stop and continue (the iterations, the
residual and report histories and the criteria windows go on; the record keeps each segment), the iteration limit
reached, a changed set-up (continue from the current solution or start over), a changed mesh (Clear solution), the
two-stage run resumed in its stage, and a parallel case keeping its decomposition."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner, iteration
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from tests.test_two_stage import _case, _cd
from vortexcfd.core.model import AsymptoticCriterion, ResidualCriterion, StoppingCriteria
from vortexcfd.foam.dictfile import read_foam_file, write_foam_file
from vortexcfd.foam.logparse import parse_log_text
from vortexcfd.foam.run_record import read_run_record
from vortexcfd.foam.solver_run import STAGE2_SCHEME, STOPPED, ContinueFrom, SolverRun, stage2_criteria
from vortexcfd.gui.main_window import MESH_CHANGED_TEXT, SETTINGS_CHANGED_TEXT
from vortexcfd.workflow import solving

FIELD = """FoamFile
{{
    version     2.0;
    format      ascii;
    class       {cls};
    object      {name};
}}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform {value};
boundaryField
{{
    inlet
    {{
        type            fixedValue;
        value           uniform {value};
    }}
}}
"""


def _write_time(case: Path, it: int, speed: float = 20.0) -> None:
    """A written time as simpleFoam leaves it (the fields the solver files have, with an old inlet value)."""
    folder = case / str(it)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "U").write_text(FIELD.format(cls="volVectorField", name="U", value=f"({speed} 0 0)"))
    for name in ("p", "k", "omega", "nut"):
        (folder / name).write_text(FIELD.format(cls="volScalarField", name=name, value="0"))


def _stopped_at(w, qtbot: QtBot, last: int = 4) -> Path:
    """A first run stopped by the user: iterations 1..last-1, then the clean stop writes ``last``."""
    case = w.project.path.parent / "case"
    lines = [line for n in range(1, last - 1) for line in iteration(n)]
    runner = use_runner(w, FakeRunner(lines, hold=True, stop_lines=iteration(last - 1) + iteration(last) + ["End\n"]))
    w.run_solver()
    qtbot.waitUntil(lambda: len(w.monitors.history.series.get("p", [])) == last - 2, timeout=20000)
    w.run_solver()  # Stop
    wait_done(qtbot, w)
    assert runner.stop_requested and w.run_record.state == STOPPED and w.run_record.iterations == last
    _write_time(case, last)
    w._update_run_button()
    return case


def test_stop_and_continue_goes_on_from_the_latest_time(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = _stopped_at(w, qtbot, 4)
    assert w.solver_mode() == "continue"
    button = w.top_bar.run_button
    assert button.text() == "Continue Solver" and button.isEnabled()
    assert button.toolTip().startswith("Continue the solution from iteration 4 (its latest written time)")
    first = read_run_record(case)
    assert first.segments == ({"first": 1, "last": 4, "state": "stopped", "cores": 1,
                               "duration_s": first.segments[0]["duration_s"]},)
    runner = use_runner(w, FakeRunner(iteration(5) + iteration(6) + ["End\n"]))
    w.run_solver()  # Continue
    wait_done(qtbot, w)
    assert w.dialogs.choices_asked == []  # nothing changed: no question
    assert runner.append  # the log goes on
    control = read_foam_file(case / "system" / "controlDict")
    assert control["startFrom"] == "latestTime" and control["endTime"] == w.project.sim.solvers.iterations
    assert (case / "4" / "U").is_file()  # the solution was not cleared
    steps = [s.time for s in parse_log_text((case / "log.simpleFoam").read_text()).time_steps]
    assert steps == [1, 2, 3, 4, 5, 6]  # one continuous log
    assert [x for x, _v in w.monitors.history.series["p"]] == [1, 2, 3, 4, 5, 6]  # the residual history goes on
    record = w.run_record
    assert record.state == "iteration_limit" and record.iterations == 6
    assert [(s["first"], s["last"], s["state"]) for s in record.segments] == [(1, 4, "stopped"),
                                                                             (5, 6, "iteration_limit")]
    assert record.segments[1]["continued_from"] == 4 and record.segments[1]["settings_changed"] is False
    assert record.settings_hash == solving.solution_hash(w.project) and read_run_record(case) == record
    assert w.top_bar.run_button.text() == "Continue Solver"  # at the limit: it can go on (asking how far)
    w.tree.setCurrentItem(w._items[("solvers", None)])
    assert w.properties.run_iterations.text() == "6 in 2 runs: 1-4 (Stopped), 5-6 (Iteration limit)"


def test_the_criteria_windows_reach_back_into_the_earlier_iterations(tmp_path: Path) -> None:
    """An asymptotic criterion with a window of 4 met at iteration 5, the first iteration of the continued run: its
    window holds iterations 2 to 5 (the earlier log and postProcessing files)."""
    case = _case(tmp_path / "case", end_time=50, two_stage=False)
    _cd(case, 0, {1: 0.5, 2: 0.3, 3: 0.3001, 4: 0.3})
    _cd(case, 4, {5: 0.3001, 6: 0.3})  # the continued run writes its own start-time directory
    earlier = tuple(parse_log_text("".join(line for n in range(1, 5) for line in iteration(n))).time_steps)
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=4, tolerance=1e-2)])
    runner = FakeRunner(iteration(5) + iteration(6) + ["Time = 7\n"], hold=True, stop_lines=iteration(7) + ["End\n"])
    run = SolverRun(case, runner_factory=lambda: runner, stopping=stop, resume=ContinueFrom(4, earlier))
    run.start()
    result = run.wait(10)
    assert runner.stop_requested and result.state == "criteria_met" and result.met_iteration == 5


def test_at_the_limit_continue_asks_how_many_more(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = w.project.path.parent / "case"
    w.project.update_solver(iterations=3)
    use_runner(w, FakeRunner(iteration(1) + iteration(2) + iteration(3) + ["End\n"]))
    w.run_solver()
    wait_done(qtbot, w)
    _write_time(case, 3)
    w._update_run_button()
    assert w.run_record.state == "iteration_limit" and w.top_bar.run_button.text() == "Continue Solver"
    assert "reached the iteration limit (3)" in w.top_bar.run_button.toolTip()
    w.dialogs.more_iterations = None  # cancelled: nothing happens
    w.run_solver()
    assert w.dialogs.more_iterations_asked == [(3, 3)] and not w.solver_worker.is_running()
    w.dialogs.more_iterations = 2
    use_runner(w, FakeRunner(iteration(4) + iteration(5) + ["End\n"]))
    w.run_solver()
    wait_done(qtbot, w)
    assert w.project.sim.solvers.iterations == 5  # the limit is the total
    assert read_foam_file(case / "system" / "controlDict")["endTime"] == 5
    assert w.dialogs.choices_asked == []  # a longer run is not a changed set-up
    assert [(s["first"], s["last"]) for s in w.run_record.segments] == [(1, 3), (4, 5)]


def test_a_changed_set_up_continues_from_the_current_solution(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = _stopped_at(w, qtbot)
    w.project.update_inflow(turbulence_intensity=0.02)  # a free-stream change: not the mesh
    assert not w.mesh_stale
    w.dialogs.choices = [None]  # cancelled: nothing happens
    w.run_solver()
    assert w.dialogs.choices_asked[-1] == ("Continue solver", SETTINGS_CHANGED_TEXT, ["continue", "start_over"])
    assert not w.solver_worker.is_running()
    w.dialogs.choices = ["continue"]
    runner = use_runner(w, FakeRunner(iteration(5) + ["End\n"]))
    w.run_solver()
    wait_done(qtbot, w)
    assert runner.append and (case / "4" / "U").is_file()
    # the latest time's fields got the new boundary conditions, the solution kept [NUMERICS-REVIEW]
    k = read_foam_file(case / "4" / "k")
    assert k["internalField"] == 0 and k["boundaryField"] == read_foam_file(case / "0" / "k")["boundaryField"]
    assert w.run_record.segments[-1]["settings_changed"] is True
    assert not w.results_stale


def test_a_changed_set_up_can_start_over(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = _stopped_at(w, qtbot)
    w.project.update_inflow(viscosity_ratio=5.0)  # not a mesh input (nu would be: the y+ layers)
    assert not w.mesh_stale
    w.dialogs.choices = ["start_over"]
    runner = use_runner(w, FakeRunner(iteration(1) + ["End\n"]))
    w.run_solver()
    wait_done(qtbot, w)
    assert not runner.append and not (case / "4").exists()  # cleared, from the start
    assert read_foam_file(case / "system" / "controlDict")["startFrom"] == "startTime"
    assert len(w.run_record.segments) == 1 and w.run_record.iterations == 1


def test_a_changed_mesh_cannot_continue_and_offers_clear_solution(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = _stopped_at(w, qtbot)
    w.project.update_mesh(background_cells_target=200_000)
    assert w.mesh_stale
    button = w.top_bar.run_button
    assert button.text() == "Continue Solver" and button.isEnabled() and button.toolTip() == MESH_CHANGED_TEXT
    w.dialogs.choices = [None]
    w.run_solver()
    assert w.dialogs.choices_asked[-1] == ("Continue solver", MESH_CHANGED_TEXT, ["clear"])
    assert (case / "4").is_dir()  # cancelled: kept
    w.dialogs.choices = ["clear"]
    w.run_solver()
    assert not (case / "4").exists() and not (case / "log.simpleFoam").exists() and w.run_record is None
    assert (case / "constant" / "polyMesh").is_dir()  # the mesh stays
    assert button.text() == "Run Solver" and not button.isEnabled()  # generate the mesh again first


def test_a_two_stage_run_resumes_in_its_stage(tmp_path: Path) -> None:
    case = _case(tmp_path / "case", end_time=100)
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1e-9)])
    stage1 = {"stage": 1, "k_omega": "first order (bounded Gauss upwind)", "first": 1, "last": 50,
              "switch": "half the iteration limit", "condition_met_at": 50}
    resume = ContinueFrom(60, (), stage=2, switch_iteration=50, stage1=stage1)
    runner = FakeRunner(iteration(61) + iteration(62) + ["End\n"])
    run = SolverRun(case, runner_factory=lambda: runner, stopping=stop, resume=resume)
    assert run._stage == 2 and run._stopping == stage2_criteria(stop, 50)  # no switch again: stage 2 goes on
    run.start()
    result = run.wait(10)
    assert result.iterations == 62 and result.switch_iteration == 50
    assert result.stages[0] == {**stage1, "last": 50}
    assert result.stages[1] == {"stage": 2, "k_omega": STAGE2_SCHEME, "first": 51, "last": 62}
    assert runner.append and runner.command == ["simpleFoam"]
    # stopped in stage 1: it resumes in stage 1 (the switch is still ahead)
    runner = FakeRunner(iteration(21) + ["End\n"])
    run = SolverRun(case, runner_factory=lambda: runner, stopping=stop, resume=ContinueFrom(20, ()))
    assert run._stage == 1


def _queue(*runners: FakeRunner):
    queue = list(runners)
    return lambda: queue.pop(0)


def test_a_parallel_case_keeps_its_decomposition_on_the_same_cores(tmp_path: Path) -> None:
    case = _case(tmp_path / "case", two_stage=False)
    solver, reconstruct = FakeRunner(iteration(31) + ["End\n"]), FakeRunner([])
    run = SolverRun(case, runner_factory=_queue(solver, reconstruct), cores=2,
                    resume=ContinueFrom(30, (), reuse_decomposition=True))
    lines = []
    run._on_line = lines.append
    run.start()
    result = run.wait(10)
    assert solver.command[:3] == ["mpirun", "-np", "2"] and reconstruct.command == ["reconstructPar", "-latestTime"]
    assert result.decomposition is None and "Continuing on the existing decomposition (2 subdomains)\n" in lines
    # other cores: the latest time decomposed again
    decompose, solver, reconstruct = FakeRunner([]), FakeRunner(iteration(31) + ["End\n"]), FakeRunner([])
    run = SolverRun(case, runner_factory=_queue(decompose, solver, reconstruct), cores=3, resume=ContinueFrom(30, ()))
    run.start()
    run.wait(10)
    assert decompose.command == ["decomposePar", "-force", "-latestTime"] and solver.command[:3] == ["mpirun", "-np",
                                                                                                    "3"]
    # the latest time only in the processor directories: reconstructed first (serial continue)
    first, solver = FakeRunner([]), FakeRunner(iteration(31) + ["End\n"])
    run = SolverRun(case, runner_factory=_queue(first, solver), cores=1,
                    resume=ContinueFrom(30, (), reconstruct_first=True))
    run.start()
    run.wait(10)
    assert first.command == ["reconstructPar", "-latestTime"] and solver.command == ["simpleFoam"]


def test_prepare_continue_reads_the_case(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = _stopped_at(w, qtbot)
    w.project.update_solver(cores=2)
    for rank in (0, 1):
        _write_time(case / f"processor{rank}", 4)
    _case_dir, resume = solving.prepare_continue(w.project, w.run_record)
    assert resume.iteration == 4 and resume.reuse_decomposition and not resume.reconstruct_first
    assert [s.time for s in resume.history] == [1, 2, 3, 4]
    w.project.update_solver(cores=3)
    _case_dir, resume = solving.prepare_continue(w.project, w.run_record)
    assert not resume.reuse_decomposition  # 2 processor directories for 3 cores: decomposed again
    import shutil

    shutil.rmtree(case / "4")  # only in the processor directories
    _case_dir, resume = solving.prepare_continue(w.project, w.run_record)
    assert resume.reconstruct_first
    with pytest.raises(solving.SolvingNotReady, match="only in the processor directories"):
        solving.prepare_continue(w.project, w.run_record, rewrite=True)
