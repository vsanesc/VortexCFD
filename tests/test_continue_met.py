"""Continue Solver after "Criteria met" (D-176), with fake runners: the dialog asks how many more iterations and offers
the criteria's values; the changes are one undoable edit saved in the project, and the run continues as in D-171."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner, iteration
from tests.test_continue import _write_time
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from tests.test_stopping_gui import _stop_lines
from vortexcfd.core.model import AsymptoticCriterion, ResidualCriterion, StoppingCriteria
from vortexcfd.core.project import Project
from vortexcfd.foam import convergence
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.logparse import parse_log_text
from vortexcfd.foam.run_record import read_run_record
from vortexcfd.gui.continue_dialog import ContinueMetDialog

CRITERIA = [ResidualCriterion(field="p", threshold=1e-4), ResidualCriterion(field="U", threshold=1e-5)]


def _met_at(w, qtbot: QtBot, last: int = 4) -> Path:
    """A first run whose residual criteria (runTimeControl) were met at iteration ``last``, its time written."""
    case = w.project.path.parent / "case"
    w.project.update_solver(stopping=StoppingCriteria(criteria=CRITERIA).model_dump(), iterations=100)
    names = [convergence.condition_name(i, c) for i, c in enumerate(CRITERIA)]
    use_runner(w, FakeRunner([line for n in range(1, last + 1) for line in iteration(n)] + _stop_lines(*names)))
    w.run_solver()
    wait_done(qtbot, w)
    assert w.run_record.state == "criteria_met" and w.run_record.iterations == last
    _write_time(case, last)
    w._update_run_button()
    return case


def test_criteria_met_offers_continue(make_window, qtbot: QtBot) -> None:
    w = make_window()
    _met_at(w, qtbot)
    assert w.solver_mode() == "continue"
    button = w.top_bar.run_button
    assert button.text() == "Continue Solver" and button.isEnabled()
    assert "its stopping criteria were met" in button.toolTip() and "tighten" in button.toolTip()
    assert w.act_clear_solution.isEnabled()  # Clear Solution still starts over


def test_cancelled_dialog_changes_nothing(make_window, qtbot: QtBot) -> None:
    w = make_window()
    _met_at(w, qtbot)
    before = w.project.sim.model_copy(deep=True)
    w.dialogs.continue_met = None
    w.run_solver()
    assert len(w.dialogs.continue_met_asked) == 1 and not w.solver_worker.is_running()
    latest, limit, stopping, met = w.dialogs.continue_met_asked[0]
    assert (latest, limit, met) == (4, 100, w.run_record.met_iteration) and stopping.criteria == CRITERIA
    assert w.dialogs.more_iterations_asked == []  # the one dialog asks both
    assert w.project.sim == before


def test_tightened_criteria_are_saved_and_the_run_continues(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = _met_at(w, qtbot)
    w.dialogs.continue_met = (6, {0: 1e-6})  # 6 more iterations, p's threshold tightened
    runner = use_runner(w, FakeRunner([line for n in range(5, 11) for line in iteration(n)] + ["End\n"]))
    w.run_solver()
    wait_done(qtbot, w)
    sim = w.project.sim
    assert sim.solvers.iterations == 10  # the latest iteration plus the more iterations: the total
    assert sim.solvers.stopping.criteria[0].threshold == pytest.approx(1e-6)
    assert sim.solvers.stopping.criteria[1].threshold == pytest.approx(1e-5)  # unchanged
    saved = Project.open(w.project.path).sim  # saved before the run (D-165)
    assert saved.solvers.stopping == sim.solvers.stopping and saved.solvers.iterations == 10
    assert w.project.undo_label == "Edit solver (iterations, stopping)"  # one undoable edit
    assert w.dialogs.choices_asked == []  # other criteria are not a changed set-up
    assert runner.append  # continued as in D-171: the log goes on
    control = read_foam_file(case / "system" / "controlDict")
    assert control["startFrom"] == "latestTime" and control["endTime"] == 10
    conditions = control["functions"]["runTimeControl1"]["conditions"]
    assert sorted(c["value"] for c in conditions.values()) == pytest.approx([1e-6, 1e-5])
    assert (case / "4" / "U").is_file()
    steps = [s.time for s in parse_log_text((case / "log.simpleFoam").read_text()).time_steps]
    assert steps == list(range(1, 11))
    record = w.run_record
    assert record.state == "iteration_limit" and record.iterations == 10
    assert [(s["first"], s["last"], s["state"]) for s in record.segments] == [(1, 4, "criteria_met"),
                                                                             (5, 10, "iteration_limit")]
    assert record.segments[1]["continued_from"] == 4 and record.segments[1]["settings_changed"] is False
    assert record.stopping["criteria"][0]["threshold"] == pytest.approx(1e-6)  # the run's criteria
    assert read_run_record(case) == record
    w.project.undo()
    assert w.project.sim.solvers.iterations == 100 and w.project.sim.solvers.stopping.criteria == CRITERIA


def test_unchanged_criteria_only_extend_the_limit(make_window, qtbot: QtBot) -> None:
    w = make_window()
    _met_at(w, qtbot)
    w.dialogs.continue_met = (2, {})
    use_runner(w, FakeRunner(iteration(5) + iteration(6) + ["End\n"]))
    w.run_solver()
    wait_done(qtbot, w)
    assert w.project.sim.solvers.iterations == 6 and w.project.sim.solvers.stopping.criteria == CRITERIA
    assert w.project.undo_label == "Edit solver (iterations, stopping)"
    assert [(s["first"], s["last"]) for s in w.run_record.segments] == [(1, 4), (5, 6)]


def test_without_a_written_time_it_runs_from_the_start(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = _met_at(w, qtbot)
    for folder in case.iterdir():
        if folder.name == "4":
            for child in folder.iterdir():
                child.unlink()
            folder.rmdir()
    w._update_run_button()
    assert w.solver_mode() == "run" and w.top_bar.run_button.text() == "Run Solver"


def test_with_values_validates_and_replaces() -> None:
    stop = StoppingCriteria(criteria=[*CRITERIA, AsymptoticCriterion(quantity="Cd", window=50, tolerance=1e-3)])
    tight = convergence.with_values(stop, {1: 2e-6, 2: 1e-4})
    assert [convergence.value_field(c) for c in tight.criteria] == ["threshold", "threshold", "tolerance"]
    assert tight.criteria[0] == CRITERIA[0] and tight.criteria[1].threshold == pytest.approx(2e-6)
    assert tight.criteria[2].tolerance == pytest.approx(1e-4) and tight.criteria[2].window == 50
    with pytest.raises(ValueError):
        convergence.with_values(stop, {0: 0.0})


def test_the_dialog(qtbot: QtBot) -> None:
    stop = StoppingCriteria(criteria=[*CRITERIA, AsymptoticCriterion(quantity="Cd", window=50, tolerance=1e-3)])
    dialog = ContinueMetDialog(259, 1000, stop, 259)
    qtbot.addWidget(dialog)
    assert dialog.more.value() == 500 and dialog.windowTitle() == "Continue solver"
    assert [e.text() for e in dialog.values.values()] == ["0.0001", "1e-05", "0.001"]
    assert dialog.values[2].toolTip() == convergence.describe(stop.criteria[2])
    assert dialog.answer() == (500, {})
    dialog.more.setValue(300)
    dialog.values[0].setText("1e-6")
    dialog.values[2].setText("2e-4")
    assert dialog.answer() == (300, {0: pytest.approx(1e-6), 2: pytest.approx(2e-4)})
    dialog.values[1].setText("0")
    assert not dialog._ok.isEnabled() and dialog.values[1].property("invalid")
    dialog.values[1].setText("1e-5")
    assert dialog._ok.isEnabled() and dialog._ok.text() == "Continue Solver"
    empty = ContinueMetDialog(10, 10, StoppingCriteria(criteria=[]), None)
    qtbot.addWidget(empty)
    assert empty.values == {} and empty.answer() == (100, {})
