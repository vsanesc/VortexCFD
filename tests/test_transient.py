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
    assert control["adjustTimeStep"] is True and control["maxCo"] == 2.0  # turbulent: PIMPLE at Co 2 (D-185)
    assert control["endTime"] == pytest.approx(100.0)  # 200 flow-through times of 0.5 s
    assert control["deltaT"] == pytest.approx(5e-4) and control["maxDeltaT"] == pytest.approx(0.01)
    assert control["writeControl"] == "adjustableRunTime" and control["writeInterval"] == pytest.approx(10.0)
    assert "runTimeControl1" not in control["functions"] and "fieldAverage1" not in control["functions"]
    assert "forceCoeffs1" in control["functions"]
    schemes = files["system/fvSchemes"].content
    assert schemes["ddtSchemes"] == {"default": "backward"}
    assert schemes["divSchemes"]["div(phi,U)"] == ("Gauss", "linearUpwind", "grad(U)")
    assert schemes["divSchemes"]["div(phi,k)"] == ("Gauss", "linearUpwind", "grad(k)")  # D-192
    assert schemes["divSchemes"]["div(phi,omega)"] == ("Gauss", "linearUpwind", "grad(omega)")
    assert schemes["gradSchemes"]["grad(omega)"] == ("cellLimited", "Gauss", "linear", 1)
    solution = files["system/fvSolution"].content
    assert solution["PIMPLE"] == {"momentumPredictor": True, "nOuterCorrectors": 10, "nCorrectors": 2,
                                  "nNonOrthogonalCorrectors": 0,
                                  "residualControl": {'"(U|k|omega)"': {"tolerance": 1e-4, "relTol": 0}}}
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
    # an interval that does not divide the run is shortened so that the end is a write time
    odd = build_solver_files(_input(time_unit="s", end_time=10.0, write_interval=3.0))
    assert odd["system/controlDict"].content["writeInterval"] == pytest.approx(2.5)
    assert transient.even_interval(12.9, 1.0) == pytest.approx(12.9 / 13)
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


def _laminar(**transient_settings) -> SolverCaseInput:
    inp = _input(**transient_settings)
    return SolverCaseInput(Physics(flow="incompressible_transient", turbulence_model="laminar"), inp.inflow,
                           inp.solvers, inp.patches, inp.parts_bounds)


def test_piso_or_pimple_per_case_type_and_by_choice() -> None:
    """D-185: auto is PISO at Co 1 for a laminar project and PIMPLE (residual control, no relaxation) at Co 2 for a
    turbulent one; the choice and the Courant number override it."""
    files = build_solver_files(_laminar())
    assert files["system/controlDict"].content["maxCo"] == 1.0
    assert files["system/fvSolution"].content["PIMPLE"] == {"momentumPredictor": True, "nOuterCorrectors": 1,
                                                            "nCorrectors": 2, "nNonOrthogonalCorrectors": 0}
    files = build_solver_files(_laminar(algorithm="pimple", max_courant=4.0, outer_correctors=6,
                                        outer_tolerance=1e-5))
    assert files["system/controlDict"].content["maxCo"] == 4.0
    pimple = files["system/fvSolution"].content["PIMPLE"]
    assert pimple["nOuterCorrectors"] == 6 and pimple["residualControl"] == {"U": {"tolerance": 1e-5, "relTol": 0}}
    assert "relaxationFactors" not in files["system/fvSolution"].content
    files = build_solver_files(_input(algorithm="piso"))
    assert files["system/controlDict"].content["maxCo"] == 1.0
    assert "residualControl" not in files["system/fvSolution"].content["PIMPLE"]
    assert Transient().resolved_algorithm(laminar=True) == "piso"
    assert Transient().resolved_max_courant(laminar=False) == 2.0


