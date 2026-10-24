"""Stopping Criteria node, convergence banner, per-criterion state and oscillation warning (D-058,
D-059). The solver is a FakeRunner playing real-format log lines."""

import shutil
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner, iteration
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from vortexcfd.core.model import AsymptoticCriterion, ResidualCriterion, StoppingCriteria
from vortexcfd.foam.run_record import read_run_record
from vortexcfd.gui.monitors import BANNER_LIMIT, BANNER_NO_RUN, BANNER_RUNNING, BANNER_STOPPED

DATA = Path(__file__).parent / "data"


def _select(w, kind: str) -> None:
    w.tree.setCurrentItem(w._items[(kind, None)])


def _stop_lines(*names: str) -> list[str]:
    """runTimeControl's lines when its conditions are met (format of tests/data/stop_run)."""
    lines = ["runTimeControl runTimeControl1 output:\n"]
    lines += [f"    equationInitialResidual: {n} condition satisfied\n" for n in names]
    return lines + ["    Stopping calculation\n", "    Writing fields\n", "\n", "End\n"]


# -- editor -------------------------------------------------------------------------------------------------


def test_node_shows_the_default_criteria_and_edits_commit_and_revert(make_window) -> None:
    w = make_window()
    _select(w, "stopping")
    p = w.properties
    assert p._rows["stop_combine"].isVisible() and not p.info_label.isVisible()
    assert p.stop_combine.currentData() == "all" and p.stop_min.value() == 0 and p.stop_max.value() == 1000
    assert p.stop_osc_threshold.value() == pytest.approx(1.0) and p.stop_osc_window.value() == 100
    rows = p.criterion_widgets
    assert [r["field"].currentText() for r in rows] == ["p", "U", "k", "omega"]
    assert rows[0]["threshold"].text() == "0.0001" and rows[0]["earliest"].text() == "iteration 3"
    rows[1]["threshold"].setText("2e-6")
    rows[1]["threshold"].editingFinished.emit()
    assert w.project.sim.solvers.stopping.criteria[1].threshold == pytest.approx(2e-6)
    assert w.project.undo_label == "Edit solver (stopping)"
    p.criterion_widgets[2]["threshold"].setText("0")  # invalid: reverted with a message
    p.criterion_widgets[2]["threshold"].editingFinished.emit()
    assert w.project.sim.solvers.stopping.criteria[2].threshold == pytest.approx(1e-5)
    assert "threshold" in w.statusBar().currentMessage()
    assert p.criterion_widgets[2]["threshold"].text() == "1e-05"
    p.stop_max.setValue(400)
    p.stop_max.editingFinished.emit()
    assert w.project.sim.solvers.iterations == 400  # the iteration limit is Solvers.iterations
    p.stop_combine.setCurrentIndex(p.stop_combine.findData("any"))
    assert w.project.sim.solvers.stopping.combine == "any"
    p.stop_min.setValue(60)
    p.stop_min.editingFinished.emit()
    assert w.project.sim.solvers.stopping.min_iterations == 60
    assert p.criterion_widgets[0]["earliest"].text() == "iteration 60"
    p.stop_osc_threshold.setValue(2.5)
    p.stop_osc_threshold.editingFinished.emit()
    assert w.project.sim.solvers.stopping.oscillation_threshold == pytest.approx(0.025)


