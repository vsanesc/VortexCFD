"""The convergence panel (D-178): "Satisfied now" says whether each criterion holds at the last iteration (not whether
it stopped the run), with an incomplete window's progress; the soft warning of a force coefficient still changing
while the residual criteria hold; the mass imbalance below the postProcessing files' resolution."""

import math
import re
import shutil
from pathlib import Path

import pytest

from tests.test_solver_gui import fake_mesh, make_window  # noqa: F401 (fixture)
from vortexcfd.core.model import AsymptoticCriterion, MeanStableCriterion, ResidualCriterion, StoppingCriteria
from vortexcfd.foam.convergence import DRIFT_TOLERANCE, DRIFT_WINDOW, evaluate, still_changing
from vortexcfd.foam.forces import imbalance_resolution, imbalance_text
from vortexcfd.foam.logparse import TimeStep
from vortexcfd.foam.postprocessing import ReportMonitor
from vortexcfd.foam.solver_run import stage2_criteria
from vortexcfd.gui.monitors import SATISFIED_TIP, ConvergencePanel, drift_warning, satisfied_text

DATA = Path(__file__).parent / "data"
RESIDUALS = [ResidualCriterion(field="p", threshold=1e-4), ResidualCriterion(field="U", threshold=1e-5),
             ResidualCriterion(field="k", threshold=1e-5), ResidualCriterion(field="omega", threshold=1e-5)]
# The owner's run (2D airfoil, two stages switched at iteration 1502, minimum iterations 2000), stopped by hand at
# iteration 2831: the initial residuals of its last iteration.
OWNER = {"Ux": [(2831, 1.49052e-08)], "Uz": [(2831, 6.87866e-08)], "p": [(2831, 1.17191e-07)],
         "omega": [(2831, 9.92751e-09)], "k": [(2831, 1.96448e-08)]}


def _no_series(_q):
    return []


# -- a) "Satisfied now" ---------------------------------------------------------------------------------------------


def test_the_owners_stopped_run_holds_every_residual_criterion() -> None:
    """What the table computed before: holds AND may stop the run there. In stage 2 the earliest iteration is the
    switch plus the run's minimum (1502 + 2000 = 3502), so at 2831 every row said "no"."""
    run = StoppingCriteria(criteria=RESIDUALS, min_iterations=2000)
    statuses = evaluate(stage2_criteria(run, 1502), OWNER, _no_series)
    assert [s.value for s in statuses] == pytest.approx([1.17191e-07, 6.87866e-08, 1.96448e-08, 9.92751e-09])
    assert all(s.holds for s in statuses)
    assert not any(s.satisfied for s in statuses) and {s.earliest for s in statuses} == {3502}
    text, tip = satisfied_text(statuses[0])
    assert text == "yes (stops from 3,502)" and "only from iteration 3,502" in tip
    plain = evaluate(run, OWNER, _no_series)  # stage 1, past the minimum: it holds and may stop the run
    assert all(s.holds and s.satisfied for s in plain)
    assert [satisfied_text(s)[0] for s in plain] == ["yes"] * 4


def test_residual_criteria() -> None:
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1e-4),
                                      ResidualCriterion(field="U", threshold=1e-5)])
    p, u = evaluate(stop, {"p": [(10, 5e-5)], "Ux": [(10, 2e-6)], "Uy": [(10, 3e-5)]}, _no_series)
    assert p.holds and satisfied_text(p)[0] == "yes"
    assert not u.holds and satisfied_text(u)[0] == "no"  # U is the largest component
    none = evaluate(stop, {}, _no_series)
    assert [satisfied_text(s)[0] for s in none] == ["not yet", "not yet"]


def test_asymptotic_criterion_window_progress_and_holding() -> None:
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=50, tolerance=1e-3)])
    short = {"Cd": [(i, 0.3) for i in range(1, 41)]}
    (status,) = evaluate(stop, {}, lambda q: short.get(q, []))
    assert status.value is None and status.progress == (40, 50) and not status.holds
    assert satisfied_text(status)[0] == "not yet: 40 of 50 iterations"
    steady = {"Cd": [(i, 0.3) for i in range(1, 61)]}
    (status,) = evaluate(stop, {}, lambda q: steady.get(q, []))
    assert status.holds and status.satisfied and satisfied_text(status)[0] == "yes"
    moving = {"Cd": [(i, 0.3 + 0.001 * i) for i in range(1, 61)]}
    (status,) = evaluate(stop, {}, lambda q: moving.get(q, []))
    assert status.value > 1e-3 and not status.holds and satisfied_text(status)[0] == "no"


