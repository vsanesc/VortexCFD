"""Stopping criteria (schema v6), the runTimeControl dictionary, their live evaluation, the
CriteriaMet log event and the oscillation check (D-058, D-059)."""

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from vortexcfd.core.model import (
    CURRENT_SCHEMA_VERSION,
    AsymptoticCriterion,
    ResidualCriterion,
    Solvers,
    StoppingCriteria,
)
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import load_simulation
from vortexcfd.foam.convergence import (
    asymptotic_delta,
    condition_name,
    describe,
    earliest_iteration,
    evaluate,
    linear_change,
    oscillation,
    residual_value,
    run_time_control,
    unique_by_iteration,
)
from vortexcfd.foam.logparse import CriteriaMet, parse_log_text
from vortexcfd.foam.postprocessing import ForceCoeffsTail
from vortexcfd.foam.solver_run import CONVERGED, classify

DATA = Path(__file__).parent / "data"
FOAM_SRC = Path("/usr/lib/openfoam/openfoam2606/src")


# -- model and migration -------------------------------------------------------------------------------


def test_criteria_validation_and_discriminator() -> None:
    stop = StoppingCriteria.model_validate({"criteria": [
        {"kind": "residual", "field": "U", "threshold": 1e-5},
        {"kind": "asymptotic", "quantity": "Cd", "window": 30, "tolerance": 2e-4}], "combine": "any",
        "min_iterations": 40})
    assert isinstance(stop.criteria[0], ResidualCriterion) and isinstance(stop.criteria[1], AsymptoticCriterion)
    assert AsymptoticCriterion(quantity="Cl").window == 50 and AsymptoticCriterion(quantity="Cl").tolerance == 1e-4
    for bad in ({"kind": "residual", "field": "p", "threshold": 0}, {"kind": "residual", "field": "T", "threshold": 1},
                {"kind": "asymptotic", "quantity": "Cd", "window": 1}, {"kind": "asymptotic", "quantity": "Cs"},
                {"kind": "asymptotic", "quantity": "Cd", "tolerance": -1}, {"kind": "maxTime"}):
        with pytest.raises(ValidationError):
            StoppingCriteria(criteria=[bad])
    for bad in ({"combine": "majority"}, {"min_iterations": -1}, {"oscillation_threshold": 0},
                {"oscillation_window": 3}):
        with pytest.raises(ValidationError):
            StoppingCriteria(**bad)
    assert StoppingCriteria(criteria=[]).criteria == []  # only the iteration limit


def test_stopping_edit_is_one_undoable_step_and_round_trips(tmp_path: Path) -> None:
    p = Project.new("s")
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cl", window=40, tolerance=5e-4)],
                            combine="any", min_iterations=100)
    p.update_solver(stopping=stop.model_dump())
    assert p.sim.solvers.stopping == stop and p.undo_label == "Edit solver (stopping)"
    p.save(tmp_path / "s.json")
    assert Project.open(tmp_path / "s.json").sim.solvers.stopping == stop
    p.undo()
    assert p.sim.solvers.stopping == StoppingCriteria()


def test_v5_fixture_migrates_residual_targets_to_criteria() -> None:
    """Hand-written v5 project (tests/data/project_v5.json): its residual targets become residual
    criteria combined with "all"; k, not set in the file, keeps its old default; the rest is kept."""
    raw = json.loads((DATA / "project_v5.json").read_text())
    assert raw["schema_version"] == 5 and "residual_p" in raw["solvers"]
    sim = load_simulation(DATA / "project_v5.json")
    assert sim.schema_version == CURRENT_SCHEMA_VERSION == 6
    stop = sim.solvers.stopping
    assert stop.combine == "all" and stop.min_iterations == 0
    assert [(c.field, c.threshold) for c in stop.criteria] == [("p", 2e-5), ("U", 3e-6), ("k", 1e-5), ("omega", 4e-6)]
    assert (sim.solvers.iterations, sim.solvers.write_interval) == (600, 100)
    assert sim.geometry.parts[0].surface_level_max == 6 and sim.inflow.speed == 30.0
    assert sim.reports.slots == ["Cd", "Cl", None]


# -- runTimeControl dictionary ---------------------------------------------------------------------------


def _source_has(keyword: str, *files: str) -> bool:
    return any(f'"{keyword}"' in (FOAM_SRC / f).read_text() for f in files)


RTC = "functionObjects/utilities/runTimeControl/"
CONDITION = RTC + "runTimeCondition/runTimeCondition/runTimeCondition.C"
AVERAGE = (RTC + "runTimeCondition/averageCondition/averageCondition.C",
           "OpenFOAM/db/functionObjects/valueAverageBase/valueAverageBase.C", CONDITION)