def test_add_edit_and_remove_criteria(make_window) -> None:
    w = make_window()
    _select(w, "stopping")
    p = w.properties
    p.stop_add_asymptotic.click()
    stop = w.project.sim.solvers.stopping
    assert stop.criteria[-1] == AsymptoticCriterion(quantity="Cd", window=50, tolerance=1e-3)
    row = p.criterion_widgets[-1]
    assert row["quantity"].currentText() == "Cd" and row["window"].value() == 50
    assert row["floor"].text() == "0.01" and row["earliest"].text() == "iteration 50"
    row["quantity"].setCurrentIndex(2)  # Cm (pitch)
    assert w.project.sim.solvers.stopping.criteria[-1].quantity == "CmPitch"
    row = p.criterion_widgets[-1]
    row["window"].setValue(25)
    row["window"].editingFinished.emit()
    p.criterion_widgets[-1]["tolerance"].setText("5e-4")
    p.criterion_widgets[-1]["tolerance"].editingFinished.emit()
    assert w.project.sim.solvers.stopping.criteria[-1] == AsymptoticCriterion(quantity="CmPitch", window=25,
                                                                               tolerance=5e-4)
    p.criterion_widgets[-1]["floor"].setText("0.05")
    p.criterion_widgets[-1]["floor"].editingFinished.emit()
    assert w.project.sim.solvers.stopping.criteria[-1].floor == pytest.approx(0.05)
    for _ in range(4):  # remove the four residual criteria
        p.criterion_widgets[0]["remove"].click()
    assert [c.kind for c in w.project.sim.solvers.stopping.criteria] == ["asymptotic"]
    p.criterion_widgets[0]["remove"].click()
    assert w.project.sim.solvers.stopping.criteria == []
    assert p.stop_empty.isVisible() and p.stop_empty.text() == "No criteria: the run stops at the iteration limit"
    p.stop_add_residual.click()
    assert w.project.sim.solvers.stopping.criteria == [ResidualCriterion(field="p", threshold=1e-4)]
    p.criterion_widgets[0]["field"].setCurrentText("omega")
    assert w.project.sim.solvers.stopping.criteria[0].field == "omega"
    w.project.undo()
    assert w.project.sim.solvers.stopping.criteria[0].field == "p"
    assert p.criterion_widgets[0]["field"].currentText() == "p"


# -- banner and per-criterion state --------------------------------------------------------------------------


def test_banner_states_which_criterion_stopped_the_run(make_window, qtbot: QtBot) -> None:
    """With an asymptotic criterion the app evaluates every criterion ("any" here): the p residual
    met at iteration 3 makes it stop the solver cleanly; the solver writes iteration 4."""
    w = make_window()
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1e-3),
                                      AsymptoticCriterion(quantity="Cd", window=20, tolerance=1e-3)],
                            combine="any")
    w.project.update_solver(stopping=stop.model_dump())
    box = w.monitors.convergence
    assert box.isVisible() and box.banner.text() == BANNER_NO_RUN
    runner = use_runner(w, FakeRunner(iteration(1) + iteration(2), hold=True,
                                      stop_lines=iteration(4)[1:] + ["End\n"]))
    w.run_solver()
    qtbot.waitUntil(lambda: len(w.monitors.history.series.get("p", [])) == 2, timeout=20000)
    w.monitors.refresh()
    assert box.banner.text() == BANNER_RUNNING
    # p residual 0.1 against 1e-3; Cd not written: no value yet
    assert box.statuses_text == [("p residual", "0.1", "0.001", "no"), ("Cd asymptotic", "—", "0.001", "no")]
    assert box.rows[1][0].toolTip() == ("Cd: (max - min) / max(|mean|, 0.01) over the last 20 <= 0.001 "
                                        "(from iteration 20)")
    assert box.rows[0][3].toolTip() == "from iteration 3"
    assert not runner.stop_requested
    runner.push(iteration(3, p=1e-4) + ["Time = 4\n"])  # step 3 completes with the next Time line
    wait_done(qtbot, w)
    assert runner.stop_requested  # the app stopped it (clean stop)
    record = w.run_record
    assert record.state == "criteria_met" and record.stopped_by == ("p initial residual < 0.001",)
    assert record.met_iteration == 3 and record.iterations == 4
    assert record.label == "Criteria met: p residual"
    assert record.criteria == ("p initial residual < 0.001",
                               "Cd: (max - min) / max(|mean|, 0.01) over the last 20 <= 0.001")
    assert box.banner.text() == "Criteria met at iteration 3: p initial residual < 0.001"
    assert box.banner.property("ok") == "true"
    message = w.statusBar().currentMessage()
    assert message.startswith("Solver: Criteria met: p residual after 4 iterations")
    assert "p initial residual < 0.001 at iteration 3" in message
    assert read_run_record(w.project.path.parent / "case") == record
    # reopening the project shows the same banner from the record
    w._load_run_record(w.project)
    assert box.banner.text() == "Criteria met at iteration 3: p initial residual < 0.001"