def test_the_start_up_perturbation_swings_the_inflow_and_holds_the_detection(tmp_path: Path) -> None:
    """D-187: the inflow swings +-10 degrees towards +z at 0.2 U / l_ref for 10 t_c (two periods), the speed kept,
    then along +x; the control file holds the detection until then; off: a plain fixedValue inlet."""
    files = build_solver_files(_input())  # l_ref 2 m at 4 m/s: t_c = 0.5 s, f = 0.4 Hz, 10 t_c = 5 s
    inlet = files["0/U"].content["boundaryField"]["inlet"]
    assert inlet["type"] == "uniformFixedValue"
    kind, rows = inlet["uniformValue"]
    assert kind == "table" and rows[0][0] == 0.0 and rows[-1][0] == pytest.approx(5.0) and len(rows) == 81
    angles = [math.degrees(math.atan2(r[1][2], r[1][0])) for r in rows]
    assert max(angles) == pytest.approx(10.0) and min(angles) == pytest.approx(-10.0)
    assert rows[10][0] == pytest.approx(0.625) and angles[10] == pytest.approx(10.0)  # a quarter period
    assert all(math.hypot(r[1][0], r[1][2]) == pytest.approx(4.0) for r in rows)
    assert rows[-1][1] == [4.0, 0.0, 0.0] and inlet["value"] == [4.0, 0.0, 0.0]
    ctl = transient.TransientControl.from_content(files[transient.TRANSIENT_FILE].content)
    assert ctl.not_before == pytest.approx(5.0) and ctl.range_tolerance == pytest.approx(0.05)
    write_foam_file(tmp_path / "U", files["0/U"].content, object_name="U", class_name="volVectorField")
    assert "uniformValue table ((0.0 (4.0 0.0 0.0)) (0.0625 (" in (tmp_path / "U").read_text()
    off = build_solver_files(_input(perturb=False, detect_tolerance=0.1))
    assert off["0/U"].content["boundaryField"]["inlet"] == {"type": "fixedValue", "value": [4.0, 0.0, 0.0]}
    ctl = transient.TransientControl.from_content(off[transient.TRANSIENT_FILE].content)
    assert ctl.not_before == 0.0 and ctl.range_tolerance == pytest.approx(0.1)
    steady = build_solver_files(SolverCaseInput(Physics(), Inflow(speed=4.0), Solvers(), ("body",),
                                                (0.0, 2.0, -0.5, 0.5, -0.5, 0.5)))
    assert steady["0/U"].content["boundaryField"]["inlet"]["type"] == "fixedValue"


def test_the_detection_tolerance_and_the_end_of_the_perturbation() -> None:
    """D-186 and D-187: a looser range tolerance settles a slowly growing oscillation earlier; nothing is sampled
    before ``not_before`` + 2 W."""
    t = np.arange(0.0, 40.0, 0.01)
    growth = 1.0 + 0.04 * np.minimum(t, 20.0) / 20.0  # the amplitude grows 4 % until t = 20, then stays
    series = {"Cd": list(zip(t, 1.3 + 0.01 * growth * np.sin(4 * np.pi * t))),
              "Cl": list(zip(t, 0.3 * growth * np.sin(2 * np.pi * t)))}
    strict = transient.detect_start(series, 2.0, 0.005, "Cd", range_tolerance=0.002)
    loose = transient.detect_start(series, 2.0, 0.005, "Cd", range_tolerance=0.05)
    assert loose is not None and strict is not None and loose < strict
    held = transient.detect_start(series, 2.0, 0.005, "Cd", not_before=10.0)
    assert held is not None and held >= 14.0 - 1e-9
    assert not transient.settled_at(series, 13.9, 2.0, 0.005, "Cd", not_before=10.0)


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
                                                     "endTime": end, "writeInterval": 1.0, "functions": {}},
                    object_name="controlDict")
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
    assert control["writeInterval"] == pytest.approx((20.0 - 7.1) / 13)  # 13 writes, the last at the end time
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
    assert "old" not in u["boundaryField"]  # the new conditions: the perturbed inlet (D-187)
    assert u["boundaryField"]["inlet"]["type"] == "uniformFixedValue"
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
    assert field.auto.isChecked() and field.spin.value() == 1.0  # laminar: PISO at Co 1 (D-185)
    assert not panel._rows["transient_outer_tolerance"].isVisibleTo(panel)  # PIMPLE only
    field.auto.setChecked(False)
    field.spin.setValue(0.5)
    field.spin.editingFinished.emit()
    assert w.project.sim.solvers.transient.max_courant == 0.5
    assert w._solver_name() == "pimpleFoam"  # (laminar sizing puts the mesh out of date, D-190)
    w.act_undo.trigger()
    w.act_undo.trigger()
    w.project.update_transient(algorithm="pimple")
    assert panel._rows["transient_outer_tolerance"].isVisibleTo(panel)
    assert panel.group_fields["transient"]["max_courant"].spin.value() == 2.0
    assert panel._rows["transient_perturb_angle"].isVisibleTo(panel)
    w.project.update_transient(perturb=False)
    assert not panel._rows["transient_perturb_angle"].isVisibleTo(panel)
    w.project.update_physics(flow="incompressible_steady")
    assert not panel._rows["transient_max_courant"].isVisibleTo(panel)
    assert panel._rows["solvers_iterations"].isVisibleTo(panel)


