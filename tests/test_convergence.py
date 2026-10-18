"""Stopping criteria (schema v6), the runTimeControl dictionary of residual-only criteria, the
app-side evaluation (range-based asymptotic criterion), the CriteriaMet log event and the
oscillation check (D-058, D-059)."""

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
    app_side,
    asymptotic_range,
    condition_name,
    criteria_met,
    describe,
    earliest_iteration,
    evaluate,
    first_met_iteration,
    is_native,
    linear_change,
    oscillation,
    relative_range,
    residual_value,
    run_time_control,
    unique_by_iteration,
)
from vortexcfd.foam.logparse import CriteriaMet, parse_log_text
from vortexcfd.foam.postprocessing import ForceCoeffsTail
from vortexcfd.foam.solver_run import CRITERIA_MET, classify

DATA = Path(__file__).parent / "data"
FOAM_SRC = Path("/usr/lib/openfoam/openfoam2606/src")


# -- model and migration -------------------------------------------------------------------------------


def test_criteria_validation_and_discriminator() -> None:
    stop = StoppingCriteria.model_validate({"criteria": [
        {"kind": "residual", "field": "U", "threshold": 1e-5},
        {"kind": "asymptotic", "quantity": "Cd", "window": 30, "tolerance": 2e-3}], "combine": "any",
        "min_iterations": 40})
    assert isinstance(stop.criteria[0], ResidualCriterion) and isinstance(stop.criteria[1], AsymptoticCriterion)
    assert AsymptoticCriterion(quantity="Cl").window == 50 and AsymptoticCriterion(quantity="Cl").tolerance == 1e-3
    # floor: 0.01 by default for coefficients; a probe has no default scale and needs one
    assert AsymptoticCriterion(quantity="Cl@Pod").effective_floor == 0.01
    assert AsymptoticCriterion(quantity="Cd", floor=0.1).effective_floor == 0.1
    assert AsymptoticCriterion(quantity="probe:w:p", floor=2.0).effective_floor == 2.0
    for bad in ({"quantity": "probe:w:p"}, {"quantity": "Cd", "floor": 0}):
        with pytest.raises(ValidationError):
            AsymptoticCriterion(**bad)
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
    assert sim.schema_version == CURRENT_SCHEMA_VERSION
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
RESIDUAL = (RTC + "runTimeCondition/equationInitialResidualCondition/equationInitialResidualCondition.C",
            "finiteVolume/functionObjects/fieldSelections/fieldSelection/fieldSelection.C", CONDITION)


@pytest.mark.skipif(not FOAM_SRC.is_dir(), reason="OpenFOAM v2606 sources not installed")
def test_run_time_control_uses_the_v2606_keywords() -> None:
    """Every keyword and enum word written is one the v2606 sources read."""
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1e-4),
                                      ResidualCriterion(field="U", threshold=1e-5)], min_iterations=10)
    fo = run_time_control(stop)
    assert fo["type"] == "runTimeControl" and fo["libs"] == ["utilityFunctionObjects"]
    for key in ("conditions", "satisfiedAction"):
        assert _source_has(key, RTC + "runTimeControl.C")
    assert _source_has(fo["satisfiedAction"], RTC + "runTimeControl.C")  # "end"
    for residual in fo["conditions"].values():
        assert residual["type"] == "equationInitialResidual"
        for key in set(residual) - {"type"}:
            assert _source_has(key, *RESIDUAL), key
        assert _source_has(residual["mode"], *RESIDUAL)  # "minimum"
    folder = FOAM_SRC / RTC / "runTimeCondition" / "equationInitialResidualCondition"
    assert 'TypeName("equationInitialResidual")' in (folder / "equationInitialResidualCondition.H").read_text()


