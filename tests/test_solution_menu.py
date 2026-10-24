"""The Solution menu (D-173): after View; each entry is the same action as the top bar's button and the tree's context
menus (one action, one place for its state); the shortcuts; a disabled entry says why; Clear solution and Clear mesh
ask first, Clear mesh saying the solution goes too."""

from pathlib import Path

from PySide6.QtGui import QKeySequence
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner, iteration
from tests.fakes import FakeDialogs
from tests.test_continue import _write_time
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from vortexcfd.gui.main_window import MainWindow


def _entries(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_the_menu_after_view_with_its_entries(make_window) -> None:
    w = make_window()
    titles = [a.text() for a in w.menuBar().actions()]
    assert titles == ["&File", "&Edit", "&View", "&Solution", "&Help"]
    menu = w.solution_menu
    assert _entries(menu) == ["&Generate Mesh", "C&lear Mesh...", "&Run Solver", "S&top Solver", "Clear &Solution...",
                              "&Write Fields Now", "Mesh &Independence Study", "&Polar Sweep", "Open in &ParaView"]
    assert menu.toolTipsVisible()
    shortcuts = {a.text(): a.shortcut().toString() for a in menu.actions() if not a.isSeparator()}
    assert shortcuts["&Run Solver"] == "F5" and shortcuts["S&top Solver"] == "Shift+F5"
    assert shortcuts["&Generate Mesh"] == "F6"
    menu.aboutToShow.emit()  # the studies' state is read when the menu opens
    for act in menu.actions():  # every disabled entry says why
        if not act.isSeparator() and not act.isEnabled():
            assert act.toolTip(), act.text()
    assert not w.act_stop_solver.isEnabled() and w.act_stop_solver.toolTip() == "The solver is not running"
    assert not w.act_write_now.isEnabled() and w.act_write_now.toolTip().startswith("Only while the solver runs")
    assert not w.act_clear_solution.isEnabled() and w.act_clear_solution.toolTip() == "No solution to clear."
    assert not w.act_polar_sweep.isEnabled() and "polar sweep is off" in w.act_polar_sweep.toolTip()


def test_one_action_for_the_menu_the_top_bar_and_the_tree(make_window, qtbot: QtBot) -> None:
    w = make_window()
    bar = w.top_bar
    assert bar.run_button.isEnabled() == w.act_run_solver.isEnabled()
    assert bar.run_button.toolTip() == w.act_run_solver.toolTip()
    assert bar.mesh_button.toolTip() == w.act_generate_mesh.toolTip()
    assert bar.paraview_button.isEnabled() == w.act_paraview.isEnabled()
    for key, acts in ((("mesh", None), (w.act_generate_mesh, w.act_clear_mesh)),
                      (("solvers", None), (w.act_run_solver, w.act_stop_solver, w.act_write_now, w.act_clear_solution)),
                      (("stopping", None), (w.act_run_solver, w.act_stop_solver)),
                      (("mesh_study", None), (w.act_mesh_study,))):
        menu = w.tree_menu_for(key)
        assert all(act in menu.actions() for act in acts), key  # the same objects
    triggered = []
    w.act_run_solver.triggered.connect(lambda: triggered.append("run"))
    use_runner(w, FakeRunner(iteration(1), hold=True, stop_lines=iteration(2) + ["End\n"]))
    bar.run_button.click()  # the top bar's button triggers the action
    assert triggered == ["run"] and w.solver_worker.is_running()
    qtbot.waitUntil(lambda: w.act_stop_solver.isEnabled(), timeout=5000)
    assert bar.run_button.text() == "Stop" and bar.run_button.toolTip() == w.act_stop_solver.toolTip()
    assert not w.act_run_solver.isEnabled() and w.act_write_now.isEnabled()
    w.act_run_solver.trigger()  # F5 while running: never a stop
    assert w.solver_worker.is_running()
    stops = []
    w.act_stop_solver.triggered.connect(lambda: stops.append(1))
    bar.run_button.click()  # Stop: the stop action
    wait_done(qtbot, w)
    assert stops == [1] and w.run_record.state == "stopped"


def test_shift_f5_stops_and_f5_continues(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = w.project.path.parent / "case"
    runner = use_runner(w, FakeRunner(iteration(1), hold=True, stop_lines=iteration(2) + ["End\n"]))
    w.act_run_solver.trigger()
    qtbot.waitUntil(lambda: len(w.monitors.history.series.get("p", [])) == 1, timeout=5000)
    w.act_stop_solver.trigger()
    wait_done(qtbot, w)
    assert runner.stop_requested
    _write_time(case, 2)
    w._update_run_button()
    assert w.act_run_solver.text() == "&Continue Solver" and w.top_bar.run_button.text() == "Continue Solver"
    assert w.act_run_solver.shortcut() == QKeySequence("F5")
    use_runner(w, FakeRunner(iteration(3) + ["End\n"]))
    w.act_run_solver.trigger()  # F5: continue
    wait_done(qtbot, w)
    assert w.run_record.iterations == 3 and len(w.run_record.segments) == 2


def test_clear_solution_asks_first(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = w.project.path.parent / "case"
    use_runner(w, FakeRunner(iteration(1) + ["End\n"]))
    w.act_run_solver.trigger()
    wait_done(qtbot, w)
    _write_time(case, 1)
    w._update_run_button()
    assert w.act_clear_solution.isEnabled()
    w.dialogs.confirm_answer = False
    w.act_clear_solution.trigger()
    assert w.dialogs.confirmed[-1][0] == "Clear solution" and (case / "1").is_dir() and w.run_record is not None
    w.dialogs.confirm_answer = True
    w.act_clear_solution.trigger()
    assert not (case / "1").exists() and w.run_record is None and (case / "constant" / "polyMesh").is_dir()
    assert not w.act_clear_solution.isEnabled()


def test_clear_mesh_says_the_solution_goes_too(make_window, qtbot: QtBot) -> None:
    w = make_window()
    use_runner(w, FakeRunner(iteration(1) + ["End\n"]))
    w.act_run_solver.trigger()
    wait_done(qtbot, w)
    w.dialogs.confirm_answer = False
    w.act_clear_mesh.trigger()
    title, text = w.dialogs.confirmed[-1]
    assert title == "Clear mesh" and "The solution computed on it is deleted too" in text
    assert w.mesh_report is not None  # cancelled
    w.dialogs.confirm_answer = True
    w.act_clear_mesh.trigger()
    assert w.mesh_report is None and w.run_record is None
    assert not w.act_clear_mesh.isEnabled() and w.act_clear_mesh.toolTip() == "No mesh to clear."


def test_without_a_project_only_file_and_help(qtbot: QtBot) -> None:
    w = MainWindow(None, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    assert not w.solution_menu.menuAction().isEnabled()
    assert w.menuBar().actions()[0].isEnabled() and w.menuBar().actions()[-1].isEnabled()
    w.close()


def test_the_manual_lists_the_shortcuts() -> None:
    manual = (Path(__file__).parent.parent / "docs" / "manual").rglob("*.md")
    text = "\n".join(p.read_text(encoding="utf-8") for p in manual)
    for key in ("F5", "Shift+F5", "F6"):
        assert key in text, key
