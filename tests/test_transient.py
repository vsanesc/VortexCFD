"""Transient flow with pimpleFoam (D-181) and the laminar model (D-182): the case files (adaptive and fixed time steps,
fieldAverage, the control file), the pimpleFoam log, the statistics (time-weighted mean and RMS, running mean, the
start-up detection, the statistics stop, the Strouhal number), SolverRun with fake runners (the sampling switch, the
statistics stop, the end time), the start from a steady solution, older projects unchanged, and the GUI rows and
monitors."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Inflow, Physics, Reports, Simulation, Solvers, Transient
from vortexcfd.core.project_io import load_simulation, migrate
from vortexcfd.foam import transient
from vortexcfd.foam.dictfile import read_foam_file, write_foam_file
from vortexcfd.foam.logparse import parse_log_text
from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files, transient_times
from vortexcfd.foam.run_record import RunRecord, read_run_record, write_run_record
from vortexcfd.foam.solver_run import CRITERIA_MET, END_TIME, STATISTICS_STOP, SolverRun, solver_log
from vortexcfd.workflow import solving

DATA = Path(__file__).parent / "data"


def _input(**transient_settings) -> SolverCaseInput:
    """A unit body (l_ref 2 m) at 4 m/s: t_c = 0.5 s."""
    physics = Physics(flow="incompressible_transient")
    solvers = Solvers(transient=Transient(**transient_settings))
    return SolverCaseInput(physics, Inflow(speed=4.0), solvers, ("body",), (0.0, 2.0, -0.5, 0.5, -0.5, 0.5))


# -- the case files --------------------------------------------------------------------------------------------------


def test_adaptive_time_step_dictionaries() -> None:
    files = build_solver_files(_input())
    control = files["system/controlDict"].content
    assert control["application"] == "pimpleFoam"
    assert control["adjustTimeStep"] is True and control["maxCo"] == 1.0
    assert control["endTime"] == pytest.approx(100.0)  # 200 flow-through times of 0.5 s
    assert control["deltaT"] == pytest.approx(5e-4) and control["maxDeltaT"] == pytest.approx(0.01)
    assert control["writeControl"] == "adjustableRunTime" and control["writeInterval"] == pytest.approx(10.0)
    assert "runTimeControl1" not in control["functions"] and "fieldAverage1" not in control["functions"]
    assert "forceCoeffs1" in control["functions"]
    schemes = files["system/fvSchemes"].content
    assert schemes["ddtSchemes"] == {"default": "backward"}
    assert schemes["divSchemes"]["div(phi,U)"] == ("Gauss", "linearUpwind", "grad(U)")
    assert schemes["divSchemes"]["div(phi,k)"] == ("Gauss", "limitedLinear", 1)
    assert schemes["divSchemes"]["div(phi,omega)"] == ("Gauss", "limitedLinear", 1)
    solution = files["system/fvSolution"].content
    assert solution["PIMPLE"] == {"momentumPredictor": True, "nOuterCorrectors": 1, "nCorrectors": 2,
                                  "nNonOrthogonalCorrectors": 0}
    assert solution["solvers"]["pFinal"]["relTol"] == 0 and solution["solvers"]["omegaFinal"]["relTol"] == 0
    assert solution["solvers"]["p"]["tolerance"] == 1e-6  # the cylinder2D tutorial's
    assert "SIMPLE" not in solution and "relaxationFactors" not in solution
    ctl = transient.TransientControl.from_content(files[transient.TRANSIENT_FILE].content)
    assert ctl.convective_time == pytest.approx(0.5) and ctl.window == pytest.approx(10.0)
    assert ctl.sampling_start is None and ctl.field_average["type"] == "fieldAverage"
    assert "system/turbulenceStages" not in files


def test_fixed_time_step_and_a_set_sampling_start(tmp_path: Path) -> None:
    files = build_solver_files(_input(time_step="fixed", delta_t=0.002, time_unit="s", end_time=3.0,
                                      write_interval=0.5, sampling_start=1.0, outer_correctors=3))
    control = files["system/controlDict"].content
    assert control["adjustTimeStep"] is False and control["deltaT"] == 0.002 and control["endTime"] == 3.0
    assert control["writeControl"] == "runTime"
    average = control["functions"]["fieldAverage1"]
    assert average["timeStart"] == 1.0 and average["executeControl"] == "timeStep"
    assert files["system/fvSolution"].content["PIMPLE"]["nOuterCorrectors"] == 3
    write_foam_file(tmp_path / "controlDict", control, object_name="controlDict")
    text = (tmp_path / "controlDict").read_text()
    assert "fields (U {mean yes; prime2Mean yes; base time;} p {mean yes; prime2Mean yes; base time;});" in text
    # the auto step of a fixed run: 1/200 of t_c
    assert transient_times(_input(time_step="fixed")).delta_t == pytest.approx(0.0025)


def test_laminar_writes_u_and_p_only() -> None:
    inp = _input()
    inp = SolverCaseInput(Physics(flow="incompressible_transient", turbulence_model="laminar"), inp.inflow,
                          inp.solvers, inp.patches, inp.parts_bounds)
    files = build_solver_files(inp)
    assert files["constant/turbulenceProperties"].content == {"simulationType": "laminar"}
    assert sorted(r for r in files if r.startswith("0/")) == ["0/U", "0/p"]
    assert "div(phi,k)" not in files["system/fvSchemes"].content["divSchemes"]
    assert set(files["system/fvSolution"].content["solvers"]) == {"p", "pFinal", "U", "UFinal"}
    steady = SolverCaseInput(Physics(turbulence_model="laminar"), inp.inflow, Solvers(), inp.patches,
                             inp.parts_bounds)
    assert build_solver_files(steady)["system/controlDict"].content["application"] == "simpleFoam"


# -- the log ---------------------------------------------------------------------------------------------------------


def pimple_step(t: float, dt: float, co: float = 0.8, p: float = 1e-3) -> list[str]:
    """One pimpleFoam time step as v2606 prints it: Courant number and deltaT before "Time = "."""
    return [
        f"Courant Number mean: {co / 10} max: {co}\n",
        f"deltaT = {dt:.6g}\n",
        f"Time = {t:.6g}\n",
        "\n",
        "PIMPLE: iteration 1\n",
        f"smoothSolver:  Solving for Ux, Initial residual = {p}, Final residual = {p / 100}, No Iterations 2\n",
        f"GAMG:  Solving for p, Initial residual = {p}, Final residual = {p / 100}, No Iterations 4\n",
        f"GAMG:  Solving for p, Initial residual = {p / 10}, Final residual = {p / 1000}, No Iterations 4\n",
        f"ExecutionTime = {t:.3f} s  ClockTime = 1 s\n",
        "\n",
    ]


def test_the_pimplefoam_log() -> None:
    text = "Courant Number mean: 0 max: 0\n" + "".join("".join(pimple_step(0.001 * (i + 1), 0.001, co=0.1 * (i + 1)))
                                                       for i in range(3)) + "End\n"
    parser = parse_log_text(text)
    assert [s.time for s in parser] == [0.001, 0.002, 0.003]
    assert [s.courant_max for s in parser] == [pytest.approx(0.1), pytest.approx(0.2), pytest.approx(0.3)]
    assert [s.delta_t for s in parser] == [0.001] * 3
    assert parser.has_ended


# -- statistics ------------------------------------------------------------------------------------------------------


def _signal(f, times):
    return [(float(t), float(f(t))) for t in times]


def test_time_weighted_statistics_on_uneven_steps() -> None:
    rng = np.random.default_rng(1)
    times = np.cumsum(rng.uniform(0.005, 0.02, 3000))
    rows = _signal(lambda t: 2.0 + 0.5 * math.sin(2 * math.pi * t), times)
    stats = transient.window_stats(rows, times[0])
    assert stats.mean == pytest.approx(2.0, abs=5e-3)  # not a whole number of periods
    assert stats.rms == pytest.approx(0.5 / math.sqrt(2), rel=5e-3)
    running = transient.running_mean(np.array(times), np.array([v for _, v in rows]))
    assert running[-1] == pytest.approx(stats.mean)


@pytest.mark.parametrize("frequency", [0.165, 1.0, 7.3])
def test_strouhal_of_a_known_frequency(frequency: float) -> None:
    rng = np.random.default_rng(2)
    duration = 12 / frequency  # 12 cycles
    times = np.cumsum(rng.uniform(0.5, 1.5, 6000)) * duration / 6000
    rows = _signal(lambda t: 0.3 * math.sin(2 * math.pi * frequency * t) + 0.05 * math.sin(4 * math.pi * frequency
                                                                                             * t), times)
    st, cycles = transient.strouhal(rows, length=2.0, speed=4.0)
    assert st == pytest.approx(frequency * 2.0 / 4.0, rel=2e-3)
    assert cycles == pytest.approx(12, rel=0.02)
    assert transient.strouhal([(0.0, 1.0)] * 20, 1.0, 1.0) is None  # a constant has no frequency


def _shedding(t: float) -> tuple[float, float]:
    """Cd and Cl of a shedding that grows until t = 2 s and is then stationary (Cl at 0.5 Hz, Cd at 1 Hz)."""
    return 1.3 + 0.01 * math.sin(2 * math.pi * t), min(1.0, t / 2.0) * math.sin(math.pi * t)


def _series(end: float, dt: float = 0.05) -> dict:
    times = np.arange(dt, end + dt / 2, dt)
    return {"Cd": [(t, _shedding(t)[0]) for t in times], "Cl": [(t, _shedding(t)[1]) for t in times]}


def test_the_start_up_is_detected_once_the_ranges_and_mean_settle() -> None:
    series = _series(12.0)
    start = transient.detect_start(series, window=2.0, tolerance=0.005, mean_quantity="Cd")
    assert start is not None and 5.4 <= start <= 6.6  # both windows hold a saturated peak and trough
    assert not transient.settled_at(series, 4.5, 2.0, 0.005, "Cd")
    growing = {"Cd": series["Cd"], "Cl": [(t, 0.05 * t * math.sin(math.pi * t)) for t, _ in series["Cl"]]}
    assert transient.detect_start(growing, 2.0, 0.005, "Cd") is None  # an amplitude still growing never settles
    steady = {"Cd": [(t, 0.9) for t, _ in series["Cd"]], "Cl": [(t, 0.0) for t, _ in series["Cl"]]}
    assert transient.detect_start(steady, 2.0, 0.005, "Cd") == pytest.approx(4.0)  # a steady flow at once


def test_the_running_mean_stop() -> None:
    cd = _series(20.0)["Cd"]
    assert transient.running_mean_range(cd, 2.0, 5.0, 2.0) is None  # sampled for less than 2 W
    first = next(t for t, _ in cd if t > 6 and transient.running_mean_stable(cd, 2.0, t, 2.0, 0.001))
    assert 6.0 < first < 9.0
    assert transient.running_mean_stable(cd, 2.0, 20.0, 2.0, 0.001)
    drift = [(t, 1.0 + 0.05 * t) for t, _ in cd]
    assert not transient.running_mean_stable(drift, 2.0, 20.0, 2.0, 0.001)


# -- SolverRun with fake runners -------------------------------------------------------------------------------------


def _transient_case(case: Path, start: float | None = None, stop: bool = False, end: float = 20.0) -> Path:
    write_foam_file(case / "system" / "controlDict", {"application": "pimpleFoam", "startFrom": "startTime",
                                                     "endTime": end, "functions": {}}, object_name="controlDict")
    control = transient.TransientControl(1.0, 1.0, 1.0, end, 2.0, 0.001 if stop else 0.005, "Cd", stop, start,
                                         False, transient.field_average(start or 0.0))
    transient.write_control(case, control)
    folder = case / "postProcessing" / "forceCoeffs1" / "0"
    folder.mkdir(parents=True)
    rows = "".join(f"{t:.6g}\t{_shedding(t)[0]}\t0\t0\t{_shedding(t)[1]}\t0\t0\t0\t0\t0\t0\t0\t0\n"
                   for t in np.arange(0.1, end + 0.05, 0.1))
    (folder / "coefficient.dat").write_text("# Time\tCd\tCd(f)\tCd(r)\tCl\tCl(f)\tCl(r)\tCmPitch\tCmRoll\tCmYaw\t"
                                            "Cs\tCs(f)\tCs(r)\n" + rows)
    return case


def _steps(t0: float, t1: float) -> list[str]:
    return [line for t in np.arange(t0, t1 + 0.05, 0.1) for line in pimple_step(round(float(t), 6), 0.1)]


def _run(case: Path, runners: list[FakeRunner]):
    lines, queue = [], list(runners)
    run = SolverRun(case, on_line=lines.append, runner_factory=lambda: queue.pop(0))
    run.start()
    result = run.wait(20)
    assert result is not None and not run.is_running()
    return result, lines


def test_the_sampling_starts_when_the_start_up_is_over(tmp_path: Path) -> None:
    case = _transient_case(tmp_path)
    first = FakeRunner(_steps(0.1, 7.0), hold=True, stop_lines=pimple_step(7.1, 0.1) + ["End\n"])
    second = FakeRunner(_steps(7.2, 20.0) + ["End\n"])
    result, lines = _run(case, [first, second])
    assert first.stop_requested and first.clean_stop and second.append and second.command[0] == "pimpleFoam"
    assert result.state == END_TIME and result.transient["detected"]
    start = result.transient["sampling_start"]
    assert start == pytest.approx(7.1)  # the latest time after the switch's clean stop
    assert any("Start-up transient over at t = " in line for line in lines)
    control = read_foam_file(case / "system" / "controlDict")
    assert control["startFrom"] == "latestTime" and control["functions"]["fieldAverage1"]["timeStart"] == 7.1
    assert transient.read_control(case).sampling_start == pytest.approx(7.1)
    stats = result.transient["statistics"]
    assert stats["coefficients"]["Cd"]["mean"] == pytest.approx(1.3, abs=1e-3)
    assert stats["coefficients"]["Cl"]["rms"] == pytest.approx(1 / math.sqrt(2), rel=0.02)
    assert stats["strouhal"] == pytest.approx(0.5, rel=0.01) and stats["cycles"] > 6
    assert result.iterations == len(parse_log_text(solver_log(case).read_text()).time_steps) == 200
    assert solver_log(case).name == "log.pimpleFoam"


def test_the_statistics_stop(tmp_path: Path) -> None:
    case = _transient_case(tmp_path, start=2.0, stop=True)
    runner = FakeRunner(_steps(0.1, 15.0), hold=True, stop_lines=pimple_step(15.1, 0.1) + ["End\n"])
    result, _lines = _run(case, [runner])
    assert runner.stop_requested and result.state == CRITERIA_MET
    assert result.criteria_met == (STATISTICS_STOP,) and 6.0 <= result.transient["met_time"] < 9.0
    assert result.transient["sampling_start"] == 2.0 and not result.transient["detected"]
    assert result.met_iteration is None


def test_the_record_keeps_the_transient_results(tmp_path: Path) -> None:
    data = {"end_time": 20.0, "steps": 200, "sampling_start": 7.1, "detected": True, "statistics": {"strouhal": 0.5}}
    write_run_record(tmp_path, RunRecord(END_TIME, 200, transient=data))
    record = read_run_record(tmp_path)
    assert record.transient == data and record.label == "End time reached"
    assert not solving.can_continue(tmp_path, record)  # a transient solution runs from its start


# -- the project -----------------------------------------------------------------------------------------------------


def test_older_projects_stay_steady(tmp_path: Path) -> None:
    sim = load_simulation(DATA / "project_v24.json")
    assert sim.schema_version == CURRENT_SCHEMA_VERSION == 25
    assert sim.physics.flow == "incompressible_steady" and sim.physics.turbulence_model == "kOmegaSST"
    assert sim.solvers.transient == Transient()
    raw = json.loads((DATA / "project_v24.json").read_text())
    assert migrate(raw)["schema_version"] == 25 and "transient" not in migrate(raw)["solvers"]


def test_a_steady_hash_has_no_transient_settings(make_window) -> None:
    w = make_window()
    payload = json.loads(solving._results_payload(w.project))
    assert "transient" not in payload["solvers"]
    before = solving.results_hash(w.project)
    w.project.update_transient(window=5.0)  # a steady project ignores them
    assert solving.results_hash(w.project) == before
    w.project.update_physics(flow="incompressible_transient")
    assert "transient" in json.loads(solving._results_payload(w.project))["solvers"]
    assert solving.results_hash(w.project) != before


def test_start_from_the_steady_solution(make_window) -> None:
    w = make_window()
    case = w.project.path.parent / "case"
    (case / "300").mkdir()
    (case / "300" / "U").write_text("FoamFile\n{\n    version 2.0;\n    format ascii;\n    class volVectorField;\n"
                                    "    object U;\n}\ndimensions [0 1 -1 0 0 0 0];\ninternalField uniform (7 0 0);\n"
                                    "boundaryField\n{\n    old\n    {\n        type zeroGradient;\n    }\n}\n")
    write_run_record(case, RunRecord("criteria_met", 300))
    w.project.update_physics(flow="incompressible_transient")
    w.project.update_transient(start_from="steady")
    assert solving.readiness(w.project, has_mesh=True, mesh_stale=False, meshing=False) is None
    solving.prepare_solver_case(w.project)
    u = read_foam_file(case / "0" / "U")
    assert tuple(u["internalField"]) == (7.0, 0.0, 0.0)  # the steady solution's field
    assert "old" not in u["boundaryField"] and u["boundaryField"]["inlet"]["type"] == "fixedValue"  # new conditions
    assert read_foam_file(case / "0" / "k")["internalField"] != 0  # the free stream: the steady run had none
    assert not (case / "300").exists() and not (case / solving.STEADY_START).exists()
    assert read_foam_file(case / "system" / "controlDict")["application"] == "pimpleFoam"
    (case / "300").mkdir()
    (case / "300" / "U").write_text("x")
    write_run_record(case, RunRecord(END_TIME, 3, transient={"end_time": 1.0}))
    assert "no steady solution" in solving.readiness(w.project, has_mesh=True, mesh_stale=False, meshing=False)


# -- the GUI ---------------------------------------------------------------------------------------------------------


def test_the_rows_of_a_transient_project(make_window) -> None:
    w = make_window()
    panel = w.properties
    w._select_node("physics", None)
    panel.group_fields["physics"]["flow"].buttons["incompressible_transient"].setChecked(True)
    assert w.project.sim.physics.transient
    panel.group_fields["physics"]["turbulence_model"].buttons["laminar"].setChecked(True)
    assert w.project.sim.physics.laminar
    w._select_node("solvers", None)
    assert panel._rows["transient_max_courant"].isVisibleTo(panel)
    assert not panel._rows["solvers_iterations"].isVisibleTo(panel)
    assert "s (l_ref" in panel.transient_convective.text()
    field = panel.group_fields["transient"]["max_courant"]
    field.setValue(0.5)
    field.editingFinished.emit()
    assert w.project.sim.solvers.transient.max_courant == 0.5
    assert "pimpleFoam" in w.top_bar.run_button.toolTip()
    w.act_undo.trigger()
    w.project.update_physics(flow="incompressible_steady")
    assert not panel._rows["transient_max_courant"].isVisibleTo(panel)
    assert panel._rows["solvers_iterations"].isVisibleTo(panel)


def test_a_transient_run_through_the_window(make_window, qtbot: QtBot) -> None:
    w = make_window()
    w.project.update_physics(flow="incompressible_transient")
    w.project.update_transient(time_unit="s", end_time=20.0, window=2.0)
    w.project.update_reports(slots=["Cd", "Cl", None])
    case = w.project.path.parent / "case"

    def coefficients(*_args, **_kwargs):  # the files a run writes, once the solver files are in place
        _transient_case_files(case)

    first = use_runner(w, FakeRunner(_steps(0.1, 7.0), hold=True, stop_lines=pimple_step(7.1, 0.1) + ["End\n"]))
    second = FakeRunner(_steps(7.2, 20.0) + ["End\n"])
    queue = [first, second]
    w.solver_worker.runner_factory = lambda: (coefficients(), queue.pop(0))[1]
    w.run_solver()
    wait_done(qtbot, w)
    record = w.run_record
    assert record.state == END_TIME and record.transient["sampling_start"] == pytest.approx(7.1)
    length = transient.read_control(case).length  # the ball's x extent
    assert record.transient["statistics"]["strouhal"] == pytest.approx(0.5 * length / 20.0, rel=0.01)  # f l_ref / U
    banner = w.monitors.convergence.banner.text()
    assert banner.startswith("End time reached")
    assert "Strouhal number St" in w.monitors.convergence.note.text()
    assert w.monitors.kpis.means[1].text().startswith("running mean 1.3")
    w._load_run_record(w.project)  # reopened: the record's statistics
    assert w.monitors.convergence.banner.text().startswith("End time reached")
    assert w.monitors.chart.X_CAPTION == "Time [s]"


def _transient_case_files(case: Path) -> None:
    folder = case / "postProcessing" / "forceCoeffs1" / "0"
    if (folder / "coefficient.dat").is_file():
        return
    folder.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"{t:.6g}\t{_shedding(t)[0]}\t0\t0\t{_shedding(t)[1]}\t0\t0\t0\t0\t0\t0\t0\t0\n"
                   for t in np.arange(0.1, 20.05, 0.1))
    (folder / "coefficient.dat").write_text("# Time\tCd\tCd(f)\tCd(r)\tCl\tCl(f)\tCl(r)\tCmPitch\tCmRoll\tCmYaw\t"
                                            "Cs\tCs(f)\tCs(r)\n" + rows)


def test_the_mean_fields_are_offered(tmp_path: Path) -> None:
    from vortexcfd.foam.results import FIELDS_BY_KEY, available_fields, field_values, result_times

    folder = tmp_path / "2.5"
    folder.mkdir()
    for name, cls in (("p", "volScalarField"), ("pMean", "volScalarField"), ("pPrime2Mean", "volScalarField"),
                      ("UMean", "volVectorField"), ("UPrime2Mean", "volSymmTensorField")):
        (folder / name).write_text(f"FoamFile\n{{\n    class {cls};\n}}\n")
    (tmp_path / "0.5").mkdir()
    (tmp_path / "0.5" / "p").write_text("FoamFile\n{\n    class volScalarField;\n}\n")
    keys = [spec.key for spec in available_fields(tmp_path)]
    assert {"pMean", "CpMean", "UMean_mag", "p_rms", "Ux_rms", "Uz_rms"} <= set(keys)
    assert result_times(tmp_path) == ["0.5", "2.5"]
    tensor = np.array([[4.0, 0, 0, 9.0, 0, 16.0]])
    assert field_values(FIELDS_BY_KEY["Uy_rms"], {"UPrime2Mean": tensor}, 1.0).tolist() == [3.0]
    assert field_values(FIELDS_BY_KEY["p_rms"], {"pPrime2Mean": np.array([0.25, -1e-12])}, 1.0).tolist() == [0.5, 0.0]


def test_the_studies_refuse_a_transient_project(make_window) -> None:
    from vortexcfd.workflow.mesh_study import study_readiness
    from vortexcfd.workflow.polar_sweep import sweep_readiness

    w = make_window()
    w.project.update_physics(flow="incompressible_transient")
    assert "steady projects only" in study_readiness(w.project)
    assert "steady projects only" in sweep_readiness(w.project)


def test_the_snapshot_and_the_report_carry_the_statistics(make_window) -> None:
    from vortexcfd.workflow import report, snapshots

    w = make_window()
    w.project.update_physics(flow="incompressible_transient")
    case = w.project.path.parent / "case"
    _transient_case_files(case)
    series = {q: rows for q, rows in _series(20.0, 0.1).items()}
    stats = transient.summary(series, 7.0, 1.0, 1.0)
    write_run_record(case, RunRecord(END_TIME, 200, transient={"end_time": 20.0, "steps": 200, "sampling_start": 7.0,
                                                               "detected": True, "convective_time": 1.0,
                                                               "met_time": None, "statistics": stats}))
    snap = snapshots.capture(w.project, "a")
    assert snap.transient["strouhal"] == pytest.approx(0.5, rel=0.01)
    assert snap.reports["Cd"].mean == pytest.approx(stats["coefficients"]["Cd"]["mean"])
    rows = {r.report_id: r for r in snapshots.value_rows([snap, snap])}
    assert rows["transient:St"].values[0] == pytest.approx(0.5, rel=0.01) and "transient:rms:Cl" in rows
    loaded = snapshots.load(snapshots.save(w.project, snap))
    assert loaded.transient == snap.transient
    section = report.reports_section(w.project)
    assert "Strouhal number" in section.body and "RMS" in section.body
    assert "Sampling start" in report.convergence_section(w.project).body