def test_run_time_control_only_for_residual_criteria() -> None:
    """Residual criteria only: runTimeControl (native). Any asymptotic criterion: no runTimeControl,
    the app evaluates every criterion (D-058)."""
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="U", threshold=1e-5),
                                      ResidualCriterion(field="k", threshold=2e-5)], min_iterations=50)
    assert is_native(stop) and not app_side(stop)
    fo = run_time_control(stop)
    assert list(fo["conditions"]) == ["c1_residual_U", "c2_residual_k"]
    assert fo["conditions"]["c1_residual_U"] == {"type": "equationInitialResidual", "fields": ["U"], "value": 1e-5,
                                                 "mode": "minimum", "timeStart": 50, "groupID": 1}
    anyof = run_time_control(stop.model_copy(update={"combine": "any"}))
    assert [c["groupID"] for c in anyof["conditions"].values()] == [1, 2]  # one group each
    mixed = stop.model_copy(update={"criteria": [*stop.criteria, AsymptoticCriterion(quantity="Cl")]})
    assert run_time_control(mixed) is None and app_side(mixed) and not is_native(mixed)
    assert run_time_control(StoppingCriteria(criteria=[])) is None
    assert not app_side(StoppingCriteria(criteria=[])) and not app_side(None)
    # earliest: the window and the minimum iterations; residuals never before time index 3
    long = AsymptoticCriterion(quantity="Cd", window=80)
    assert earliest_iteration(long, 0) == 80 and earliest_iteration(long, 120) == 120
    assert earliest_iteration(ResidualCriterion(field="p", threshold=1), 0) == 3
    assert earliest_iteration(AsymptoticCriterion(quantity="Cd", window=2), 0) == 2


def test_descriptions_state_the_criterion() -> None:
    assert describe(ResidualCriterion(field="p", threshold=1e-4)) == "p initial residual < 0.0001"
    assert describe(AsymptoticCriterion(quantity="CmPitch", window=20, tolerance=1e-3)) == (
        "Cm (pitch): (max - min) / max(|mean|, 0.01) over the last 20 <= 0.001")
    assert describe(AsymptoticCriterion(quantity="probe:w:U", floor=0.2)) == (
        "Probe w U: (max - min) / max(|mean|, 0.2) over the last 50 <= 0.001")
    assert condition_name(2, ResidualCriterion(field="omega", threshold=1)) == "c3_residual_omega"


# -- live evaluation -------------------------------------------------------------------------------------


def test_relative_range_hand_values_and_repeated_last_row() -> None:
    series = [(i, float(v)) for i, v in enumerate([5, 4, 3, 2, 2, 2], start=1)]
    assert asymptotic_range(series, 7, 0.01) is None
    assert asymptotic_range(series, 3, 0.01) == 0.0
    assert asymptotic_range(series, 4, 0.01) == pytest.approx((3 - 2) / (9 / 4))
    # the floor replaces a mean near zero
    assert relative_range([-0.001, 0.001], 0.01) == pytest.approx(0.002 / 0.01)
    assert relative_range([0.999, 1.001], 0.01) == pytest.approx(0.002)
    # vectors: length of the component ranges over the length of the mean
    assert relative_range([(1.0, 0.0, 0.0), (1.0, 0.03, 0.04)], 0.1) == pytest.approx(0.05 / (1.0 + 0.02 ** 2 * 1.25) ** 0.5, rel=1e-3)
    # writeAndEnd writes the final row twice: it counts once
    assert unique_by_iteration(series + [(6, 2.0)]) == series
    assert asymptotic_range(series + [(6, 2.0)], 4, 0.01) == asymptotic_range(series, 4, 0.01)


def _criterion(window=50, tolerance=1e-3):
    return AsymptoticCriterion(quantity="Cd", window=window, tolerance=tolerance)