RESIDUAL = (RTC + "runTimeCondition/equationInitialResidualCondition/equationInitialResidualCondition.C",
            "finiteVolume/functionObjects/fieldSelections/fieldSelection/fieldSelection.C", CONDITION)


@pytest.mark.skipif(not FOAM_SRC.is_dir(), reason="OpenFOAM v2606 sources not installed")
def test_run_time_control_uses_the_v2606_keywords() -> None:
    """Every keyword and enum word written is one the v2606 sources read."""
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1e-4),
                                      AsymptoticCriterion(quantity="Cd", window=20, tolerance=1e-3)],
                            min_iterations=10)
    fo = run_time_control(stop)
    assert fo["type"] == "runTimeControl" and fo["libs"] == ["utilityFunctionObjects"]
    for key in ("conditions", "satisfiedAction"):
        assert _source_has(key, RTC + "runTimeControl.C")
    assert _source_has(fo["satisfiedAction"], RTC + "runTimeControl.C")  # "end"
    residual, average = fo["conditions"].values()
    assert residual["type"] == "equationInitialResidual" and average["type"] == "average"
    for key in set(residual) - {"type"}:
        assert _source_has(key, *RESIDUAL), key
    assert _source_has(residual["mode"], *RESIDUAL)  # "minimum"
    for key in set(average) - {"type"}:
        assert _source_has(key, *AVERAGE), key
    assert _source_has(average["windowType"], *AVERAGE)  # "exact"
    for name in ("equationInitialResidual", "average"):  # the registered condition type names
        folder = FOAM_SRC / RTC / "runTimeCondition" / f"{name}Condition"
        assert f'TypeName("{name}")' in (folder / f"{name}Condition.H").read_text()


def test_run_time_control_conditions_groups_and_start_up() -> None:
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="U", threshold=1e-5),
                                      AsymptoticCriterion(quantity="Cl", window=30, tolerance=2e-4)],
                            min_iterations=50)
    fo = run_time_control(stop)
    assert list(fo["conditions"]) == ["c1_residual_U", "c2_asymptotic_Cl"]
    res, avg = fo["conditions"].values()
    assert res == {"type": "equationInitialResidual", "fields": ["U"], "value": 1e-5, "mode": "minimum",
                   "timeStart": 50, "groupID": 1}
    # nIterStartUp N first allows a stop at N + 3 (measured): min_iterations 50 -> 47
    assert avg == {"type": "average", "functionObject": "forceCoeffs1", "fields": ["Cl"], "tolerance": 2e-4,
                   "window": 30, "windowType": "exact", "nIterStartUp": 47, "groupID": 1}
    anyof = run_time_control(stop.model_copy(update={"combine": "any"}))
    assert [c["groupID"] for c in anyof["conditions"].values()] == [1, 2]  # one group each
    assert run_time_control(StoppingCriteria(criteria=[])) is None
    # the window governs when it is longer than the minimum iterations
    long = AsymptoticCriterion(quantity="Cd", window=80)
    assert run_time_control(StoppingCriteria(criteria=[long]))["conditions"]["c1_asymptotic_Cd"]["nIterStartUp"] == 77
    assert earliest_iteration(long, 0) == 80 and earliest_iteration(long, 120) == 120
    assert earliest_iteration(ResidualCriterion(field="p", threshold=1), 0) == 3  # time index 3 at the earliest
    assert earliest_iteration(AsymptoticCriterion(quantity="Cd", window=2), 0) == 3


def test_descriptions_state_the_criterion() -> None:
    assert describe(ResidualCriterion(field="p", threshold=1e-4)) == "p initial residual < 0.0001"
    assert describe(AsymptoticCriterion(quantity="CmPitch", window=20, tolerance=1e-3)) == (
        "Cm (pitch): |value - mean of last 20| <= 0.001")
    assert condition_name(2, ResidualCriterion(field="omega", threshold=1)) == "c3_residual_omega"


# -- live evaluation -------------------------------------------------------------------------------------


def test_asymptotic_delta_hand_values_and_repeated_last_row() -> None:
    series = [(i, float(v)) for i, v in enumerate([5, 4, 3, 2, 2, 2], start=1)]
    assert asymptotic_delta(series, 7) is None
    assert asymptotic_delta(series, 3) == 0.0
    assert asymptotic_delta(series, 4) == pytest.approx(abs(2 - 9 / 4))
    # writeAndEnd writes the final row twice: it counts once
    assert unique_by_iteration(series + [(6, 2.0)]) == series
    assert asymptotic_delta(series + [(6, 2.0)], 4) == asymptotic_delta(series, 4)


