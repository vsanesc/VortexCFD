"""The charts' axes (D-169): "nice" ticks by the 1-2-5 rule, minor ticks, readable labels and ticks that follow a
zoom or a pan, on the QPainter charts (the residual chart) and the matplotlib ones (line plots, Compare, the report)."""

import math

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from pytestqt.qtbot import QtBot

from vortexcfd.core.ticks import fitted_ticks, label, nice_step, ticks
from vortexcfd.foam.logparse import TimeStep
from vortexcfd.gui.chart_axis import XView


def _is_nice(step: float) -> bool:
    mantissa = step / 10 ** math.floor(math.log10(step) + 1e-9)
    return any(abs(mantissa - m) < 1e-6 for m in (1, 2, 5))


@pytest.mark.parametrize("hi", [10, 37, 100, 250, 1000, 2600, 10_000, 45_000, 100_000])
def test_iteration_ranges_from_10_to_100000(hi: int) -> None:
    for target in (3, 5, 8):
        t = ticks(1, hi, target, integer=True)
        assert _is_nice(t.step) and t.step >= 1 and t.step == int(t.step)
        assert 2 <= len(t.major) <= 2 * target + 1
        assert all(1 <= v <= hi for v in t.major)
        assert all(b - a == pytest.approx(t.step) for a, b in zip(t.major, t.major[1:]))
        assert all(v == int(v) for v in (*t.major, *t.minor))  # whole iterations, majors and minors
        assert not set(t.major) & set(t.minor)
        assert t.minor == tuple(sorted(t.minor))


@pytest.mark.parametrize("lo, hi, step", [(4520, 4580, 20), (4521, 4529, 2), (990, 1010, 5), (49_000, 51_000, 500),
                                         (12, 15, 1), (1, 6, 1), (80_000, 100_000, 5_000)])
def test_zoomed_ranges(lo: float, hi: float, step: float) -> None:
    t = ticks(lo, hi, 5, integer=True)
    assert t.step == step and lo <= t.major[0] and t.major[-1] <= hi


def test_minor_ticks_divide_the_step() -> None:
    assert ticks(0, 1000, 5, integer=True).step == 200
    assert ticks(0, 1000, 5, integer=True).minor[:4] == (50, 100, 150, 250)  # 4 per 200
    assert ticks(0, 100, 10, integer=True).minor[:3] == (2, 4, 6)  # 5 per 10
    assert ticks(0, 10, 2, integer=True).minor[:2] == (1, 2)  # 5 per 5, each one iteration
    assert ticks(0, 4, 2, integer=True).minor == (1, 3)  # a step of 2: whole iterations only
    assert ticks(0, 0.8, 4).minor[:2] == (0.05, 0.1)  # a 0.2 step on a real axis: 4 minors of 0.05
    assert len(ticks(1, 37, 3, integer=True).major) >= 2  # never a single tick: a smaller step


def test_labels_are_readable() -> None:
    assert ticks(0, 100_000, 5, integer=True).labels() == ["0", "20,000", "40,000", "60,000", "80,000", "100,000"]
    assert label(1500, 500) == "1,500" and label(999, 1) == "999"
    assert ticks(0, 0.37, 4).labels() == ["0.0", "0.1", "0.2", "0.3"]
    assert ticks(-0.05, 0.13, 4).labels() == ["−0.05", "0.00", "0.05", "0.10"]
    assert label(0.30000000000000004, 0.1) == "0.3"
    assert nice_step(7.2, integer=True) == 10 and nice_step(0.3, integer=True) == 1 and nice_step(0.3) == 0.5


def test_the_tick_count_follows_the_room_for_the_labels() -> None:
    width = lambda text: 7.0 * len(text)  # noqa: E731
    narrow = fitted_ticks(1, 100_000, 300, width, integer=True)
    wide = fitted_ticks(1, 100_000, 1200, width, integer=True)
    assert len(narrow.major) < len(wide.major)
    for t, length in ((narrow, 300), (wide, 1200)):
        spacing = length * t.step / (100_000 - 1)
        assert spacing >= max(width(s) for s in t.labels()) + 12  # labels never touch