def test_synthetic_series_linear_drift_damped_oscillation_and_constant() -> None:
    """A linear drift never stops; a damped oscillation stops once its swing over the window has
    decayed below the tolerance (and not before); a constant stops at the first eligible
    iteration (the full window, or the minimum iterations)."""
    drift = [(i, 0.3 + 1e-5 * i) for i in range(1, 2001)]  # 0.05 % of the value per 50 iterations
    assert first_met_iteration(drift, _criterion(50, 1e-4)) is None
    assert first_met_iteration([(i, 0.3 + 1e-4 * i) for i in range(1, 2001)], _criterion()) is None
    damped = [(i, 0.3 + 0.05 * math.exp(-i / 60) * math.sin(2 * math.pi * i / 25)) for i in range(1, 2001)]
    stop = first_met_iteration(damped, _criterion())
    assert stop is not None
    # at the stop the swing over the last 50 is below 0.1 % of 0.3; one iteration earlier it was not
    window = [v for _, v in damped[stop - 50:stop]]
    assert (max(window) - min(window)) / 0.3 <= 1e-3
    before = [v for _, v in damped[stop - 51:stop - 1]]
    assert (max(before) - min(before)) / max(abs(sum(before) / 50), 0.01) > 1e-3
    # the envelope 0.05 e^(-i/60) must have fallen to about 0.3e-3 / 2: i ~ 60 ln(0.1 / 3e-4) = 350
    assert 300 < stop < 420
    constant = [(i, 0.25) for i in range(1, 200)]
    assert first_met_iteration(constant, _criterion()) == 50
    assert first_met_iteration(constant, _criterion(), min_iterations=120) == 120
    assert first_met_iteration(constant[:49], _criterion()) is None  # window never full


def test_the_real_cd_series_that_stopped_at_49_does_not_stop_early() -> None:
    """tests/data/stop_run: the old |x_n - mean of 20| <= 1e-3 stopped the coarse sphere at
    iteration 49 while Cd still drifted. The range criterion with the same window and tolerance
    does not stop there, and on the 300-iteration continuation of the same set-up
    (tests/data/breakdown_run, same mesh and inflow) the defaults (window 50, tolerance 1e-3) never
    stop: over its last 50 iterations Cd still spans 1.46 % of its mean."""
    tail = ForceCoeffsTail(DATA / "stop_run" / "coefficient.dat")
    tail.poll()
    cd = unique_by_iteration(tail.series["Cd"])
    assert cd[-1][0] == 49 and len(cd) == 49
    assert asymptotic_range(cd, 20, 0.01) == pytest.approx(0.298, abs=1e-3)  # a 30 % range at 49
    assert first_met_iteration(cd, _criterion(20, 1e-3)) is None
    tail = ForceCoeffsTail(DATA / "breakdown_run" / "postProcessing" / "forceCoeffs1" / "0" / "coefficient.dat")
    tail.poll()
    long = unique_by_iteration(tail.series["Cd"])
    # same run up to the reference area (planform 0.9977 m2 vs frontal 0.9953 m2... within 0.3 %)
    assert long[48][1] == pytest.approx(cd[48][1], rel=3e-3)
    assert first_met_iteration(long, _criterion()) is None
    assert asymptotic_range(long, 50, 0.01) == pytest.approx(0.01457, abs=1e-4)
    assert first_met_iteration(long, _criterion(20, 1e-3)) is None
    # looser settings stop later than 49, once the large swings have passed
    assert first_met_iteration(long, _criterion(50, 1e-2)) == 245
    assert first_met_iteration(long, _criterion(20, 2e-2)) == 144


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
    assert (p.value, p.satisfied, p.iteration, p.name) == (1e-4, True, 4, "c2_residual_p")
    assert (a.value, a.threshold, a.satisfied, a.iteration) == (0.0, 0.01, True, 4)
    assert criteria_met(stop, [u, p, a], 4) == ()  # "all": U is not met
    assert criteria_met(stop.model_copy(update={"combine": "any"}), [u, p, a], 4) == ("c2_residual_p", "c3_asymptotic_Cd")
    assert criteria_met(stop.model_copy(update={"combine": "any"}), [u, p, a], 5) == ()  # values of another iteration
    early = evaluate(stop.model_copy(update={"min_iterations": 10}), residuals, lambda q: cd.get(q, []))
    assert not early[1].satisfied and early[1].note == "from iteration 10"
    none = evaluate(stop, {}, lambda q: [])
    assert all(s.value is None and not s.satisfied for s in none)