def test_changing_the_time_unit_converts_the_values(make_window) -> None:
    """D-188 (QUESTIONS 255): flow-through times to seconds and back keep the times; one undo step."""
    w = make_window()
    panel = w.properties
    w.project.update_physics(flow="incompressible_transient")
    w.project.update_transient(end_time=100.0, sampling_start=40.0, window=10.0)
    w._select_node("solvers", None)
    t_c = panel._convective_time()
    assert t_c is not None and t_c > 0
    unit = panel.group_fields["transient"]["time_unit"]
    unit.buttons["s"].setChecked(True)
    s = w.project.sim.solvers.transient
    assert s.time_unit == "s" and s.end_time == pytest.approx(100.0 * t_c)
    assert s.sampling_start == pytest.approx(40.0 * t_c) and s.window == pytest.approx(10.0 * t_c)
    assert s.perturb_time == pytest.approx(10.0 * t_c) and s.write_interval == pytest.approx(20.0 * t_c)
    assert panel.group_fields["transient"]["end_time"].suffix() == " s"
    unit.buttons["flow_through"].setChecked(True)
    s = w.project.sim.solvers.transient
    assert s.end_time == pytest.approx(100.0) and s.sampling_start == pytest.approx(40.0)
    w.act_undo.trigger()
    assert w.project.sim.solvers.transient.time_unit == "s"
    assert w.project.sim.solvers.transient.end_time == pytest.approx(100.0 * t_c)


def test_a_transient_run_through_the_window(make_window, qtbot: QtBot) -> None:
    w = make_window()
    w.project.update_physics(flow="incompressible_transient")
    w.project.update_transient(time_unit="s", end_time=20.0, window=2.0, perturb=False)
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


def _coefficient_rows(case: Path, start: str, t0: float, t1: float) -> None:
    """forceCoeffs1's history from ``t0`` to ``t1`` in the start-time directory ``start`` (a continued run writes a
    new one)."""
    folder = case / "postProcessing" / "forceCoeffs1" / start
    folder.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"{t:.6g}\t{_shedding(t)[0]}\t0\t0\t{_shedding(t)[1]}\t0\t0\t0\t0\t0\t0\t0\t0\n"
                   for t in np.arange(t0, t1 + 0.05, 0.1))
    (folder / "coefficient.dat").write_text("# Time\tCd\tCd(f)\tCd(r)\tCl\tCl(f)\tCl(r)\tCmPitch\tCmRoll\tCmYaw\t"
                                            "Cs\tCs(f)\tCs(r)\n" + rows)


def _written_time(case: Path, name: str) -> None:
    folder = case / name
    folder.mkdir(parents=True, exist_ok=True)
    for field in ("U", "p", "UMean"):
        (folder / field).write_text("FoamFile {}\n")