def test_the_view_zooms_and_pans_inside_the_data() -> None:
    view = XView()
    assert view.range(1, 1000) == (1, 1000) and view.follows
    view.zoom(0.5, 500, 1, 1000)
    lo, hi = view.range(1, 1000)
    assert hi - lo == pytest.approx(499.5) and lo < 500 < hi and not view.follows
    view.pan(10_000, 1, 1000)  # kept inside the data
    assert view.range(1, 1000)[1] == 1000
    view.zoom(100, 500, 1, 1000)  # out past the whole history: follows again
    assert view.follows
    view.zoom(1e-6, 10, 1, 1000)  # the narrowest view: 4 iterations
    lo, hi = view.range(1, 1000)
    assert hi - lo == pytest.approx(4)


# -- matplotlib -------------------------------------------------------------------------------------------------


def test_the_matplotlib_ticks_follow_a_zoom() -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from vortexcfd.workflow import plot_axes

    figure = Figure()
    FigureCanvasAgg(figure)
    ax = figure.add_subplot(111)
    ax.plot(range(1, 20_001), [1.0] * 20_000)
    plot_axes.apply(ax, x_integer=True)
    ax.set_xlim(1, 20_000)
    figure.canvas.draw()
    majors = list(ax.xaxis.get_major_locator()())
    assert all(_is_nice(b - a) for a, b in zip(majors, majors[1:]))
    assert [t.get_text() for t in ax.get_xticklabels()][:3] == ["0", "5,000", "10,000"] or \
        "10,000" in [t.get_text() for t in ax.get_xticklabels()]
    assert ax.xaxis.get_minor_locator()()  # minor ticks
    ax.set_xlim(4520, 4580)  # zoomed: the ticks follow
    figure.canvas.draw()
    assert list(ax.xaxis.get_major_locator()()) == [4520, 4530, 4540, 4550, 4560, 4570, 4580]
    assert ax.xaxis.get_major_formatter()(4540) == "4,540"


def test_the_compare_and_line_plots_use_them(tmp_path) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from tests.test_snapshots import two_snapshots
    from vortexcfd.workflow import plot_axes, snapshots

    _project, first, second = two_snapshots(tmp_path)
    figure = Figure()
    FigureCanvasAgg(figure)
    snapshots.draw(figure, [first, second], "report:Cd")
    ax = figure.axes[0]
    assert isinstance(ax.xaxis.get_major_locator(), plot_axes.NiceLocator)
    assert ax.xaxis.get_major_locator().integer  # an iteration axis
    snapshots.draw(figure, [first, second], "line:axis:p")
    assert not figure.axes[0].xaxis.get_major_locator().integer  # a distance


# -- the residual chart -------------------------------------------------------------------------------------------


def _wheel(widget, x: float, up: bool) -> None:
    pos = QPointF(x, widget.height() / 2)
    event = QWheelEvent(pos, widget.mapToGlobal(pos.toPoint()), QPoint(), QPoint(0, 120 if up else -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    widget.wheelEvent(event)


def test_the_residual_chart_zooms_pans_and_follows_again(qtbot: QtBot) -> None:
    from vortexcfd.gui.monitors import MonitorsPanel

    panel = MonitorsPanel()
    qtbot.addWidget(panel)
    panel.resize(500, 500)
    panel.show()
    for i in range(1, 3001):
        panel.add_step(TimeStep(float(i), residuals=[("p", 1.0 / i, 0.0, 1)]))
    panel.refresh()
    chart = panel.chart
    chart.grab()
    assert chart.x_range() == (1.0, 3000.0)
    assert chart.x_ticks.labels()[-1] in ("3,000", "2,500") and "," in chart.x_ticks.labels()[-1]
    assert "Wheel: zoom" in chart.toolTip()
    middle = chart._plot_area.center().x()
    for _ in range(6):
        _wheel(chart, middle, up=True)
    lo, hi = chart.x_range()
    assert hi - lo < 1000 and 1 <= lo and hi <= 3000
    chart.grab()
    assert chart.x_ticks.step < 500 and all(lo <= v <= hi for v in chart.x_ticks.major)  # the ticks follow
    for i in range(3001, 3101):  # the run goes on: a zoomed view stays where it is
        panel.add_step(TimeStep(float(i), residuals=[("p", 1.0 / i, 0.0, 1)]))
    panel.refresh()
    assert chart.x_range() == (lo, hi)
    qtbot.mouseDClick(chart, Qt.MouseButton.LeftButton)  # back to the whole history, following the run
    assert chart.x_range() == (1.0, 3100.0)