def test_mean_stable_criterion_needs_two_windows() -> None:
    stop = StoppingCriteria(criteria=[MeanStableCriterion(quantity="Cl", window=30, tolerance=5e-3)])
    short = {"Cl": [(i, 1.0 + 0.05 * math.sin(i)) for i in range(1, 51)]}
    (status,) = evaluate(stop, {}, lambda q: short.get(q, []))
    assert status.progress == (50, 60) and satisfied_text(status)[0] == "not yet: 50 of 60 iterations"
    full = {"Cl": [(i, 1.0 + 0.05 * math.sin(i)) for i in range(1, 121)]}
    (status,) = evaluate(stop, {}, lambda q: full.get(q, []))
    assert status.holds and satisfied_text(status)[0] == "yes"


def test_the_minimum_iterations_say_from_when_it_may_stop() -> None:
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1e-4)], min_iterations=500)
    (status,) = evaluate(stop, {"p": [(120, 1e-6)]}, _no_series)
    assert status.holds and not status.satisfied and satisfied_text(status)[0] == "yes (stops from 500)"


def test_the_column_header_says_what_it_means(qtbot) -> None:
    panel = ConvergencePanel()
    qtbot.addWidget(panel)
    head = panel.grid.itemAtPosition(0, 3).widget()
    assert head.text() == "Satisfied now" and head.toolTip() == SATISFIED_TIP
    assert "at the last iteration" in SATISFIED_TIP and "stops the run only from" in SATISFIED_TIP


def _steps(residuals: dict, last: int) -> list[TimeStep]:
    """One TimeStep per iteration up to ``last`` with the given initial residuals."""
    rows = [(name, value, value / 10, 1) for name, value in residuals.items()]
    return [TimeStep(float(i), residuals=rows) for i in range(1, last + 1)]


def _case(tmp_path: Path, cl) -> Path:
    """A case with breakdown_run's controlDict and a forceCoeffs1 file whose Cl is ``cl(i)``."""
    case = tmp_path / "case"
    shutil.copytree(DATA / "breakdown_run" / "system", case / "system")
    header = (DATA / "breakdown_run" / "postProcessing" / "forceCoeffs1" / "0" / "coefficient.dat").read_text()
    header = "".join(line + "\n" for line in header.splitlines() if line.startswith("#"))
    rows = "".join(f"{i}\t0.3\t0.15\t0.15\t{cl(i):.6e}\t0\t0\t0.01\t0\t0\t0\t0\t0\n" for i in range(1, 201))
    folder = case / "postProcessing" / "forceCoeffs1" / "0"
    folder.mkdir(parents=True)
    (folder / "coefficient.dat").write_text(header + rows)
    return case


def test_a_stopped_run_whose_values_are_below_the_thresholds_says_yes(make_window, tmp_path: Path) -> None:
    w = make_window()
    stop = StoppingCriteria(criteria=RESIDUALS)
    case = _case(tmp_path, lambda i: 1.0)
    w.monitors.load_run(case, _steps({"Ux": 1.5e-8, "Uz": 6.9e-8, "p": 1.2e-7, "omega": 9.9e-9, "k": 2e-8}, 200),
                        ("stopped", (), 200), stop)
    rows = w.monitors.convergence.statuses_text
    assert [r[3] for r in rows] == ["yes", "yes", "yes", "yes"]
    assert w.monitors.convergence.rows[0][3].property("ok") == "true"


# -- b) residuals met, a force coefficient still changing -----------------------------------------------------------


def test_still_changing_needs_every_residual_criterion_to_hold() -> None:
    stop = StoppingCriteria(criteria=RESIDUALS[:2])
    drifting = {"Cl": [(i, 1.0 + 1e-3 * i) for i in range(1, 201)], "Cd": [(i, 0.3) for i in range(1, 201)]}
    held = {"p": [(200, 1e-6)], "Ux": [(200, 1e-7)]}
    statuses = evaluate(stop, held, lambda q: drifting.get(q, []))
    assert still_changing(stop, statuses, ["Cd", "Cl"], lambda q: drifting.get(q, [])) == ["Cl"]
    assert DRIFT_WINDOW == 50 and DRIFT_TOLERANCE == pytest.approx(1e-3)
    failing = evaluate(stop, {"p": [(200, 1e-3)], "Ux": [(200, 1e-7)]}, lambda q: drifting.get(q, []))
    assert still_changing(stop, failing, ["Cl"], lambda q: drifting.get(q, [])) == []  # p does not hold
    watched = stop.model_copy(update={"criteria": [*stop.criteria, AsymptoticCriterion(quantity="Cl")]})
    statuses = evaluate(watched, held, lambda q: drifting.get(q, []))
    assert still_changing(watched, statuses, ["Cl"], lambda q: drifting.get(q, [])) == []  # already watched
    only_windowed = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd")])
    statuses = evaluate(only_windowed, held, lambda q: drifting.get(q, []))
    assert still_changing(only_windowed, statuses, ["Cl"], lambda q: drifting.get(q, [])) == []  # no residuals
    part = {"Cl@wing": drifting["Cl"]}
    statuses = evaluate(stop, held, lambda q: part.get(q, []))
    assert still_changing(stop, statuses, ["Cl@wing", "probe:wake:p"], lambda q: part.get(q, [])) == ["Cl@wing"]