def test_evaluate_reports_value_threshold_and_satisfied() -> None:
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="U", threshold=1e-3),
                                      ResidualCriterion(field="p", threshold=1e-3),
                                      AsymptoticCriterion(quantity="Cd", window=3, tolerance=0.01)],
                            min_iterations=4)
    residuals = {"Ux": [(4, 1e-4)], "Uy": [(4, 5e-4)], "Uz": [(4, 2e-3)], "p": [(4, 1e-4)]}
    assert residual_value(residuals, "U") == (4, 2e-3)
    cd = {"Cd": [(1, 1.0), (2, 0.5), (3, 0.5), (4, 0.5)]}
    u, p, a = evaluate(stop, residuals, lambda q: cd.get(q, []))
    assert (u.value, u.threshold, u.satisfied) == (2e-3, 1e-3, False)
    assert (p.value, p.satisfied) == (1e-4, True)
    assert (a.value, a.threshold, a.satisfied) == (0.0, 0.01, True)
    early = evaluate(stop.model_copy(update={"min_iterations": 10}), residuals, lambda q: cd.get(q, []))
    assert not early[1].satisfied and early[1].note == "from iteration 10"
    none = evaluate(stop, {}, lambda q: [])
    assert all(s.value is None and not s.satisfied for s in none)


def test_python_mirror_agrees_with_the_real_stop() -> None:
    """tests/data/stop_run: OpenFOAM stopped at iteration 49 on |Cd - mean of 20| <= 1e-3. The
    mirror computes the same delta from coefficient.dat: met at 49, not met at any earlier
    iteration from the earliest one (20)."""
    tail = ForceCoeffsTail(DATA / "stop_run" / "coefficient.dat")
    tail.poll()
    cd = unique_by_iteration(tail.series["Cd"])
    assert cd[-1][0] == 49 and len(cd) == 49
    deltas = {int(t): asymptotic_delta(cd[:i], 20) for i, (t, _) in enumerate(cd, start=1)}
    assert deltas[49] <= 1e-3
    assert all(deltas[i] > 1e-3 for i in range(20, 49))
    # the log prints the delta of the stopping iteration: "CdMean: 0.176298, delta: 0.000285946"
    log = (DATA / "stop_run" / "log.simpleFoam").read_text()
    # (coefficient.dat keeps 7 significant digits: about 1e-7 of rounding in a difference of 0.17s)
    assert "delta: 0.000285946" in log and deltas[49] == pytest.approx(0.000285946, abs=2e-7)


# -- log event and end state ------------------------------------------------------------------------------


def test_criteria_met_is_parsed_from_the_real_log_and_classified_converged() -> None:
    parser = parse_log_text((DATA / "stop_run" / "log.simpleFoam").read_text())
    assert parser.criteria_met == CriteriaMet(("c1_asymptotic_Cd",), 49.0)
    assert [e for e in parser.events if isinstance(e, CriteriaMet)] == [parser.criteria_met]
    assert parser.has_ended and parser.time_steps[-1].time == 49.0
    assert classify(0, False, parser) == CONVERGED


def test_condition_lines_without_a_stop_are_dropped() -> None:
    text = ("Time = 1\nExecutionTime = 1 s\n    average: a condition satisfied\n    Conditions not met\n"
            "Time = 2\nExecutionTime = 2 s\n    equationInitialResidual: b condition satisfied\n"
            "    average: c condition satisfied\n    Stopping calculation\nEnd\n")
    parser = parse_log_text(text)
    assert parser.criteria_met == CriteriaMet(("b", "c"), 2.0)


# -- oscillation ----------------------------------------------------------------------------------------------


def _sine(n: int, mean: float, amp: float, period: float, drift: float = 0.0):
    return [(i, mean + amp * math.sin(2 * math.pi * i / period) + drift * i) for i in range(1, n + 1)]