def test_a_transient_run_continues_to_a_later_end_time(make_window, qtbot: QtBot) -> None:
    """D-189: a transient run at its end time continues (not restarted) to a later end: controlDict from the latest
    time with the same fieldAverage start, the statistics over the whole sampling window, the steps counted on."""
    w = make_window()
    w.project.update_physics(flow="incompressible_transient")
    w.project.update_transient(time_unit="s", end_time=10.0, write_interval=5.0, sampling_start=3.0, perturb=False)
    w.project.update_reports(slots=["Cd", "Cl", None])
    case = w.project.path.parent / "case"

    def first_files():
        _coefficient_rows(case, "0", 0.1, 10.0)
        _written_time(case, "10")

    w.solver_worker.runner_factory = lambda: (first_files(), FakeRunner(_steps(0.1, 10.0) + ["End\n"]))[1]
    w.run_solver()
    wait_done(qtbot, w)
    first = w.run_record
    assert first.state == END_TIME and first.transient["steps"] == 100
    assert w.solver_mode() == "continue"
    w.dialogs.more_time = 15.0

    def second_files():
        _coefficient_rows(case, "10", 10.1, 15.0)

    w.solver_worker.runner_factory = lambda: (second_files(), FakeRunner(_steps(10.1, 15.0) + ["End\n"]))[1]
    w.run_solver()
    assert w.dialogs.more_time_asked == [(pytest.approx(10.0, rel=1e-3), 10.0, " s")]
    control = read_foam_file(case / "system" / "controlDict")
    assert control["startFrom"] == "latestTime" and control["endTime"] == pytest.approx(15.0)
    assert control["functions"]["fieldAverage1"]["timeStart"] == pytest.approx(3.0)
    assert control["writeInterval"] == pytest.approx(5.0)
    wait_done(qtbot, w)
    record = w.run_record
    assert record.state == END_TIME and w.project.sim.solvers.transient.end_time == 15.0
    assert record.transient["steps"] == 150 and record.transient["end_time"] == pytest.approx(15.0)
    assert record.transient["sampling_start"] == pytest.approx(3.0)
    stats = record.transient["statistics"]["coefficients"]["Cd"]
    assert stats["start"] == pytest.approx(3.0) and stats["end"] == pytest.approx(15.0)
    assert [s["first"] for s in record.segments] == [1, 101] and record.segments[-1]["continued_from"] == 100
    assert transient.read_control(case).sampling_start == pytest.approx(3.0)


def test_a_changed_transient_set_up_can_only_start_over(make_window, qtbot: QtBot) -> None:
    """D-189: a later end time keeps the solution continuable; another time step does not (start over)."""
    w = make_window()
    w.project.update_physics(flow="incompressible_transient")
    w.project.update_transient(time_unit="s", end_time=10.0, sampling_start=3.0, perturb=False)
    case = w.project.path.parent / "case"

    def files():
        _coefficient_rows(case, "0", 0.1, 10.0)
        _written_time(case, "10")

    w.solver_worker.runner_factory = lambda: (files(), FakeRunner(_steps(0.1, 10.0) + ["End\n"]))[1]
    w.run_solver()
    wait_done(qtbot, w)
    record = w.run_record
    w.project.update_transient(end_time=30.0, write_interval=7.0, statistics_stop=True)
    assert not solving.settings_changed(w.project, record)
    w.project.update_transient(max_courant=3.0)
    assert solving.settings_changed(w.project, record)
    w.dialogs.choices = [None]
    w.run_solver()
    assert w.dialogs.choices_asked[-1][2] == ["start_over"] and not w.dialogs.more_time_asked
    with pytest.raises(solving.SolvingNotReady, match="start over"):
        solving.prepare_continue(w.project, record)


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


def test_a_laminar_project_sizes_its_layers_by_a_first_cell_thickness(make_window) -> None:
    """D-190 (QUESTIONS 252): a laminar project has no y+ row; its first layer is the first-cell thickness (auto:
    0.1 sqrt(nu L / U)); a turbulent project and its mesh hash are unchanged."""
    import math as _math

    from vortexcfd.workflow import meshing

    w = make_window()
    panel = w.properties
    before = meshing.inputs_hash(w.project)
    w.project.update_mesh(first_layer_height=None)
    assert meshing.inputs_hash(w.project) == before  # an unset thickness keeps every project's hash
    w._select_node("mesh", None)
    assert panel._rows["mset_target_yplus"].isVisibleTo(panel)
    assert not panel._rows["mset_first_layer_height"].isVisibleTo(panel)
    turbulent = meshing.yplus_first_layer(w.project, 1.0)
    w.project.update_physics(turbulence_model="laminar")
    assert meshing.inputs_hash(w.project) != before  # the layers are sized differently
    w._select_node("mesh", None)
    assert not panel._rows["mset_target_yplus"].isVisibleTo(panel)
    assert panel._rows["mset_first_layer_height"].isVisibleTo(panel)
    assert panel.mesh_fields["layer_sizing"].text_of("absolute_yplus") == "Absolute: from a first-cell thickness"
    sim = w.project.sim
    auto = 0.1 * _math.sqrt(sim.physics.nu * 1.0 / sim.inflow.speed)
    assert meshing.yplus_first_layer(w.project, 1.0) == pytest.approx(auto) and auto != pytest.approx(turbulent)
    field = panel.mesh_fields["first_layer_height"]
    assert field.auto.isChecked() and field.spin.value() > 0
    w.project.update_mesh(first_layer_height=2e-4)
    assert meshing.yplus_first_layer(w.project, 1.0) == 2e-4
    w.project.update_physics(turbulence_model="kOmegaSST")
    assert meshing.yplus_first_layer(w.project, 1.0) == pytest.approx(turbulent)  # y+ again
    assert panel.mesh_fields["layer_sizing"].text_of("absolute_yplus") == "Sized from a target y+"


