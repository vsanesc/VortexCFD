"""The mean-stable stopping criterion and the windowed mean of the monitors and results (D-118), on
synthetic series and on the recorded body Cd histories of the Ahmed round 1 study."""

import csv
import math
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from vortexcfd.core.model import AsymptoticCriterion, MeanStableCriterion, Simulation, StoppingCriteria
from vortexcfd.foam.convergence import (
    criteria_met,
    describe,
    earliest_iteration,
    evaluate,
    first_met_iteration,
    is_native,
    mean_change,
    oscillation,
    short_label,
    window_stats,
)
from vortexcfd.foam.forces import ForceRow
from vortexcfd.gui.monitors import ReportSlots
from vortexcfd.gui.report_views import ForcesTable

DATA = Path(__file__).parent / "data" / "ahmed_round1_cd_body.csv"


def _round1() -> dict[str, list[tuple[float, float]]]:
    """The body Cd per iteration of the three round 1 levels (1500 iterations each)."""
    rows = [r for r in DATA.read_text(encoding="utf-8").splitlines() if not r.startswith("#")]
    reader = csv.DictReader(rows)
    out: dict[str, list] = {"coarse": [], "medium": [], "fine": []}
    for r in reader:
        for level in out:
            out[level].append((float(r["iteration"]), float(r[level])))
    return out


def _sine(n: int, mean: float, amp: float, period: float, drift: float = 0.0):
    return [(float(i + 1), mean + drift * i + amp * math.sin(2 * math.pi * i / period)) for i in range(n)]


def test_defaults_discriminator_and_app_side() -> None:
    c = MeanStableCriterion(quantity="Cd@body")
    assert (c.window, c.tolerance, c.effective_floor) == (500, 0.005, 0.01)
    stop = StoppingCriteria(criteria=[c])
    back = StoppingCriteria.model_validate(stop.model_dump())
    assert isinstance(back.criteria[0], MeanStableCriterion) and back == stop
    assert not is_native(stop)  # the app evaluates it and stops the solver cleanly (D-058)
    assert earliest_iteration(c, 0) == 1000 and earliest_iteration(c, 1200) == 1200
    assert short_label(c).endswith("mean stable")
    assert "mean of the last 500 - mean of the 500 before" in describe(c)
    with pytest.raises(ValueError):
        MeanStableCriterion(quantity="probe:p1:p")  # a probe needs its floor, as the asymptotic criterion
    sim = Simulation(name="s")
    sim.solvers.stopping = stop
    assert Simulation.model_validate(sim.model_dump()).solvers.stopping == stop


def test_synthetic_stationary_oscillation_stops_and_drift_does_not() -> None:
    c = MeanStableCriterion(quantity="Cd", window=100, tolerance=0.005)
    steady = _sine(400, 0.35, 0.02, 25)  # four whole periods per window: equal means
    assert first_met_iteration(steady, c) == 200
    assert first_met_iteration(_sine(1000, 0.35, 0.02, 25, drift=1e-4), c) is None  # 2.9 % per window
    # the range-based criterion never stops the same oscillation
    assert first_met_iteration(steady, AsymptoticCriterion(quantity="Cd", window=100, tolerance=0.005)) is None
    assert mean_change([v for _, v in steady][:150], 100, 0.01) is None  # fewer than 2 W values
    assert mean_change([1.0] * 100 + [1.01] * 100, 100, 0.01) == pytest.approx(0.01 / 1.01)