# -- log event and end state ------------------------------------------------------------------------------


def test_criteria_met_is_parsed_from_the_real_log_and_classified_criteria_met() -> None:
    parser = parse_log_text((DATA / "stop_run" / "log.simpleFoam").read_text())
    assert parser.criteria_met == CriteriaMet(("c1_asymptotic_Cd",), 49.0)
    assert [e for e in parser.events if isinstance(e, CriteriaMet)] == [parser.criteria_met]
    assert parser.has_ended and parser.time_steps[-1].time == 49.0
    assert classify(0, False, parser) == CRITERIA_MET
    assert classify(0, True, parse_log_text("Time = 1\nEnd\n"), criteria_stop=True) == CRITERIA_MET


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
    # around zero the floor (0.01 for coefficients) is the scale: a small swing is not flagged,
    # a large one is (docs/QUESTIONS.md item 61)
    assert oscillation("Cl", _sine(200, 0.0, 4e-5, 20), 100, 0.01) is None  # 8e-5 / 0.01 = 0.8 %
    big = oscillation("Cl", _sine(200, 0.0, 0.05, 20), 100, 0.01)
    assert big is not None and big.amplitude == pytest.approx(0.1 / 0.01, rel=0.01)
    assert big.message().startswith("Cl oscillates with a range of 0.1 around a mean near zero")
    # a probe has no default floor: near zero it is not evaluated unless the criterion's floor is given
    assert oscillation("probe:w:p", _sine(200, 0.0, 0.05, 20), 100, 0.01) is None
    assert oscillation("probe:w:p", _sine(200, 0.0, 0.05, 20), 100, 0.01, floor=1.0) is not None
    assert oscillation("Cl", _sine(50, 0.5, 0.01, 20), 100, 0.01) is None  # window not full
    assert linear_change([0.0, 1.0, 2.0, 3.0]) == pytest.approx(3.0)


def test_oscillation_on_a_real_series() -> None:
    """tests/data/oscillation_run (172 real iterations on the coarse sphere, default window 100):
    over iterations 73-172 Cl swings between 0.038 and 0.092 around 0.061 (88 %) and Cd between
    0.161 and 0.180 around 0.169 (11 %), both without a trend: both are flagged. CmPitch (mean
    2.4e-4, range 1.23e-4) is judged against the 0.01 floor: 1.2 %, just above the 1 % threshold."""
    tail = ForceCoeffsTail(DATA / "oscillation_run" / "coefficient.dat")
    tail.poll()
    cl = oscillation("Cl", tail.series["Cl"], 100, 0.01)
    assert cl is not None and cl.amplitude == pytest.approx(0.8776, abs=1e-3) and cl.mean == pytest.approx(0.06135, abs=1e-4)
    cd = oscillation("Cd", tail.series["Cd"], 100, 0.01)
    assert cd is not None and cd.amplitude == pytest.approx(0.1104, abs=1e-3)
    assert cd.message().startswith("Cd oscillates by 11%")
    cm = oscillation("CmPitch", tail.series["CmPitch"], 100, 0.01)
    assert cm is not None and cm.amplitude == pytest.approx(0.0123, abs=1e-4)
    assert cm.message().startswith("Cm (pitch) oscillates with a range of 0.00012 around a mean near zero")
    assert oscillation("CmPitch", tail.series["CmPitch"], 100, 0.02) is None
    assert oscillation("Cd", tail.series["Cd"], 100, 0.2) is None  # an 11 % swing under a 20 % threshold


