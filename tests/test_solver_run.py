"""The solver run state machine (fake runner), the app-side stop, the run record and the Converged
log event."""

from pathlib import Path

import pytest

from tests.fake_solver import CRASH_BLOCK, FakeRunner, iteration
from vortexcfd.foam.logparse import Converged, parse_log_text
from vortexcfd.foam.run_record import RunRecord, read_run_record, remove_run_record, write_run_record
from vortexcfd.core.model import AsymptoticCriterion, ResidualCriterion, StoppingCriteria
from vortexcfd.foam.solver_run import (
    CRITERIA_MET,
    CRASHED,
    ITERATION_LIMIT,
    LOG_NAME,
    STOPPED,
    SolverRun,
    classify,
    final_residuals,
)

DATA = Path(__file__).parent / "data"


def _run(tmp_path: Path, runner: FakeRunner, stop: bool = False, stopping=None):
    lines, steps, done = [], [], []
    run = SolverRun(tmp_path, on_line=lines.append, on_step=steps.append, on_done=done.append,
                    runner_factory=lambda: runner, stopping=stopping)
    run.start()
    if stop:  # the fake plays its lines first, then honours the stop (also before it is registered)
        run.request_stop()
    result = run.wait(10)
    assert result is not None and not run.is_running()
    assert done == [result]
    return result, lines, steps


def test_converged_when_residual_control_is_reached(tmp_path: Path) -> None:
    lines = iteration(1) + iteration(2, p=1e-5) + ["\n", "SIMPLE solution converged in 2 iterations\n", "\n",
                                                  "End\n"]
    runner = FakeRunner(lines)
    result, got, steps = _run(tmp_path, runner)
    assert runner.command == ["simpleFoam"] and runner.clean_stop is True
    assert runner.log_file == tmp_path / LOG_NAME
    assert result.state == CRITERIA_MET and result.label == "Criteria met" and result.exit_code == 0
    assert result.iterations == 2 and [s.time for s in steps] == [1.0, 2.0]
    assert got == lines  # every line is forwarded, in order
    assert result.final_residuals == {"Ux": 0.01, "Uy": 0.02, "Uz": 0.03, "p": 1e-5, "omega": 0.002, "k": 0.001}
    assert result.crash is None


def test_iteration_limit_when_the_run_ends_without_converging(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, FakeRunner(iteration(1) + iteration(2) + iteration(3) + ["End\n"]))
    assert result.state == ITERATION_LIMIT and result.label == "Iteration limit" and result.iterations == 3


def test_stopped_on_request(tmp_path: Path) -> None:
    runner = FakeRunner(iteration(1), hold=True, stop_lines=iteration(2) + ["End\n"])
    result, _, steps = _run(tmp_path, runner, stop=True)
    assert runner.stop_requested
    assert result.state == STOPPED and result.label == "Stopped" and result.iterations == 2


def test_crashed_on_a_stack_trace_or_a_non_zero_exit(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, FakeRunner(iteration(1) + ["Time = 2\n"] + CRASH_BLOCK, exit_code=-8))
    assert result.state == CRASHED and result.label == "Crashed" and result.exit_code == -8
    assert result.crash is not None and result.crash.startswith("[stack trace]") and "sigFpe" in result.crash
    result, _, _ = _run(tmp_path, FakeRunner(iteration(1), exit_code=1))  # no block, failing exit code
    assert result.state == CRASHED and result.crash is None
    fatal = ["--> FOAM FATAL ERROR: (openfoam-2606)\n", "Cannot find patchField entry for Ball\n",
             "\n", "FOAM exiting\n"]
    result, _, _ = _run(tmp_path, FakeRunner(fatal, exit_code=1))
    assert result.state == CRASHED and "Cannot find patchField" in result.crash


def test_crashed_when_the_runner_cannot_start(tmp_path: Path) -> None:
    class Broken(FakeRunner):
        def start(self, *a, **k):
            raise ValueError("clean_stop=True requires OptimisationSwitches.stopAtWriteNowSignal")

    result, _, _ = _run(tmp_path, Broken([]))
    assert result.state == CRASHED and "stopAtWriteNowSignal" in result.crash and result.exit_code is None