@pytest.mark.parametrize("state", ["criteria_met", "stopped"])
def test_the_soft_warning_in_the_panel(make_window, tmp_path: Path, state: str) -> None:
    """Also when the residual criteria alone stopped the run."""
    w = make_window()
    w.monitors.set_assignments(["Cd", "Cl", None, None][:len(w.monitors.kpis.assignments)])
    stop = StoppingCriteria(criteria=RESIDUALS)
    steps = _steps({"Ux": 1e-8, "Uz": 1e-8, "p": 1e-7, "omega": 1e-8, "k": 1e-8}, 200)
    w.monitors.load_run(_case(tmp_path, lambda i: 1.0 + 1e-3 * i), steps, (state, (), 200), stop)
    texts = [label.text() for label in w.monitors.convergence.warnings]
    assert drift_warning("Cl") in texts
    assert drift_warning("Cl") == ("Residuals met, but Cl is still changing: add an asymptotic or mean-stable "
                                   "criterion on it")
    assert not any("Cd" in t for t in texts)  # Cd is constant


def test_no_soft_warning_for_a_settled_coefficient(make_window, tmp_path: Path) -> None:
    w = make_window()
    w.monitors.set_assignments(["Cd", "Cl", None, None][:len(w.monitors.kpis.assignments)])
    steps = _steps({"Ux": 1e-8, "Uz": 1e-8, "p": 1e-7, "omega": 1e-8, "k": 1e-8}, 200)
    w.monitors.load_run(_case(tmp_path, lambda i: 1.0), steps, ("criteria_met", (), 200),
                        StoppingCriteria(criteria=RESIDUALS))
    assert not any("still changing" in label.text() for label in w.monitors.convergence.warnings)


# -- c) the mass imbalance ------------------------------------------------------------------------------------------


def test_the_recorded_mass_imbalance_is_below_the_files_resolution() -> None:
    """The owner's run (tests/data/mass_flow_run): both fluxes written as 2.114049e-01 (writePrecision 6) cancel
    exactly; the parse, the units (sum(phi), m3/s) and the % of the inlet flux are right. The log's continuity error
    gives the true imbalance, about 1e-8 %, far below what the files resolve (4.7e-5 %)."""
    case = DATA / "mass_flow_run"
    monitor = ReportMonitor(case)
    monitor.poll()
    inlet, outlet, pct = monitor.mass_balance()
    assert (inlet, outlet, pct) == (-0.2114049, 0.2114049, 0.0)
    assert {v for _t, v in monitor.mass_series()} == {0.0} and len(monitor.mass_series()) == 120
    assert monitor.write_precision() == 6
    resolution = monitor.mass_resolution()
    assert resolution == pytest.approx(100 * 1e-7 / 0.2114049) and resolution == pytest.approx(4.73e-5, rel=1e-2)
    log = (case / "log.simpleFoam").read_text()
    global_error = float(re.search(r"global = ([-0-9.e+]+)", log).group(1))
    volume = float(re.search(r"Total volume = ([0-9.e+-]+)\.", (case / "logs" / "log.checkMesh").read_text()).group(1))
    true_pct = 100 * global_error * volume / abs(inlet)  # sum(phi) over the boundary / |inlet flux|
    assert true_pct == pytest.approx(1.016e-8, rel=1e-2) and true_pct < resolution
    assert imbalance_text(pct, resolution) == "< 4.7e-05"


def test_imbalance_text_and_resolution() -> None:
    assert imbalance_text(0.0, None) == "0"
    assert imbalance_text(1.2345e-3, 4.7e-5) == "0.00123"  # above the resolution: as before
    assert imbalance_text(2.5e-6, 4.7e-5) == "< 4.7e-05"
    assert imbalance_resolution([-0.2114049, 0.2114049], -0.2114049, precision=8) == pytest.approx(4.73e-7, rel=1e-2)
    assert imbalance_resolution([0.0, 1.0], 0.0) is None


def test_the_monitors_show_the_imbalance_in_scientific_notation(make_window) -> None:
    w = make_window()
    w.project.update_reports(slots=["mass_imbalance", None, None])
    case = w.project.path.parent / "case"
    for child in ("postProcessing", "system"):
        shutil.copytree(DATA / "mass_flow_run" / child, case / child, dirs_exist_ok=True)
    w.monitors.load_run(case, [], ("iteration_limit", (), 2000))
    assert w.monitors.kpis.values[1].text() == "< 4.7e-05"
    assert w.monitors.kpis.means[1].text() == "mean < 4.7e-05 (100 it.)"