def test_round1_histories_stop_at_about_1000_iterations_with_the_1000_iteration_means() -> None:
    """Where the defaults (W 500, tol 0.5 %) would have stopped the round 1 levels, and the mean they
    report: within 0.25 % of the means over iterations 501-1500 judged in RESULT.md."""
    c = MeanStableCriterion(quantity="Cd@body")
    expected = {"coarse": (1002, 0.3416, 0.3409), "medium": (1003, 0.3464, 0.3468), "fine": (1036, 0.3250, 0.3250)}
    for level, series in _round1().items():
        assert len(series) == 1500
        stop, mean, judged = expected[level]
        assert first_met_iteration(series, c) == stop, level
        reported = sum(v for t, v in series if stop - 500 < t <= stop) / 500
        assert reported == pytest.approx(mean, abs=5e-5), level
        assert sum(v for _, v in series[500:]) / 1000 == pytest.approx(judged, abs=5e-5)
        assert abs(reported / judged - 1) < 0.0025
        # evaluate() at that iteration: met, value below the tolerance
        stopping = StoppingCriteria(criteria=[c])
        status = evaluate(stopping, {}, lambda _q, s=series, n=stop: [r for r in s if r[0] <= n])[0]
        assert status.satisfied and status.value <= 0.005 and status.iteration == stop
        assert criteria_met(stopping, [status], stop) == (status.name,)
        before = evaluate(stopping, {}, lambda _q, s=series, n=stop - 1: [r for r in s if r[0] <= n])[0]
        assert not before.satisfied


def test_shorter_windows_stop_on_the_phase_of_the_oscillation() -> None:
    """Why W = 500 (about three periods of 167 iterations): the 100-iteration mean of the coarse level
    still swings by 2.6 % of the mean over iterations 400-1500, the 500-iteration mean by 0.6 %."""
    coarse = [v for _, v in _round1()["coarse"]]
    ref = sum(coarse[500:]) / 1000

    def swing(w: int) -> float:
        means = [sum(coarse[e - w:e]) / w for e in range(300 + w, 1501)]
        return (max(means) - min(means)) / ref

    assert swing(100) > 0.025 and swing(500) < 0.0065


def test_window_stats_and_the_oscillation_hint() -> None:
    steady = _sine(600, 0.35, 0.02, 25)
    stats = window_stats(steady, 500, quantity="Cd")
    assert stats.n == 500 and stats.mean == pytest.approx(0.35, abs=1e-4)
    assert stats.amplitude == pytest.approx(0.04 / 0.35, rel=1e-2)
    assert stats.text().startswith("mean 0.35 ± 5.7%")
    assert window_stats(steady[:1], 500) is None
    osc = oscillation("Cd", steady, 100, 0.01)
    assert "mean stable" in osc.message(suggest_mean_stable=True)
    assert "mean stable" not in osc.message()


def test_report_slots_show_the_windowed_mean(qtbot: QtBot) -> None:
    slots = ReportSlots()
    qtbot.addWidget(slots)
    slots.set_assignments(["Cd", None, None, None][:len(slots.assignments)] + [None] * (len(slots.assignments) - 4))
    series = _sine(600, 0.35, 0.02, 25)
    slots.window_of = lambda _r: 500
    slots.set_series(lambda r: series if r == "Cd" else [])
    assert slots.values[1].text() == f"{series[-1][1]:.4g}"
    assert slots.means[1].text().startswith("mean 0.35 ±") and "(500 it.)" in slots.means[1].text()
    assert slots.means[2].text() == ""


def test_forces_table_shows_the_windowed_means(qtbot: QtBot) -> None:
    table = ForcesTable()
    qtbot.addWidget(table)
    rows = [ForceRow("All walls", 0.36, 0.3, 0.06, 0.3, 0.3, 0.0, None, None),
            ForceRow("body", 0.34, 0.29, 0.05, 0.3, 0.3, 0.0, None, None)]
    stats = window_stats(_sine(600, 0.35, 0.02, 25), 500, quantity="Cd")
    table.set_rows(rows, lambda base, column: stats if (base, column) == ("Cd", "body") else None)
    assert table.text("Cd_mean", "body").startswith("0.35 ±")
    assert table.text("Cd_mean", "All walls") == "—"
    table.set_rows(rows)  # without windowed values: the latest values only
    assert ("Cd_mean", "body") not in table.cells