def test_classify_priorities() -> None:
    crash = parse_log_text("".join(iteration(1) + CRASH_BLOCK))
    assert classify(-8, True, crash) == CRASHED  # a crash block wins over a stop
    ok = parse_log_text("".join(iteration(1) + ["End\n"]))
    assert classify(143, True, ok) == STOPPED  # SIGTERM escalation after a stop request
    assert classify(0, False, ok) == ITERATION_LIMIT
    assert classify(1, False, ok) == CRASHED


def test_converged_event_is_parsed() -> None:
    parser = parse_log_text("".join(iteration(1) + ["\n", "SIMPLE solution converged in 1 iterations\n"]))
    assert parser.converged == Converged("SIMPLE", 1.0)
    assert len(parser) == 1  # the pending step is flushed first


def test_real_pitzdaily_log_is_an_iteration_limit() -> None:
    parser = parse_log_text((DATA / "pitzDaily_simpleFoam.log").read_text())
    assert parser.converged is None and parser.has_ended
    assert classify(0, False, parser) == ITERATION_LIMIT
    res = final_residuals(parser)
    assert set(res) == {"Ux", "Uy", "p", "epsilon", "k"}
    last = parser[-1].residuals
    assert res["p"] == next(init for name, init, _, _ in last if name == "p")


def test_real_diverged_log_is_a_crash() -> None:
    parser = parse_log_text((DATA / "cavity_diverged_icoFoam.log").read_text())
    assert classify(-8, False, parser) == CRASHED


# -- app-side stop (D-058) ---------------------------------------------------------------------------


def _coefficients(case: Path, values: list[float]) -> None:
    """A coefficient.dat with one Cd row per iteration (format of the real files, other columns 0)."""
    folder = case / "postProcessing" / "forceCoeffs1" / "0"
    folder.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"{i}\t{v}\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\n" for i, v in enumerate(values, start=1))
    (folder / "coefficient.dat").write_text("# Time\tCd\tCd(f)\tCd(r)\tCl\tCl(f)\tCl(r)\tCmPitch\tCmRoll\tCmYaw\t"
                                            "Cs\tCs(f)\tCs(r)\n" + rows)


def test_asymptotic_criterion_stops_the_solver_cleanly(tmp_path: Path) -> None:
    """Cd settles: met at iteration 4 (window 3, the rows 2-4 are equal) once its row is in the file
    (the line after the iteration); the app requests the clean stop and the solver writes
    iteration 5."""
    _coefficients(tmp_path, [0.5, 0.3, 0.3, 0.3, 0.3])
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=3)])
    runner = FakeRunner(iteration(1) + iteration(2) + iteration(3) + iteration(4) + ["Time = 5\n"], hold=True,
                        stop_lines=iteration(5)[1:] + ["End\n"])
    result, _, _ = _run(tmp_path, runner, stopping=stop)
    assert runner.stop_requested and result.state == CRITERIA_MET and result.exit_code == 0
    assert result.criteria_met == ("c1_asymptotic_Cd",) and result.met_iteration == 4 and result.iterations == 5


def test_app_side_all_needs_every_criterion_and_any_one(tmp_path: Path) -> None:
    _coefficients(tmp_path, [0.3] * 5)
    criteria = [ResidualCriterion(field="p", threshold=1e-3), AsymptoticCriterion(quantity="Cd", window=2)]
    lines = iteration(1) + iteration(2) + iteration(3, p=1e-4) + iteration(4) + iteration(5) + ["End\n"]
    # "all": Cd settles from iteration 2 but p is below 1e-3 only at iteration 3
    runner = FakeRunner(lines, hold=False)
    result, _, _ = _run(tmp_path, runner, stopping=StoppingCriteria(criteria=criteria))
    assert result.met_iteration == 3 and result.criteria_met == ("c1_residual_p", "c2_asymptotic_Cd")
    # "any": the Cd criterion alone at iteration 2
    runner = FakeRunner(lines, hold=False)
    result, _, _ = _run(tmp_path, runner, stopping=StoppingCriteria(criteria=criteria, combine="any"))
    assert result.met_iteration == 2 and result.criteria_met == ("c2_asymptotic_Cd",)
    # the minimum iterations delay the stop
    runner = FakeRunner(lines, hold=False)
    result, _, _ = _run(tmp_path, runner, stopping=StoppingCriteria(criteria=criteria, combine="any", min_iterations=4))
    assert result.met_iteration == 4