def test_oscillation_on_synthetic_series() -> None:
    # Cl = 0.5 +- 0.01 (relative amplitude 0.02 / 0.5 = 4 %) over 5 periods of 20 iterations
    osc = oscillation("Cl", _sine(200, 0.5, 0.01, 20), 100, 0.01)
    assert osc is not None and osc.amplitude == pytest.approx(0.04, rel=0.01)
    assert osc.message() == "Cl oscillates by 4% - the flow may be unsteady; a steady solution may not exist"
    assert oscillation("Cl", _sine(200, 0.5, 0.001, 20), 100, 0.01) is None  # 0.4 % < 1 %
    assert oscillation("Cl", _sine(200, 0.5, 0.01, 20), 100, 0.05) is None  # above a 5 % threshold only
    assert oscillation("Cd", [(i, 1.0 - 0.001 * i) for i in range(1, 201)], 100, 0.01) is None  # a drift
    assert oscillation("Cd", _sine(200, 0.5, 0.002, 20, drift=0.001), 100, 0.01) is None  # drift + ripple
    assert oscillation("Cd", [(i, 0.3) for i in range(1, 201)], 100, 0.01) is None  # settled
    assert oscillation("Cl", _sine(200, 0.0, 0.01, 20), 100, 0.01) is None  # mean ~0: undefined
    assert oscillation("Cl", _sine(50, 0.5, 0.01, 20), 100, 0.01) is None  # window not full
    assert linear_change([0.0, 1.0, 2.0, 3.0]) == pytest.approx(3.0)


def test_oscillation_on_a_real_series() -> None:
    """tests/data/oscillation_run (172 real iterations on the coarse sphere, default window 100):
    over iterations 73-172 Cl swings between 0.038 and 0.092 around 0.061 (88 %) and Cd between
    0.161 and 0.180 around 0.169 (11 %), both without a trend: both are flagged. CmPitch (mean
    2.4e-4) is below the mean floor and is not evaluated."""
    tail = ForceCoeffsTail(DATA / "oscillation_run" / "coefficient.dat")
    tail.poll()
    cl = oscillation("Cl", tail.series["Cl"], 100, 0.01)
    assert cl is not None and cl.amplitude == pytest.approx(0.8776, abs=1e-3) and cl.mean == pytest.approx(0.06135, abs=1e-4)
    cd = oscillation("Cd", tail.series["Cd"], 100, 0.01)
    assert cd is not None and cd.amplitude == pytest.approx(0.1104, abs=1e-3)
    assert cd.message().startswith("Cd oscillates by 11%")
    assert oscillation("CmPitch", tail.series["CmPitch"], 100, 0.01) is None
    assert oscillation("Cd", tail.series["Cd"], 100, 0.2) is None  # an 11 % swing under a 20 % threshold


# -- real run ------------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_asymptotic_cd_criterion_stops_simplefoam_on_the_session_mesh(sphere_mesh, tmp_path: Path) -> None:
    """An asymptotic criterion on Cd (window 20, tolerance 1e-3) stops simpleFoam through
    runTimeControl well before the 150-iteration limit: a clean end (exit code 0, End, the last
    iteration written), state converged, the condition named in the log, and the Python mirror
    agreeing with OpenFOAM on the stopping iteration."""
    import shutil

    from vortexcfd.core.model import Inflow, Physics
    from vortexcfd.foam.case_writer import enable_clean_stop
    from vortexcfd.foam.dictfile import write_foam_file
    from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files
    from vortexcfd.foam.postprocessing import FORCE_COEFFS, FORCE_COEFFS_FILE, output_file
    from vortexcfd.foam.solver_run import LOG_NAME, SolverRun

    case = tmp_path / "case"
    shutil.copytree(sphere_mesh.case_dir, case)
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=20, tolerance=1e-3)])
    inp = SolverCaseInput(Physics(), Inflow(), Solvers(iterations=150, write_interval=50, stopping=stop),
                          sphere_mesh.inputs.parts, sphere_mesh.inputs.parts_bounds, False)
    for rel, spec in enable_clean_stop(build_solver_files(inp)).items():
        write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    run = SolverRun(case, timeout_s=110)
    run.start()
    try:
        result = run.wait(115)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(30)
    assert result is not None and result.exit_code == 0, (case / LOG_NAME).read_text()[-1500:]
    assert result.state == CONVERGED and result.criteria_met == ("c1_asymptotic_Cd",)
    assert 20 <= result.iterations < 150
    assert (case / str(result.iterations) / "U").is_file()  # writeAndEnd wrote the last iteration
    tail = ForceCoeffsTail(output_file(case, FORCE_COEFFS, FORCE_COEFFS_FILE))
    tail.poll()
    cd = unique_by_iteration(tail.series["Cd"])
    assert cd[-1][0] == result.iterations
    assert asymptotic_delta(cd, 20) <= 1e-3
    assert all(asymptotic_delta(cd[:i], 20) > 1e-3 for i in range(20, len(cd)))
    print(f"\nstopped at iteration {result.iterations}: Cd {cd[-1][1]:.6g}, "
          f"|Cd - mean20| {asymptotic_delta(cd, 20):.3g} <= 1e-3")