def test_residual_only_criteria_are_stopped_by_runtimecontrol(make_window, qtbot: QtBot) -> None:
    """Residual criteria only: OpenFOAM's runTimeControl stops the run (its log lines), the app
    does not stop it."""
    w = make_window()
    stop = StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1e-3)])
    w.project.update_solver(stopping=stop.model_dump())
    runner = use_runner(w, FakeRunner(iteration(1) + iteration(2) + iteration(3, p=1e-4) + _stop_lines("c1_residual_p")))
    w.run_solver()
    wait_done(qtbot, w)
    assert not runner.stop_requested
    record = w.run_record
    assert record.state == "criteria_met" and record.met_iteration == 3 and record.iterations == 3
    assert record.stopped_by == ("p initial residual < 0.001",) and record.label == "Criteria met: p residual"
    assert w.monitors.convergence.banner.text() == "Criteria met at iteration 3: p initial residual < 0.001"


def test_banner_iteration_limit_stopped_and_no_criteria(make_window, qtbot: QtBot) -> None:
    w = make_window()
    box = w.monitors.convergence
    use_runner(w, FakeRunner(iteration(1) + iteration(2) + ["End\n"]))
    w.run_solver()
    wait_done(qtbot, w)
    assert w.run_record.state == "iteration_limit"
    assert box.banner.text() == BANNER_LIMIT == "Iteration limit reached without meeting the criteria"
    assert box.banner.property("warn") == "true"
    assert "without meeting the stopping criteria" in w.statusBar().currentMessage()
    runner = use_runner(w, FakeRunner(iteration(1), hold=True, stop_lines=iteration(2) + ["End\n"]))
    w.run_solver()
    qtbot.waitUntil(lambda: bool(w.monitors.history.series.get("p")), timeout=20000)
    w.run_solver()  # Stop
    wait_done(qtbot, w)
    assert runner.stop_requested and box.banner.text() == BANNER_STOPPED
    # The project's criteria removed after the run: the run's stay, labelled as the last run's, with the project's
    # (none now) said apart (D-165)
    w.project.update_solver(stopping=StoppingCriteria(criteria=[]).model_dump())
    assert box.isVisible() and box.banner.text() == BANNER_STOPPED
    assert box.caption.text() == "Criteria of the last run"
    assert [row[0] for row in box.statuses_text] == ["p residual", "U residual", "k residual", "omega residual"]
    assert box.note.text() == ("The project's stopping criteria have changed since this run: now none. They apply to "
                               "the next run.")
    w.monitors.clear()  # no run shown and no criteria: nothing to show
    assert not box.banner.isVisible() and not box.isVisible()


def test_oscillation_warning_from_a_real_series(make_window) -> None:
    """tests/data/oscillation_run's coefficient.dat in a finished run: Cl, assigned to a slot,
    swings by 88 % over the last 100 iterations, and the warning names it."""
    w = make_window()
    case = w.project.path.parent / "case"
    target = case / "postProcessing" / "forceCoeffs1" / "0"
    target.mkdir(parents=True)
    shutil.copy(DATA / "oscillation_run" / "coefficient.dat", target)
    w.project.update_reports(slots=["Cl", None, None])
    w.monitors.load_run(case, [], ("iteration_limit", (), 172))
    texts = [label.text() for label in w.monitors.convergence.warnings]
    assert texts == ["Cl oscillates by 88% - the flow may be unsteady; a steady solution may not exist. If its mean "
                     "is steady, stop on it with a \"mean stable\" criterion on Cl"]
    assert w.monitors.convergence.warnings[0].property("warn") == "true"
    w.project.update_solver(stopping=StoppingCriteria(criteria=[], oscillation_threshold=0.95).model_dump())
    assert w.monitors.convergence.warnings == [] and not w.monitors.convergence.isVisible()