def test_residual_only_criteria_are_left_to_runtimecontrol(tmp_path: Path) -> None:
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1.0)])  # met at once
    runner = FakeRunner(iteration(1) + iteration(2) + iteration(3) + ["End\n"])
    result, _, _ = _run(tmp_path, runner, stopping=stop)
    assert not runner.stop_requested and result.state == ITERATION_LIMIT


def test_a_user_stop_after_the_criteria_is_not_criteria_met(tmp_path: Path) -> None:
    runner = FakeRunner(iteration(1), hold=True, stop_lines=iteration(2) + ["End\n"])
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=50)])
    result, _, _ = _run(tmp_path, runner, stop=True, stopping=stop)
    assert result.state == STOPPED and result.criteria_met == () and result.met_iteration is None


# -- run record ------------------------------------------------------------------------------------


def test_run_record_round_trip(tmp_path: Path) -> None:
    record = RunRecord(CRITERIA_MET, 123, {"p": 9e-5, "Ux": 1e-6}, "abc", 0, ("Cd: ...",), ("Cd: ...",),
                       ("Cd asymptotic",), 122)
    write_run_record(tmp_path, record)
    assert read_run_record(tmp_path) == record
    assert read_run_record(tmp_path).label == "Criteria met: Cd asymptotic"
    remove_run_record(tmp_path)
    assert read_run_record(tmp_path) is None


def test_converged_run_records_are_migrated(tmp_path: Path) -> None:
    """A record written before D-058 was revised says "converged": read as criteria met, without
    names when it has none, and written back with the new state."""
    import json

    (tmp_path / "vortexcfd_run.json").write_text(json.dumps(
        {"state": "converged", "iterations": 60, "final_residuals": {"p": 1e-5}, "inputs_hash": "h",
         "exit_code": 0, "criteria": ["p initial residual < 0.001"], "stopped_by": ["p initial residual < 0.001"]}))
    record = read_run_record(tmp_path)
    assert record.state == CRITERIA_MET and record.label == "Criteria met" and record.met_iteration is None
    assert record.stopped_by == ("p initial residual < 0.001",) and record.iterations == 60
    saved = json.loads((tmp_path / "vortexcfd_run.json").read_text())
    assert saved["state"] == "criteria_met" and saved["met_labels"] == []


@pytest.mark.parametrize("text", ["not json", '{"state": "exploded", "iterations": 1, "inputs_hash": ""}',
                                  '{"state": "converged"}', "[]"])
def test_unreadable_run_record_is_none(tmp_path: Path, text: str) -> None:
    (tmp_path / "vortexcfd_run.json").write_text(text)
    assert read_run_record(tmp_path) is None


# -- real OpenFOAM ----------------------------------------------------------------------------------


@pytest.mark.slow
def test_real_simplefoam_clean_stop_on_the_session_mesh(sphere_mesh, tmp_path: Path) -> None:
    """simpleFoam on the shared sphere mesh through SolverRun: a stop after a few iterations is a
    clean SIGUSR1 stop (exit code 0, the current iteration written) classified as "stopped"."""
    import shutil
    import threading

    from vortexcfd.core.model import Inflow, Physics, Solvers
    from vortexcfd.foam.case_writer import enable_clean_stop
    from vortexcfd.foam.dictfile import write_foam_file
    from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files

    case = tmp_path / "case"
    shutil.copytree(sphere_mesh.case_dir, case)
    inputs = sphere_mesh.inputs
    inp = SolverCaseInput(Physics(), Inflow(), Solvers(iterations=500, write_interval=500),
                          inputs.parts, inputs.parts_bounds, False)
    for rel, spec in enable_clean_stop(build_solver_files(inp)).items():
        write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    three = threading.Event()
    steps: list = []

    def on_step(step) -> None:
        steps.append(step)
        if len(steps) >= 3:
            three.set()

    run = SolverRun(case, on_step=on_step, timeout_s=100)
    run.start()
    try:
        assert three.wait(90), "simpleFoam did not complete 3 iterations"
        run.request_stop()
        result = run.wait(60)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(30)
    assert result is not None and result.exit_code == 0, (case / LOG_NAME).read_text()[-1500:]
    assert result.state == STOPPED and result.iterations >= 3
    assert (case / str(result.iterations) / "U").is_file()  # the stop wrote the current iteration
    assert {"Ux", "p", "k", "omega"} <= set(result.final_residuals)