def _ddes(**physics) -> SolverCaseInput:
    inp = _input()
    return SolverCaseInput(Physics(flow="incompressible_transient", turbulence_model="kOmegaSSTDDES", **physics),
                           inp.inflow, inp.solvers, inp.patches, inp.parts_bounds)


def test_ddes_dictionaries() -> None:
    """D-191: an LES-type turbulenceProperties with kOmegaSSTDDES, the delta and sigma; DEShybrid with the case's U
    and l_ref (or LUST); exactDistance; fd and LESRegion written; PIMPLE at Co 1; k and omega kept."""
    files = build_solver_files(_ddes())
    props = files["constant/turbulenceProperties"].content
    assert props["simulationType"] == "LES"
    les = props["LES"]
    assert les["LESModel"] == "kOmegaSSTDDES" and les["delta"] == "DeltaOmegaTilde"
    assert les["kOmegaSSTDDESCoeffs"] == {"useSigma": True}
    schemes = files["system/fvSchemes"].content
    assert schemes["divSchemes"]["div(phi,U)"] == ("Gauss", "DEShybrid", "linear", "linearUpwind", "grad(U)",
                                                   "delta", 0.65, 4.0, 2.0, 0.0, 1.0, 1.0, 10.0)
    assert schemes["divSchemes"]["div(phi,k)"] == ("Gauss", "linearUpwind", "grad(k)")
    assert schemes["wallDist"] == {"method": "meshWave", "nRequired": True}
    control = files["system/controlDict"].content
    assert control["maxCo"] == 1.0
    assert control["functions"]["desFields"]["fields"] == ["fd", "LESRegion"]
    assert "residualControl" in files["system/fvSolution"].content["PIMPLE"]
    assert {"0/k", "0/omega", "0/nut"} <= set(files)
    lust = build_solver_files(_ddes(des_scheme="LUST", des_delta="maxDeltaxyz", des_use_sigma=False))
    assert lust["system/fvSchemes"].content["divSchemes"]["div(phi,U)"] == ("Gauss", "LUST", "grad(U)")
    assert lust["constant/turbulenceProperties"].content["LES"]["delta"] == "maxDeltaxyz"
    urans = build_solver_files(_input())  # URANS unchanged
    assert urans["constant/turbulenceProperties"].content["simulationType"] == "RAS"
    assert urans["system/fvSchemes"].content["wallDist"] == {"method": "meshWave"}
    assert "desFields" not in urans["system/controlDict"].content["functions"]
    with pytest.raises(ValueError, match="transient"):
        Physics(turbulence_model="kOmegaSSTDDES")


def test_ddes_project_checks(make_window) -> None:
    """D-191: DDES keeps other projects' hashes, is refused in 2D, warns without a fine focus region and shows its
    rows only when chosen."""
    from vortexcfd.core.model import BoxShape, RefinementVolume

    w = make_window()
    panel = w.properties
    before = solving.results_hash(w.project)
    w.project.update_physics(flow="incompressible_transient")
    w._select_node("physics", None)
    assert not panel._rows["physics_des_delta"].isVisibleTo(panel)
    w.project.update_physics(turbulence_model="kOmegaSSTDDES")
    assert panel._rows["physics_des_delta"].isVisibleTo(panel)
    assert "focus region" in solving.ddes_mesh_warning(w.project)
    assert panel.physics_ddes_warning.isVisibleTo(panel) and "Recommended averaging" in panel.physics_ddes_note.text()
    w.project.update_physics(flow="incompressible_steady", turbulence_model="kOmegaSST")
    assert solving.results_hash(w.project) == before  # the DDES fields are not in a non-DDES hash
    w.project.update_physics(flow="incompressible_transient", turbulence_model="kOmegaSSTDDES")
    sim = w.project.sim
    w.project._sim = sim.model_copy(update={"refinement_volumes": [RefinementVolume(
        id="f", name="Focus", shape=BoxShape(centre=(0.0, 0.0, 0.0), size=(10.0, 10.0, 10.0)), target_size=0.01)]})
    assert solving.ddes_mesh_warning(w.project) is None
    w.project._sim = w.project.sim.model_copy(update={"refinement_volumes": [RefinementVolume(
        id="f", name="Focus", shape=BoxShape(centre=(0.0, 0.0, 0.0), size=(0.2, 1.0, 1.0)), target_size=0.05)]})
    assert "cells across" in solving.ddes_mesh_warning(w.project)
    w.project._sim = w.project.sim.model_copy(update={"dimension": "2d"})
    assert "2D" in (solving.transient_problem(w.project, [], [], [], []) or "")


