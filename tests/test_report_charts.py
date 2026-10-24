"""Report charts in their own windows (D-170): opened from a slot's sparkline or its Open chart button, several at once,
the whole history with zoom and pan, the windowed mean and the oscillation band, PNG and CSV export, live updates
during a run, and the windows remembered like the monitors' (off-screen fallback)."""

import csv
import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QWheelEvent
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner, iteration
from tests.fakes import FakeDialogs
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from vortexcfd.core.project import Project
from vortexcfd.foam.convergence import rolling_window
from vortexcfd.foam.run_record import RunRecord, write_run_record
from vortexcfd.gui.monitors import CHARTS_KEY, _chart_key
from vortexcfd.gui.report_charts import ReportChartWindow
from vortexcfd.gui.settings_store import settings

DATA = Path(__file__).parent / "data"


def _with_coefficients(w) -> Path:
    """The oscillating sphere's 172 iterations of forceCoeffs in the project's case, shown as a finished run."""
    case = w.project.path.parent / "case"
    target = case / "postProcessing" / "forceCoeffs1" / "0"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(DATA / "oscillation_run" / "coefficient.dat", target)
    w.project.update_reports(slots=["Cd", "Cl", "yplus_avg"])
    write_run_record(case, RunRecord("iteration_limit", 172))  # reopened, the project shows this run
    w.monitors.load_run(case, [], ("iteration_limit", (), 172))
    return case


def test_the_rolling_mean_and_band() -> None:
    series = [(float(i), float(v)) for i, v in enumerate([1, 3, 1, 3, 2, 2, 5], start=1)]
    rows = rolling_window(series, 3)
    assert [r[0] for r in rows] == [3.0, 4.0, 5.0, 6.0, 7.0]
    for (x, mean, lo, hi), end in zip(rows, range(3, 8)):
        window = [v for _x, v in series[end - 3:end]]
        assert mean == pytest.approx(np.mean(window))
        assert hi - lo == pytest.approx(max(window) - min(window)) and (lo + hi) / 2 == pytest.approx(mean)
    assert rolling_window(series, 10) == [] and rolling_window(series, 1) == []
    assert rolling_window(series + [(7.0, 9.0)], 3)[-1][0] == 7.0  # a repeated iteration counts once


def test_open_from_the_sparkline_and_the_button_several_at_once(make_window, qtbot: QtBot) -> None:
    w = make_window()
    _with_coefficients(w)
    slots = w.monitors.kpis
    assert slots.chart_buttons[1].accessibleName() == "Open chart" and slots.chart_buttons[1].isEnabled()
    qtbot.mouseDClick(slots.sparks[1], Qt.MouseButton.LeftButton)  # Cd from its sparkline
    slots.chart_buttons[2].click()  # Cl from its button
    windows = w.monitors.chart_windows
    assert list(windows) == ["Cd", "Cl"] and all(isinstance(x, ReportChartWindow) for x in windows.values())
    cd = windows["Cd"]
    assert cd.isVisible() and cd.windowTitle() == "Report chart: Cd"
    assert len(cd.chart.points) == 172  # the whole history
    assert cd.chart.window == 100 and len(cd.chart.rolling) == 172 - 99  # the oscillation window's mean and band
    assert cd.stats.text().startswith("latest ") and "mean " in cd.stats.text()
    slots.chart_buttons[1].click()  # open again: the same window
    assert list(windows) == ["Cd", "Cl"]
    slots.chart_buttons[3].click()  # y+ has no windowed mean (written at write times only)
    assert windows["yplus_avg"].chart.rolling == []
    w.project.update_reports(slots=["Cd", None, None])
    assert not slots.chart_buttons[2].isEnabled() and "Assign a report first" in slots.chart_buttons[2].toolTip()
    cd.grab()
    windows["Cl"].close()
    assert "Cl" not in windows and settings().value(f"{CHARTS_KEY}/open") == ["Cd", "yplus_avg"]


