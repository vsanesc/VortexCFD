"""The residual chart and the convergence criteria in their own windows (D-156): detach and dock, live updates while
detached (fake solver runner), the state remembered across a restart, and a window whose screen is gone docked."""

from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner, iteration
from tests.fakes import FakeDialogs
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from vortexcfd.core.project import Project
from vortexcfd.gui.monitors import DETACHABLE, WINDOWS_KEY
from vortexcfd.gui.panel_widgets import FloatingPanel
from vortexcfd.gui.settings_store import settings
from vortexcfd.gui.theme import TEXT_ROLES


def test_detach_and_dock_with_the_header_buttons(make_window) -> None:
    w = make_window()
    m = w.monitors
    for key, widget in (("residuals", m.chart), ("criteria", m.convergence)):
        button = m.detach_buttons[key]
        assert button.toolTip() == DETACHABLE[key][1] and "Detach" in button.toolTip()
        button.click()
        window = m.windows[key]
        assert isinstance(window, FloatingPanel) and window.isVisible() and window.windowTitle() == DETACHABLE[key][0]
        assert widget.window() is window and widget.isVisible()
        assert button.toolTip() == DETACHABLE[key][2]
        button.click()  # docks it back
        assert key not in m.windows and widget.window() is w and button.toolTip() == DETACHABLE[key][1]
    # closing a detached window docks it
    window = w.detach_monitor("residuals")
    window.close()
    QApplication.processEvents()
    assert not m.is_detached("residuals") and m.chart.window() is w and m.chart.isVisible()
    # the criteria window shows even with no criteria, and says so
    window = w.detach_monitor("criteria")
    assert m.convergence.isVisible() and (m.convergence.has_content or m.convergence.empty_label.isVisible())
    w.dock_monitor("criteria")
    assert m.sections["criteria"].isVisible() == m.convergence.has_content


def test_live_updates_while_detached(make_window, qtbot: QtBot) -> None:
    w = make_window()
    chart = w.detach_monitor("residuals")
    criteria = w.detach_monitor("criteria")
    runner = use_runner(w, FakeRunner(iteration(1, p=1.0) + iteration(2, p=0.5), hold=True))
    w.run_solver()
    qtbot.waitUntil(lambda: len(w.monitors.chart.series.get("p", [])) == 2, timeout=5000)
    assert w.monitors.chart.window() is chart
    banner_running = w.monitors.convergence.banner.text()
    runner.release(iteration(3, p=2e-8) + ["End\n"])
    wait_done(qtbot, w)
    assert w.monitors.chart.series["p"][-1] == (3.0, 2e-8)
    assert w.monitors.convergence.window() is criteria
    assert w.monitors.convergence.banner.text() != banner_running or not w.monitors.convergence.has_content
    chart.grab()  # paints in its own window


def test_the_windows_follow_the_theme_and_the_interface_size(make_window) -> None:
    w = make_window()
    window = w.detach_monitor("criteria")
    assert window.objectName() == "panel"  # the panel's themed background
    w.set_point_size(12)
    label = w.monitors.convergence.banner
    assert label.font().pointSizeF() == 12 * TEXT_ROLES["body"].scale
    w.set_point_size(9)


def test_restored_after_a_restart(qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.main_window import MainWindow

    def open_window():
        w = MainWindow(Project.new("Demo"), FakeDialogs(), with_viewer=False)
        qtbot.addWidget(w)
        w.show()
        QApplication.processEvents()
        return w

    w = open_window()
    window = w.detach_monitor("residuals")
    window.setGeometry(40, 60, 420, 300)
    QApplication.processEvents()
    size = window.geometry().size()
    w.project.save = lambda *a, **k: None
    w._confirm_discard = lambda: True
    w.close()  # remembers the window, then closes it (no window left to keep the application open)
    QApplication.processEvents()
    assert not [x for x in QApplication.topLevelWidgets() if isinstance(x, FloatingPanel) and x.isVisible()]
    assert str(settings().value(f"{WINDOWS_KEY}/residuals/detached")).lower() == "true"
    w2 = open_window()
    try:
        assert w2.monitors.is_detached("residuals") and not w2.monitors.is_detached("criteria")
        restored = w2.monitors.windows["residuals"]
        assert restored.isVisible() and restored.geometry().size() == size
        w2.dock_monitor("residuals")  # docked by the user: docked at the next start
    finally:
        w2.project.save = lambda *a, **k: None
        w2._confirm_discard = lambda: True
        w2.close()
    w3 = open_window()
    assert not w3.monitors.is_detached("residuals")
    w3.project.save = lambda *a, **k: None
    w3._confirm_discard = lambda: True
    w3.close()


def test_a_window_whose_screen_is_gone_opens_docked(qtbot: QtBot) -> None:
    from vortexcfd.gui.main_window import MainWindow

    s = settings()
    probe = FloatingPanel("x", lambda: None)
    s.setValue(f"{WINDOWS_KEY}/criteria/detached", True)
    s.setValue(f"{WINDOWS_KEY}/criteria/geometry", probe.saveGeometry())
    s.setValue(f"{WINDOWS_KEY}/criteria/frame", QRect(50000, 50000, 400, 300))  # a screen no longer there
    s.sync()
    probe.deleteLater()
    w = MainWindow(Project.new("Demo"), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    QApplication.processEvents()
    try:
        assert not w.monitors.is_detached("criteria") and w.monitors.convergence.window() is w
        assert str(settings().value(f"{WINDOWS_KEY}/criteria/detached")).lower() == "false"
    finally:
        w.project.save = lambda *a, **k: None
        w._confirm_discard = lambda: True
        w.close()