def test_a_sampling_start_set_by_hand_after_an_undetected_start_up(make_window, qtbot: QtBot) -> None:
    """D-189: a run whose start-up was never detected continues with a sampling start set by hand: the statistics
    from it over the whole history, the field averages from the restart."""
    w = make_window()
    w.project.update_physics(flow="incompressible_transient")
    w.project.update_transient(time_unit="s", end_time=10.0, window=20.0, perturb=False)  # never detected
    w.project.update_reports(slots=["Cd", "Cl", None])
    case = w.project.path.parent / "case"

    def first_files():
        _coefficient_rows(case, "0", 0.1, 10.0)
        _written_time(case, "10")

    w.solver_worker.runner_factory = lambda: (first_files(), FakeRunner(_steps(0.1, 10.0) + ["End\n"]))[1]
    w.run_solver()
    wait_done(qtbot, w)
    first = w.run_record
    assert first.transient["sampling_start"] is None and first.transient["statistics"] is None
    w.project.update_transient(sampling_start=4.0)
    assert not solving.settings_changed(w.project, first)
    w.dialogs.more_time = 12.0
    w.solver_worker.runner_factory = lambda: (_coefficient_rows(case, "10", 10.1, 12.0),
                                              FakeRunner(_steps(10.1, 12.0) + ["End\n"]))[1]
    w.run_solver()
    control = read_foam_file(case / "system" / "controlDict")
    assert control["functions"]["fieldAverage1"]["timeStart"] == pytest.approx(10.0)
    wait_done(qtbot, w)
    stats = w.run_record.transient["statistics"]["coefficients"]["Cd"]
    assert w.run_record.transient["sampling_start"] == pytest.approx(4.0) and stats["start"] == pytest.approx(4.0)
    assert not w.run_record.transient["detected"]


def test_a_courant_number_held_down_by_the_largest_step_is_reported(make_window, qtbot: QtBot) -> None:
    """D-194: an adaptive run whose step sits at the largest time step while the Courant number stays below the
    asked one shows a warning in the monitors; a run that reaches it does not."""
    from vortexcfd.foam.logparse import TimeStep

    control = transient.TransientControl(1.0, 1.0, 1.0, 10.0, 2.0, 0.005, max_courant=5.0, max_delta_t=0.02)
    capped = [TimeStep(time=0.02 * i, courant_max=3.7, delta_t=0.02) for i in range(1, 60)]
    text = transient.courant_cap_warning(control, capped)
    assert text is not None and "0.02 s" in text and "3.7" in text and "5 asked for" in text
    reached = [TimeStep(time=0.01 * i, courant_max=4.98, delta_t=0.01) for i in range(1, 60)]
    assert transient.courant_cap_warning(control, reached) is None
    fixed = transient.TransientControl(1.0, 1.0, 1.0, 10.0, 2.0, 0.005)
    assert transient.courant_cap_warning(fixed, capped) is None
    files = build_solver_files(_input(max_courant=5.0, max_delta_t=0.02))
    written = transient.TransientControl.from_content(files[transient.TRANSIENT_FILE].content)
    assert written.max_courant == 5.0 and written.max_delta_t == 0.02
    assert transient.TransientControl.from_content(
        build_solver_files(_input(time_step="fixed"))[transient.TRANSIENT_FILE].content).max_courant is None
    w = make_window()  # in the monitors
    case = w.project.path.parent / "case"
    case.mkdir(exist_ok=True)
    transient.write_control(case, control)
    w.monitors.load_run(case, capped, ("end_time", (), 59))
    texts = [label.text() for label in w.monitors.convergence.warnings]
    assert any("holds the step" in s for s in texts)