def test_zoom_pan_and_show_all(make_window) -> None:
    w = make_window()
    _with_coefficients(w)
    window = w.monitors.open_chart("Cd")
    window.resize(900, 500)
    chart = window.chart
    chart.grab()
    assert chart.shown() == (1.0, 172.0)
    middle = chart._plot_area.center()
    for _ in range(4):
        event = QWheelEvent(middle, chart.mapToGlobal(middle.toPoint()), QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                            False)
        chart.wheelEvent(event)
    lo, hi = chart.shown()
    assert hi - lo < 100 and lo > 1
    chart.grab()
    assert all(lo <= v <= hi for v in chart.x_ticks.major)  # the ticks follow the zoom
    y0, y1 = chart.y_range(lo, hi)
    shown = [v for x, v in chart.points if lo <= x <= hi]
    assert y0 <= min(shown) and max(shown) <= y1  # the y axis fits the shown iterations
    window.all_button.click()
    assert chart.shown() == (1.0, 172.0)


def test_export_png_and_csv(make_window, tmp_path: Path) -> None:
    w = make_window()
    _with_coefficients(w)
    window = w.monitors.open_chart("Cd")
    window.resize(800, 450)
    w.dialogs.chart_export_path = tmp_path / "out" / "cd.png"
    window.png_button.click()
    assert w.dialogs.chart_export_asked[-1][1] == "png"
    assert w.dialogs.chart_export_asked[-1][0].name == "Cd_chart.png"
    assert (tmp_path / "out" / "cd.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    w.dialogs.chart_export_path = tmp_path / "out" / "cd.csv"
    window.csv_button.click()
    rows = list(csv.reader(open(tmp_path / "out" / "cd.csv", encoding="utf-8")))
    assert rows[0] == ["iteration", "Cd", "windowed_mean", "band_low", "band_high"]
    assert len(rows) == 1 + 172 and rows[1][2] == "" and rows[100][2] != ""  # the mean from the 100th iteration
    assert float(rows[1][1]) == pytest.approx(2.057275)
    w.dialogs.chart_export_path = None  # cancelled: nothing written
    window.csv_button.click()


def test_live_updates_during_a_run(make_window, qtbot: QtBot) -> None:
    w = make_window()
    w.project.update_reports(slots=["Cd", None, None])
    case = w.project.path.parent / "case"
    runner = use_runner(w, FakeRunner(iteration(1), hold=True))
    w.run_solver()
    qtbot.waitUntil(lambda: "Time = 1" in w.console.text(), timeout=5000)
    window = w.monitors.open_chart("Cd")
    assert window.chart.points == []
    rows = (DATA / "oscillation_run" / "coefficient.dat").read_text().splitlines(keepends=True)
    header = [r for r in rows if r.startswith("#")]
    data = [r for r in rows if not r.startswith("#")]
    out = case / "postProcessing" / "forceCoeffs1" / "0"
    out.mkdir(parents=True)
    (out / "coefficient.dat").write_text("".join(header + data[:20]))
    qtbot.waitUntil(lambda: len(window.chart.points) == 20, timeout=5000)
    with open(out / "coefficient.dat", "a") as fh:
        fh.write("".join(data[20:150]))
    qtbot.waitUntil(lambda: len(window.chart.points) == 150, timeout=5000)
    assert window.chart.rolling  # the mean appears once the window is full
    runner.release(["End\n"])
    wait_done(qtbot, w)


def test_remembered_across_a_restart_with_an_off_screen_fallback(make_window, qtbot: QtBot) -> None:
    w = make_window()
    _with_coefficients(w)
    window = w.monitors.open_chart("Cd")
    window.resize(700, 420)
    window.move(40, 30)
    w.monitors.open_chart("Cl")
    w.project.save()
    path = w.project.path
    w.project.save = lambda *a, **k: None
    w.close()  # remembered at exit, then closed
    assert settings().value(f"{CHARTS_KEY}/open") == ["Cd", "Cl"]
    s = settings()
    s.setValue(f"{CHARTS_KEY}/{_chart_key('Cl')}/frame", QRect(50000, 50000, 700, 420))  # a screen no longer there
    s.sync()
    from vortexcfd.gui.main_window import MainWindow

    w2 = MainWindow(Project.open(path), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w2)
    w2.show()
    try:
        charts = w2.monitors.chart_windows
        assert list(charts) == ["Cd", "Cl"]
        assert charts["Cd"].size().width() == 700 and charts["Cd"].size().height() == 420
        assert charts["Cl"].frameGeometry().left() < 50000  # placed anew on a screen
        assert len(charts["Cd"].chart.points) == 172  # the reopened run's history
    finally:
        w2.project.save = lambda *a, **k: None
        w2.close()