# -- real run ------------------------------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.long  # real run above 60 s (D-043)
def test_asymptotic_cd_criterion_stops_simplefoam_on_the_session_mesh(sphere_mesh, tmp_path: Path) -> None:
    """An asymptotic criterion on Cd (window 20, tolerance 2e-2, i.e. a 2 % range) is met from the
    live files and the app stops simpleFoam with the clean stop before the 250-iteration limit: a
    clean end (exit code 0, End, the stopping iteration written with U and p), state criteria met,
    no runTimeControl in controlDict, and the Python check on coefficient.dat finding no earlier
    iteration where the criterion held."""
    import shutil

    from vortexcfd.core.model import Inflow, Physics
    from vortexcfd.foam.case_writer import enable_clean_stop
    from vortexcfd.foam.dictfile import read_foam_file, write_foam_file
    from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files
    from vortexcfd.foam.postprocessing import FORCE_COEFFS, FORCE_COEFFS_FILE, output_file
    from vortexcfd.foam.solver_run import LOG_NAME, SolverRun

    case = tmp_path / "case"
    shutil.copytree(sphere_mesh.case_dir, case)
    criterion = AsymptoticCriterion(quantity="Cd", window=20, tolerance=2e-2)
    stop = StoppingCriteria(criteria=[criterion])
    inp = SolverCaseInput(Physics(), Inflow(), Solvers(iterations=250, write_interval=100, stopping=stop),
                          sphere_mesh.inputs.parts, sphere_mesh.inputs.parts_bounds, False)
    for rel, spec in enable_clean_stop(build_solver_files(inp)).items():
        write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    assert "runTimeControl1" not in read_foam_file(case / "system" / "controlDict")["functions"]
    run = SolverRun(case, timeout_s=280, stopping=stop)
    run.start()
    try:
        result = run.wait(290)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(30)
    assert result is not None and result.exit_code == 0, (case / LOG_NAME).read_text()[-1500:]
    assert result.state == CRITERIA_MET and result.criteria_met == ("c1_asymptotic_Cd",)
    met = result.met_iteration
    assert 20 <= met < 250 and result.iterations == met + 2  # the signal applies at the next increment
    for field in ("U", "p"):
        assert (case / str(result.iterations) / field).is_file()  # the clean stop wrote it
    assert "End" in (case / LOG_NAME).read_text()
    tail = ForceCoeffsTail(output_file(case, FORCE_COEFFS, FORCE_COEFFS_FILE))
    tail.poll()
    cd = unique_by_iteration(tail.series["Cd"])
    assert first_met_iteration(cd, criterion) == met
    window = [v for t, v in cd if met - 20 < t <= met]
    print(f"\nmet at iteration {met}, stopped at {result.iterations}: Cd {min(window):.6g}-{max(window):.6g} "
          f"over the last 20, range {asymptotic_range(cd[:met], 20, 0.01):.4g} <= 2e-2")


def test_the_real_asymptotic_stop_fixture() -> None:
    """tests/data/asymptotic_stop_run (the slow test above, saved): the app's criterion (Cd, window
    20, tolerance 2e-2) was met at iteration 144 (Cd 0.16856-0.17194 over iterations 125-144,
    relative range 1.97 %) and not before; the clean stop then ran and wrote iteration 146, End.
    No runTimeControl condition appears in the log."""
    tail = ForceCoeffsTail(DATA / "asymptotic_stop_run" / "coefficient.dat")
    tail.poll()
    cd = unique_by_iteration(tail.series["Cd"])
    criterion = AsymptoticCriterion(quantity="Cd", window=20, tolerance=2e-2)
    assert first_met_iteration(cd, criterion) == 144 and cd[-1][0] == 146
    assert asymptotic_range(cd[:144], 20, 0.01) == pytest.approx(0.01974, abs=1e-4)
    parser = parse_log_text((DATA / "asymptotic_stop_run" / "log.simpleFoam").read_text())
    assert parser.criteria_met is None and parser.has_ended and parser.time_steps[-1].time == 146.0
