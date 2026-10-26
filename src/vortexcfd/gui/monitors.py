"""Right column: live residual chart and report slots (empty states until a solver runs)."""

import math
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.core.model import REPORT_SLOTS, AsymptoticCriterion, MeanStableCriterion, StoppingCriteria
from vortexcfd.core.reports import YPLUS, available_reports, report_label
from vortexcfd.foam.convergence import (CriterionStatus, evaluate, oscillation, quantity_label, short_label,
                                       still_changing, window_stats)
from vortexcfd.foam.forces import MASS_WARNING, imbalance_text
from vortexcfd.foam.logparse import TimeStep
from vortexcfd.foam.postprocessing import ReportMonitor
from vortexcfd.foam.residuals import ResidualHistory
from vortexcfd.foam import transient
from vortexcfd.gui.icons import make_glyph
from vortexcfd.gui.panel_widgets import FloatingPanel
from vortexcfd.gui.settings_store import settings
from vortexcfd.gui.theme import DARK, Metrics, Theme, metrics, repolish, residual_style, role_font, set_text_role
from vortexcfd.gui.chart_axis import ZoomPanMixin, draw_x_axis
from vortexcfd.gui.report_charts import ReportChartWindow
from vortexcfd.gui.widgets import ElidedLabel, SectionHeader, discard

EMPTY = "—"
CHART_MIN_U = 10  # the residual chart's minimum height, in font heights


def on_a_screen(frame: QRect) -> bool:
    """Whether a window at ``frame`` (saved with its geometry) would open on one of the screens there are now: the
    strip along its top (the title bar) inside a screen's available area. Qt's restoreGeometry would move an
    off-screen window back silently, so the saved rectangle is checked first."""
    top = QRect(frame.left(), frame.top(), max(frame.width(), 1), max(min(frame.height(), 40), 1))
    return any(screen.availableGeometry().intersects(top) for screen in QGuiApplication.screens())
# Decades shown on the log10 axis without data: 1e0 down to 1e-6 (data can widen the range).
DECADES = tuple(range(0, -7, -1))
REFRESH_MS = 250  # while a run is live, the chart and the report values refresh at most this often
SPARK_POINTS = 200  # points drawn in a report sparkline (the last ones)


def _pen_style(name: str) -> Qt.PenStyle:
    return getattr(Qt.PenStyle, name)


class ResidualChart(ZoomPanMixin, QWidget):
    """Initial residual per iteration on a log10 axis (one line per field, legend), drawn with
    QPainter. The x axis ends at the latest iteration (autoscroll) until it is zoomed or panned (the wheel, a
    drag); a double click shows the whole history and follows the run again (D-169)."""

    EMPTY_MESSAGE = "No solver run yet"
    X_CAPTION = "Iteration"
    Y_CAPTION = "Residual"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("canvas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme: Theme = DARK
        self._margin = 0
        self._line = 1
        self.series: dict[str, list[tuple[float, float]]] = {}
        self._legend: list[tuple[str, str, str, float, int]] = []
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._init_zoom_pan()
        self.x_ticks = None  # the iteration ticks of the last paint (core/ticks.Ticks)

    def configure(self, m: Metrics, t: Theme) -> None:
        self._theme, self._margin, self._line = t, m.s3, m.line
        self.setMinimumHeight(CHART_MIN_U * m.u)  # never squeezed away: the column scrolls instead (D-155)
        self.update()

    def set_series(self, series: dict[str, list[tuple[float, float]]]) -> None:
        """Series to draw (already decimated); empty -> the empty state."""
        self.series = {k: v for k, v in series.items() if v}
        self.update()

    def decades(self) -> list[int]:
        values = [v for s in self.series.values() for _, v in s if v > 0]
        if not values:
            return list(DECADES)
        top = max(0, math.ceil(math.log10(max(values))))
        bottom = min(DECADES[-1], math.floor(math.log10(min(values))))
        return list(range(top, bottom - 1, -1))

    def axis_labels(self) -> list[str]:
        return [f"1e{d}" for d in self.decades()]

    def data_x_range(self) -> tuple[float, float] | None:
        """The iterations of the whole history (None: no data)."""
        xs = [x for s in self.series.values() for x, _ in s]
        if not xs:
            return None
        lo, hi = min(xs), max(xs)
        return (lo, hi) if hi > lo else (lo, lo + 1)

    def x_range(self) -> tuple[float, float]:
        """The iterations shown: the whole history, or the zoomed or panned view."""
        data = self.data_x_range() or (0.0, 1.0)
        return self.x_view.range(*data)

    def legend_entries(self) -> list[tuple[str, str, str]]:
        """(field, colour, pen style name) in the order the fields appeared."""
        return [(name, *residual_style(self._theme, name)) for name in self.series]

    def paintEvent(self, event) -> None:
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = role_font("data")
        painter.setFont(font)
        fm = painter.fontMetrics()
        decades = self.decades()
        label_w = max(fm.horizontalAdvance(f"1e{d}") for d in decades)
        left = self._margin + fm.height() + self._margin + label_w + self._margin  # y caption
        right = self.width() - self._margin
        self._legend = self._legend_layout(fm, left, right)
        rows = 1 + max((y for *_, y in self._legend), default=-1)
        legend_h = rows * fm.height() + self._margin if self.series else 0
        top = self._margin + legend_h + fm.height() / 2
        x_labels_h = fm.height() if self.series else 0
        bottom = self.height() - self._margin - fm.height() * 1.5 - x_labels_h  # room for the x caption
        n = max(len(decades) - 1, 1)
        grid = QPen(QColor(t.border), 1)
        for i, d in enumerate(decades):
            y = top + (bottom - top) * i / n
            painter.setPen(grid)
            painter.drawLine(int(left), round(y), int(right), round(y))
            painter.setPen(QColor(t.muted_text))
            painter.drawText(
                QRectF(left - self._margin - label_w, y - fm.height() / 2, label_w, fm.height()),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"1e{d}",
            )
        area = QRectF(left, top, right - left, bottom - top)
        if self.series:
            self._draw_series(painter, area, decades, fm)
        else:
            painter.setFont(role_font("body"))
            text_w = painter.fontMetrics().horizontalAdvance(self.EMPTY_MESSAGE) + 4 * self._margin
            pill = QRectF(0, 0, text_w, painter.fontMetrics().height() + self._margin)
            pill.moveCenter(area.center())
            painter.setPen(QPen(QColor(t.border), 1))
            painter.setBrush(QColor(t.base))  # a small base pill keeps the grid lines off the text
            painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
            painter.setPen(QColor(t.muted_text))
            painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), self.EMPTY_MESSAGE)
        # Axis captions: "Iteration" under the x axis, "Residual" rotated along the y axis.
        painter.setFont(font)
        painter.setPen(QColor(t.muted_text))
        painter.drawText(
            QRectF(left, bottom + x_labels_h + fm.height() / 2, right - left, fm.height()),
            int(Qt.AlignmentFlag.AlignCenter),
            self.X_CAPTION,
        )
        painter.save()
        painter.translate(self._margin + fm.height() / 2, (top + bottom) / 2)
        painter.rotate(-90)
        painter.drawText(
            QRectF(-(bottom - top) / 2, -fm.height() / 2, bottom - top, fm.height()),
            int(Qt.AlignmentFlag.AlignCenter),
            self.Y_CAPTION,
        )
        painter.restore()
        painter.end()

    def _draw_series(self, painter: QPainter, area: QRectF, decades: list[int], fm) -> None:
        t = self._theme
        x0, x1 = self.x_range()
        hi, lo = decades[0], decades[-1]

        def to_px(x: float, v: float) -> QPointF:
            px = area.left() + (x - x0) / (x1 - x0) * area.width()
            py = area.top() + (hi - math.log10(v)) / max(hi - lo, 1) * area.height()
            return QPointF(px, py)

        # the iteration axis: 1-2-5 ticks for the shown range, minor marks, a light grid (D-169)
        self._plot_area = QRectF(area)
        grid = QColor(t.border)
        self.x_ticks = draw_x_axis(painter, area, x0, x1, fm, grid, QColor(t.muted_text),
                                   integer=self.X_CAPTION == "Iteration")
        painter.save()
        painter.setClipRect(area.adjusted(-2, -2, 2, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for name, color, style in self.legend_entries():
            pen = QPen(QColor(color), 2 * self._line)
            pen.setStyle(_pen_style(style))
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF([to_px(x, v) for x, v in self.series[name] if v > 0]))
        painter.restore()
        # legend above the plot, a line sample in the series style + the name in text ink; it wraps onto more rows
        # where the chart is narrow (D-155)
        sample = 2 * fm.height()
        for name, color, style, x, row in self._legend:
            y = self._margin + row * fm.height()
            pen = QPen(QColor(color), 2 * self._line)
            pen.setStyle(_pen_style(style))
            painter.setPen(pen)
            mid = y + fm.height() / 2
            painter.drawLine(QPointF(x, mid), QPointF(x + sample, mid))
            painter.setPen(QColor(t.text))
            w = fm.horizontalAdvance(name)
            painter.drawText(QRectF(x + sample + self._margin / 2, y, w, fm.height()),
                             int(Qt.AlignmentFlag.AlignVCenter), name)

    def _legend_layout(self, fm, left: float, right: float) -> list[tuple[str, str, str, float, int]]:
        """(name, colour, style, x, row) of each legend entry: as many per row as fit between ``left`` and
        ``right``."""
        out = []
        sample = 2 * fm.height()
        x, row = left, 0
        for name, color, style in self.legend_entries():
            width = sample + self._margin / 2 + fm.horizontalAdvance(name)
            if x > left and x + width > right:
                x, row = left, row + 1
            out.append((name, color, style, x, row))
            x += width + self._margin
        return out

    def legend_rows(self) -> int:
        """The legend's rows at the last paint (for tests)."""
        return 1 + max((row for *_, row in self._legend), default=-1)


class Sparkline(QWidget):
    """A tiny line of the last values of a report (no axes); a double click opens the report's chart (D-170)."""

    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: list[float] = []
        self._color = QColor(DARK.accent)
        self._line = 1
        self.setToolTip("Double-click: open this report's chart in a window (the whole history, zoom, export)")

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    def configure(self, m: Metrics, t: Theme) -> None:
        self._color, self._line = QColor(t.accent), m.line
        self.setFixedHeight(2 * m.u)
        self.update()

    def set_values(self, values: list[float]) -> None:
        self.values = list(values[-SPARK_POINTS:])
        self.update()

    def paintEvent(self, event) -> None:
        if len(self.values) < 2:
            return
        lo, hi = min(self.values), max(self.values)
        span = hi - lo or 1.0
        w, h = self.width() - 2, self.height() - 2
        n = len(self.values) - 1
        points = QPolygonF([QPointF(1 + w * i / n, 1 + h * (1 - (v - lo) / span))
                            for i, v in enumerate(self.values)])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self._color, 1.5 * self._line))
        painter.drawPolyline(points)
        painter.end()


class ReportSlots(QWidget):
    """Report slot cards: title, chevron menu to assign a report, last value, its windowed mean and
    oscillation (D-118), sparkline, name."""

    NOT_ASSIGNED = "Not assigned"
    ASSIGN_TOOLTIP = ("Assign a report: force coefficients of all walls or of one part (with their pressure "
                      "and viscous parts and the centre of pressure), the mass imbalance, y+ min / avg / max on "
                      "the walls (written at each write interval) or a probe's p and U")
    assigned = Signal(int, object)  # slot (0-based), report id or None
    chart_requested = Signal(int)  # slot (0-based): open its report's chart (D-170)
    CHART_TOOLTIP = "Open chart: this report's whole history in a window of its own (zoom, mean, export)"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("kpiRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.titles: dict[int, QLabel] = {}
        self.values: dict[int, QLabel] = {}
        self.means: dict[int, QLabel] = {}  # windowed mean and oscillation (D-118)
        self.window_of = lambda _report_id: 100  # iterations averaged for a report (set by the panel)
        # A transient run (D-181): the slot's line from (report id, points), instead of the windowed mean; None: steady.
        self.mean_text_of = None
        self.mass_resolution: float | None = None  # the smallest imbalance the files show (%, set by the panel)
        self.subtitles: dict[int, QLabel] = {}
        self.sparks: dict[int, Sparkline] = {}
        self.assign_buttons: dict[int, QToolButton] = {}
        self.chart_buttons: dict[int, QToolButton] = {}
        self.menus: dict[int, QMenu] = {}
        self.assignments: list[str | None] = [None] * REPORT_SLOTS
        self.options: list[str] = available_reports([], [])
        self._layouts: list[QVBoxLayout] = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for slot in range(1, REPORT_SLOTS + 1):
            cell = QWidget()
            cell.setObjectName("kpiCell")
            cell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            cell.setProperty("last", "true" if slot == REPORT_SLOTS else "false")
            box = QVBoxLayout(cell)
            head = QHBoxLayout()
            title = ElidedLabel(f"REPORT {slot}", Qt.TextElideMode.ElideRight)  # a narrow column elides
            title.setObjectName("kpiTitle")
            button = QToolButton()
            button.setObjectName("chevronBtn")
            button.setToolTip(self.ASSIGN_TOOLTIP)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(self)
            self._fill_menu(menu, slot - 1)
            button.setMenu(menu)
            chart = QToolButton()
            chart.setObjectName("helpBtn")
            chart.setText("\u2197")
            chart.setAccessibleName("Open chart")
            chart.setToolTip(self.CHART_TOOLTIP)
            chart.setCursor(Qt.CursorShape.PointingHandCursor)
            chart.clicked.connect(lambda _=False, i=slot - 1: self.chart_requested.emit(i))
            head.addWidget(title, 1)
            head.addWidget(chart)
            head.addWidget(button)
            value = QLabel(EMPTY)
            value.setObjectName("kpiValue")
            mean = ElidedLabel("", Qt.TextElideMode.ElideRight)
            mean.setObjectName("kpiSub")
            mean.setToolTip("Mean over the last iterations and the half range of the oscillation (max - min) / 2 "
                            "as a share of |mean| (the oscillation check's scale, D-059)")
            spark = Sparkline()
            spark.double_clicked.connect(lambda i=slot - 1: self.chart_requested.emit(i))
            sub = ElidedLabel(self.NOT_ASSIGNED, Qt.TextElideMode.ElideRight)
            sub.setObjectName("kpiSub")
            box.addLayout(head)
            box.addWidget(value)
            box.addWidget(mean)
            box.addWidget(spark)
            box.addWidget(sub)
            self.titles[slot], self.values[slot], self.means[slot] = title, value, mean
            self.subtitles[slot], self.assign_buttons[slot] = sub, button
            self.chart_buttons[slot] = chart
            self.sparks[slot], self.menus[slot] = spark, menu
            self._layouts.append(box)
            row.addWidget(cell, 1)

    @staticmethod
    def _group(report_id: str) -> str | None:
        """Submenu of a report id (None: top level)."""
        base, _sep, patch = report_id.partition("@")
        if patch:
            return f"Part {patch}"
        if report_id.startswith("probe:"):
            return f"Probe {report_id.split(':')[1]}"
        if report_id == "mass_imbalance" or report_id in YPLUS:
            return None
        return "All walls"

    def _fill_menu(self, menu: QMenu, index: int) -> None:
        menu.clear()
        group = QActionGroup(menu)
        submenus: dict[str, QMenu] = {}
        ids = list(self.options)
        current = self.assignments[index]
        if current is not None and current not in ids:  # a removed part or probe: still shown
            ids.append(current)
        for report_id in (None, *ids):
            name = self._group(report_id) if report_id else None
            target = menu
            if name is not None:
                if name not in submenus:
                    submenus[name] = menu.addMenu(name)
                target = submenus[name]
            label = report_label(report_id) if report_id else self.NOT_ASSIGNED
            if report_id is not None and report_id not in self.options:
                label += " (not available)"
            action = QAction(label, target)
            action.setCheckable(True)
            action.setData(report_id)
            action.setChecked(report_id == current)
            group.addAction(action)
            target.addAction(action)
            action.triggered.connect(lambda _=False, r=report_id: self.assigned.emit(index, r))

    def slot_actions(self, slot: int) -> list[QAction]:
        """Every assignable action of a slot's menu (submenus flattened), in menu order."""
        out = []

        def walk(menu: QMenu) -> None:
            for action in menu.actions():
                if action.menu() is not None:
                    walk(action.menu())
                elif action.isCheckable():
                    out.append(action)

        walk(self.menus[slot])
        return out

    def set_options(self, options: list[str]) -> None:
        """The reports this project offers (core/reports.available_reports)."""
        if options != self.options:
            self.options = list(options)
            for slot in range(1, REPORT_SLOTS + 1):
                self._fill_menu(self.menus[slot], slot - 1)

    def set_assignments(self, assignments: list[str | None]) -> None:
        """Show which report each slot carries (values are cleared until ``set_series``)."""
        self.assignments = list(assignments)
        for slot in range(1, REPORT_SLOTS + 1):
            report_id = self.assignments[slot - 1]
            self.subtitles[slot].setText(report_label(report_id) if report_id else self.NOT_ASSIGNED)
            self.subtitles[slot].setToolTip(self.subtitles[slot].text())
            self.chart_buttons[slot].setEnabled(bool(report_id))
            self.chart_buttons[slot].setToolTip(self.CHART_TOOLTIP if report_id else "Assign a report first (the "
                                                "chevron), then open its chart")
            self._fill_menu(self.menus[slot], slot - 1)

    def set_series(self, series_of) -> None:
        """Fill the values from ``series_of(report_id)`` -> [(iteration, value)] (None: no run)."""
        for slot in range(1, REPORT_SLOTS + 1):
            report_id = self.assignments[slot - 1]
            points = series_of(report_id) if (report_id and series_of is not None) else []
            mass = report_id == "mass_imbalance"  # below the files' resolution: "< 4.7e-05", not 0 (D-178)
            resolution = self.mass_resolution if mass else None
            self.values[slot].setText(imbalance_text(points[-1][1], resolution, 4) if points else EMPTY)
            stats = None
            if points and self.mean_text_of is not None and has_running_mean(report_id):
                self.means[slot].setText(self.mean_text_of(report_id, points))
                self.sparks[slot].set_values([v for _, v in points])
                continue
            if points and not report_id.startswith("yplus"):
                stats = window_stats(points, self.window_of(report_id), quantity=report_id)
            text = stats.text() if stats is not None else ""
            if stats is not None and resolution is not None and abs(stats.mean) < resolution:
                text = f"mean {imbalance_text(stats.mean, resolution)} ({stats.n} it.)"
            self.means[slot].setText(text)
            self.sparks[slot].set_values([v for _, v in points])

    def configure(self, m: Metrics, t: Theme) -> None:
        for box in self._layouts:
            box.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
            box.setSpacing(m.s2)
        for label in (*self.titles.values(), *self.subtitles.values(), *self.means.values()):
            set_text_role(label, "data_small")
        for label in self.values.values():
            set_text_role(label, "metric")
        for spark in self.sparks.values():
            spark.configure(m, t)
        icon = make_glyph("chevron_down", QColor(t.muted_text), m.u, self.devicePixelRatioF())
        for button in self.assign_buttons.values():
            button.setIcon(icon)
            button.setIconSize(QSize(m.u, m.u))
        for button in self.chart_buttons.values():
            button.setFixedSize(m.u, m.u)


def has_running_mean(report_id: str | None) -> bool:
    """A transient run's slot shows the running mean of a force or moment coefficient (D-181), not of y+ or the mass
    imbalance."""
    return bool(report_id) and not report_id.startswith("yplus") and report_id != "mass_imbalance"


def set_state(label: QLabel, state: str | None) -> None:
    """Colour a value label: "ok" (success), "warn", "error" or None (text)."""
    for prop in ("ok", "warn", "error"):
        label.setProperty(prop, "true" if state == prop else "false")
    repolish(label)


def mass_warning(percent: float) -> str:
    return (f"Mass imbalance {percent:.3g}% of the inlet flux (above {MASS_WARNING:g}%): "
            "the continuity solution is not converged")


# Banner texts (D-058). The run states are those of foam/solver_run.py.
BANNER_RUNNING = "Solving: stopping criteria not met yet"
BANNER_LIMIT = "Iteration limit reached without meeting the criteria"
BANNER_STOPPED = "Stopped by the user before the criteria were met"
BANNER_CRASHED = "The solver crashed before the criteria were met"
BANNER_NO_RUN = "No solver run yet"


SATISFIED_TIP = ("Whether the criterion holds at the last iteration: a residual below its threshold, a windowed "
                 "value (asymptotic, mean stable) at most its tolerance over its window. It stops the run only from "
                 "its earliest iteration (the minimum iterations, its window) and, with \"all\", when every "
                 "criterion holds at the same iteration.")


def satisfied_text(status) -> tuple[str, str]:
    """(text, tooltip) of a criterion's "Satisfied now" cell (D-178): whether it holds at the last iteration; a window
    not yet complete says how far it is; one that holds before it may stop the run says from when it may."""
    if status.value is None:
        if status.progress is not None:
            have, need = status.progress
            return (f"not yet: {have:,} of {need:,} iterations",
                    f"Its window needs {need:,} iterations; {have:,} so far")
        return "not yet", "No value yet"
    if not status.holds:
        return "no", "Not below its threshold at the last iteration" + (f"; it may stop the run {status.note}"
                                                                       if status.note else "")
    if not status.satisfied and status.earliest > 1:
        return (f"yes (stops from {status.earliest:,})",
                f"It holds at the last iteration, but may stop the run only from iteration {status.earliest:,} "
                "(the minimum iterations, its window; in the second turbulence stage counted from the switch)")
    return "yes", "It holds at the last iteration"


def drift_warning(quantity: str) -> str:
    """The soft warning of a force coefficient still changing while the residual criteria hold (D-178)."""
    label = quantity_label(quantity)
    return f"Residuals met, but {label} is still changing: add an asymptotic or mean-stable criterion on it"


# How often the statistics of a running transient run are computed again (s; the Strouhal number's FFT).
TRANSIENT_STATS_S = 2.0


def banner_for(state: str | None, stopped_by: tuple[str, ...], iterations: int | None) -> tuple[str, str | None]:
    """(text, colour state) of the convergence banner for a run state (None: running)."""
    if state is None:
        return BANNER_RUNNING, None
    if state == "criteria_met":
        at = f" at iteration {iterations}" if iterations else ""
        if stopped_by:
            return f"Criteria met{at}: " + "; ".join(stopped_by), "ok"
        return f"Criteria met{at}: SIMPLE residual control", "ok"
    if state == "iteration_limit":
        return BANNER_LIMIT, "warn"
    if state == "stopped":
        return BANNER_STOPPED, "warn"
    if state == "crashed":
        return BANNER_CRASHED, "error"
    return BANNER_NO_RUN, None


def banner_without_criteria(state: str | None) -> tuple[str, str | None]:
    """The banner of a run that had no stopping criteria (shown when the project has some now, D-165)."""
    return {None: ("Solving without stopping criteria: the run ends at the iteration limit", None),
            "iteration_limit": ("Iteration limit reached; this run had no stopping criteria", "warn"),
            "stopped": ("Stopped by the user; this run had no stopping criteria", "warn"),
            "crashed": ("The solver crashed", "error")}.get(state, (BANNER_NO_RUN, None))


class ConvergencePanel(QWidget):
    """Convergence banner, per-criterion state and oscillation warnings (D-058, D-059).

    The banner and the criteria table are shown only when stopping criteria exist; oscillation
    warnings whenever a monitored quantity oscillates.
    """

    HEADERS = ("Criterion", "Value", "Threshold", "Satisfied now")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("convergenceBox")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.banner = QLabel()
        self.banner.setObjectName("checkValue")
        self.banner.setWordWrap(True)
        self._grid_host = QWidget()
        self.grid = QGridLayout(self._grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.rows: list[tuple[QLabel, QLabel, QLabel, QLabel]] = []
        self.warnings: list[QLabel] = []
        self._warning_box = QVBoxLayout()
        self._warning_box.setContentsMargins(0, 0, 0, 0)
        self.has_content = False
        self.always_visible = False  # in its own window (D-156): shown even with nothing to show
        self.empty_label = QLabel(NO_CRITERIA)
        self.empty_label.setObjectName("muted")
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(False)
        # Whose criteria the table shows ("Criteria of the last run", D-165) and, when the project's differ from the
        # shown run's, what the project's are now (they apply to the next run).
        self.caption = QLabel()
        self.caption.setObjectName("kpiTitle")
        self.caption.setVisible(False)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        self._layout = QVBoxLayout(self)
        self._layout.addWidget(self.empty_label)
        self._layout.addWidget(self.banner)
        self._layout.addWidget(self.caption)
        self._layout.addWidget(self._grid_host)
        self._layout.addWidget(self.note)
        self._layout.addLayout(self._warning_box)
        for col, text in enumerate(self.HEADERS):
            head = QLabel(text)
            head.setObjectName("kpiTitle")
            if col == len(self.HEADERS) - 1:
                head.setToolTip(SATISFIED_TIP)
            self.grid.addWidget(head, 0, col)
        self.grid.setColumnStretch(0, 1)
        self._has_criteria = False
        self.set_view(False, ("", None), [], [])

    def set_view(self, has_criteria: bool, banner: tuple[str, str | None], statuses: list[CriterionStatus],
                 warnings: list[str], caption: str = "", note: str = "") -> None:
        """``warnings``: oscillation and mass balance messages (warning colour); ``caption``: whose criteria the
        table shows; ``note``: the project's criteria when they differ from the shown run's (D-165)."""
        self._has_criteria = has_criteria
        self.banner.setText(banner[0])
        set_state(self.banner, banner[1])
        self.banner.setVisible(has_criteria or bool(note))
        self._grid_host.setVisible(has_criteria and bool(statuses))
        self.caption.setText(caption)
        self.caption.setVisible(bool(caption) and has_criteria and bool(statuses))
        self.note.setText(note)
        self.note.setVisible(bool(note))
        while len(self.rows) > len(statuses):
            for label in self.rows.pop():
                self.grid.removeWidget(label)
                discard(label)
        while len(self.rows) < len(statuses):
            r = len(self.rows) + 1
            labels = (ElidedLabel("", Qt.TextElideMode.ElideRight), *(QLabel() for _ in self.HEADERS[1:]))
            labels[-1].setWordWrap(True)  # "not yet: 40 of 50 iterations" wraps instead of squeezing the names
            for col, label in enumerate(labels):  # the name column elides instead of widening the column
                label.setObjectName("checkValue")
                set_text_role(label, "data_small")
                self.grid.addWidget(label, r, col)
            self.rows.append(labels)  # type: ignore[arg-type]
        for labels, status in zip(self.rows, statuses):
            name, value, threshold, met = labels
            name.setText(status.label or status.description)
            # the short name stays whole (up to 8 u); the "Satisfied now" cell wraps instead
            name.setMinimumWidth(min(name.fontMetrics().horizontalAdvance(name.text()) + 2, 8 * metrics().u))
            name.setToolTip(status.description + (f" ({status.note})" if status.note else ""))
            value.setText(EMPTY if status.value is None else f"{status.value:.3g}")
            threshold.setText(f"{status.threshold:.3g}")
            text, tip = satisfied_text(status)
            met.setText(text)
            met.setToolTip(tip)
            set_state(met, "ok" if status.holds else None)
        for label in self.warnings:
            self._warning_box.removeWidget(label)
            discard(label)
        self.warnings = []
        for text in warnings:
            label = QLabel(text)
            label.setObjectName("checkValue")
            label.setWordWrap(True)
            set_state(label, "warn")
            self._warning_box.addWidget(label)
            self.warnings.append(label)
        self.has_content = has_criteria or bool(warnings) or bool(note)
        self._show()

    def set_always_visible(self, on: bool) -> None:
        self.always_visible = on
        self._show()

    def _show(self) -> None:
        self.empty_label.setVisible(not self.has_content)
        self.setVisible(self.has_content or self.always_visible)

    @property
    def statuses_text(self) -> list[tuple[str, str, str, str]]:
        return [tuple(label.text() for label in row) for row in self.rows]  # type: ignore[misc]

    def configure(self, m: Metrics, t: Theme) -> None:
        self._layout.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
        self._layout.setSpacing(m.s1)
        self.grid.setHorizontalSpacing(m.s2)
        self.grid.setVerticalSpacing(m.s1)
        for i in range(self.grid.count()):
            widget = self.grid.itemAt(i).widget()
            if widget is not None:
                set_text_role(widget, "data_small")
        set_text_role(self.banner, "body")
        set_text_role(self.empty_label, "body")
        set_text_role(self.caption, "data_small")
        set_text_role(self.note, "body")


NO_CRITERIA = "No stopping criteria and no warnings (set the criteria under Solver > Stopping criteria)."
# Whose criteria the convergence table shows (D-165).
CAPTION_RUNNING = "Criteria of this run"
CAPTION_LAST_RUN = "Criteria of the last run"
CAPTION_UNRECORDED = "Criteria of the project (the last run's were not recorded)"


def criteria_labels(stopping: StoppingCriteria | None) -> str:
    """The criteria in a few words ("p residual; Cd asymptotic"), or "none"."""
    if stopping is None or not stopping.criteria:
        return "none"
    return "; ".join(short_label(c) for c in stopping.criteria)


def same_criteria(a: StoppingCriteria | None, b: StoppingCriteria | None) -> bool:
    """True when two sets stop a run alike: the criteria, how they combine and the minimum iterations (the
    oscillation warning's settings are not criteria)."""
    def key(s):
        return None if s is None or not s.criteria else (s.model_dump()["criteria"], s.combine, s.min_iterations)
    return key(a) == key(b)


def project_note(run: StoppingCriteria | None, project: StoppingCriteria | None, running: bool) -> str:
    """The note under a run's criteria when the project's are no longer the same (D-165)."""
    if same_criteria(run, project):
        return ""
    when = "during this run" if running else "since this run"
    return (f"The project's stopping criteria have changed {when}: now {criteria_labels(project)}. They apply to the "
            "next run.")
# The parts of the column that open in their own window (D-156): key -> (window title, detach tip, dock tip).
DETACHABLE = {
    "residuals": ("Residuals", "Detach the residual chart into its own window (it keeps updating live; close the "
                  "window or click again to dock it)", "Dock the residual chart back into the main window"),
    "criteria": ("Convergence criteria", "Detach the convergence criteria into their own window (they keep "
                 "updating live; close the window or click again to dock them)",
                 "Dock the convergence criteria back into the main window"),
}
WINDOWS_KEY = "monitors/windows"  # per user: <key>/detached, <key>/geometry
CHARTS_KEY = "monitors/charts"  # per user (D-170): open (the report ids), <report key>/geometry and frame


def _chart_key(report_id: str) -> str:
    """A report id as a settings key (no "/" or ":")."""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in report_id)


def stage_text(stage: int, switch: int | None = None, reason: str = "") -> str:
    """The monitors' line for a two-stage run (D-126): stage 1 (first-order k, omega) or stage 2 from the switch."""
    if stage == 1:
        return "Turbulence stage 1 of 2: first-order k, omega (second order after the criteria are met)"
    return (f"Turbulence stage 2 of 2: second-order k, omega from iteration {switch}"
            + (f" (switch: {reason})" if reason else ""))


class MonitorsPanel(QWidget):
    """Header + residual chart + report slots, fed live while the solver runs.

    ``add_step`` is called from GUI-thread slots (queued signals); the postProcessing files are
    polled on a GUI-thread timer (they are tailed: each poll reads only the new bytes).
    """

    slot_assigned = Signal(int, object)  # slot (0-based), report id or None
    updated = Signal()  # new data was shown (the report readers polled something)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.case_dir: Path | None = None  # case of the shown run
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header = SectionHeader("Residuals")
        self.header.add_badge("Log10 Scale")
        self.chart = ResidualChart()
        self.convergence = ConvergencePanel()
        self.kpis = ReportSlots()
        self.kpis.assigned.connect(self.slot_assigned)
        self.kpis.chart_requested.connect(self._open_slot_chart)
        # The report charts in their own windows (D-170), by report id; ``ask_export(suggested, kind)`` gives the
        # export path (the window's dialogs), ``export_folder`` the suggested folder.
        self.chart_windows: dict[str, ReportChartWindow] = {}
        self.ask_export = lambda _suggested, _kind: None
        self.export_folder: Path | None = None
        self._theme: Theme = DARK
        # The turbulence stage of a two-stage run (D-126): "" (hidden) for a single-stage run.
        self.stage_label = QLabel()
        self.stage_label.setObjectName("muted")
        self.stage_label.setWordWrap(True)
        self.stage_label.setVisible(False)
        # The detachable parts (D-156): the residual chart (with the stage line) and the convergence criteria.
        self.sections: dict[str, QWidget] = {}
        residuals = QWidget()
        box = QVBoxLayout(residuals)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self.stage_label)
        box.addWidget(self.chart, 1)
        self.sections["residuals"] = residuals
        self.criteria_header = SectionHeader("Convergence criteria")
        criteria = QWidget()
        box = QVBoxLayout(criteria)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self.criteria_header)
        box.addWidget(self.convergence)
        self.sections["criteria"] = criteria
        self.detach_buttons: dict[str, QToolButton] = {}
        for key, header in (("residuals", self.header), ("criteria", self.criteria_header)):
            button = QToolButton()
            button.setObjectName("helpBtn")
            button.setText("\u2197")
            button.setToolTip(DETACHABLE[key][1])
            button.clicked.connect(lambda _=False, k=key: self.toggle_window(k))
            header.row.addWidget(button)
            self.detach_buttons[key] = button
        self.windows: dict[str, FloatingPanel] = {}
        # Under the header the column scrolls when it is short (D-155): the chart keeps its minimum height and the
        # criteria and report slots their text, instead of being squeezed.
        body = QWidget()
        body.setObjectName("panel")
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(residuals, 1)
        self._layout.addWidget(criteria)
        self._layout.addWidget(self.kpis)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("propScroll")  # the properties' frameless, transparent scroll area
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.scroll, 1)
        self.convergence.setVisible(False)
        self._sync_criteria_section()
        self.history = ResidualHistory()
        self.reports: ReportMonitor | None = None
        # The criteria the shown run is judged by (stage 2's in a two-stage run's second stage), the criteria it
        # started with, the project's current criteria (D-165), and its outcome: (state, stopped_by, iterations);
        # state None = running, outcome None = no run. ``run_criteria_known`` is False for a run whose record
        # predates the recorded criteria (the project's are then shown, labelled so).
        self.stopping: StoppingCriteria | None = None
        self.run_stopping: StoppingCriteria | None = None
        self.project_stopping: StoppingCriteria | None = None
        self.run_criteria_known = True
        self.outcome: tuple[str | None, tuple[str, ...], int | None] | None = None
        # A transient run (D-181): its control file (the sampling start appears when detected) and the recorded
        # statistics of a finished run (None: computed from the files).
        self.transient: transient.TransientControl | None = None
        self.transient_record: dict | None = None
        self._transient_stats: tuple[float, dict | None] = (0.0, None)
        self._dirty = False
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

    def clear(self) -> None:
        """No run: empty chart and report values."""
        self._timer.stop()
        self.history.clear()
        self.reports = None
        self.case_dir = None
        self.outcome = None
        self.stopping = self.run_stopping = None
        self.run_criteria_known = True
        self.transient = self.transient_record = None
        self._transient_stats = (0.0, None)
        self.chart.set_series({})
        self.kpis.set_series(None)
        self.set_stage("")
        self._update_convergence()
        self.updated.emit()

    def set_project_stopping(self, stopping: StoppingCriteria | None) -> None:
        """The project's current stopping criteria (they apply to the next run; D-165)."""
        if stopping != self.project_stopping:
            self.project_stopping = stopping
            self._dirty = True
            self.refresh()

    def set_run_stopping(self, stopping: StoppingCriteria | None) -> None:
        """The criteria the shown run is judged by from now on (stage 2's criteria of a two-stage run, D-126)."""
        if stopping != self.stopping:
            self.stopping = stopping
            self._dirty = True
            self.refresh()

    def judged_criteria(self) -> StoppingCriteria | None:
        """The criteria the table evaluates: the shown run's, the project's when no run is shown or the run's were
        not recorded."""
        if self.outcome is not None and self.run_criteria_known:
            return self.stopping
        return self.project_stopping

    def start_run(self, case_dir: Path, stopping: StoppingCriteria | None = None, keep_history: bool = False) -> None:
        """A solver run starts in ``case_dir``: forget the previous run, poll its files. ``keep_history``: the run
        continues the shown solution (D-171): its residual history stays and goes on."""
        if keep_history:
            self._timer.stop()
            self.outcome = None
            self.set_stage("")
        else:
            self.clear()
        self.stopping = self.run_stopping = stopping
        self.run_criteria_known = True
        self.reports = ReportMonitor(case_dir)
        self.case_dir = Path(case_dir)
        self.transient = transient.read_control(case_dir)
        self.outcome = (None, (), None)
        self._timer.start()
        self._update_convergence()

    def set_stage(self, text: str) -> None:
        """The turbulence stage line of a two-stage run (``stage_text``); "" hides it."""
        self.stage_label.setText(text)
        self.stage_label.setVisible(bool(text))

    def set_outcome(self, state: str, stopped_by: tuple[str, ...] = (), iterations: int | None = None) -> None:
        """How the shown run ended (solver_run states; ``stopped_by``: descriptions of the criteria
        that stopped it)."""
        self.outcome = (state, tuple(stopped_by), iterations)
        self._dirty = True
        self.refresh()

    def add_step(self, step: TimeStep) -> None:
        """One completed solver iteration (logparse.TimeStep), in the GUI thread."""
        self.history.add(step)
        self._dirty = True

    def end_run(self) -> None:
        """The run ended: read what is left and stop polling."""
        self._timer.stop()
        self._dirty = True
        self.refresh()

    def load_run(self, case_dir: Path, steps, outcome: tuple[str, tuple[str, ...], int | None] | None = None,
                 stopping: StoppingCriteria | None = None, judged: StoppingCriteria | None = None) -> None:
        """Show a finished run (project open): its log's steps and its postProcessing files. ``stopping``: the
        criteria the run started with (its record's; None: not recorded), ``judged``: those it ended judged by
        (stage 2's), default ``stopping``."""
        self.clear()
        self.run_stopping = stopping
        self.stopping = judged if judged is not None else stopping
        self.run_criteria_known = stopping is not None
        self.history.extend(steps)
        self.reports = ReportMonitor(case_dir)
        self.case_dir = Path(case_dir)
        self.transient = transient.read_control(case_dir)
        self.outcome = outcome
        self._dirty = True
        self.refresh()

    def set_assignments(self, assignments: list[str | None]) -> None:
        if assignments != self.kpis.assignments:
            self.kpis.set_assignments(assignments)
            self._dirty = True
            self.refresh()

    def refresh(self) -> None:
        """Redraw the chart and the report values if anything changed."""
        if self.reports is not None and self.reports.poll():
            self._dirty = True
        if not self._dirty:
            return
        self._dirty = False
        if self.transient is not None and self.outcome is not None and self.outcome[0] is None:
            self.transient = transient.read_control(self.case_dir) or self.transient  # a detected sampling start
        self.chart.X_CAPTION = "Time [s]" if self.transient is not None else ResidualChart.X_CAPTION
        self.chart.set_series(self.history.decimated())
        self.kpis.window_of = self.mean_window
        start = self.transient.sampling_start if self.transient is not None else None
        self.kpis.mean_text_of = ((lambda _rid, points: transient.slot_text(points, start))
                                  if self.transient is not None else None)
        self.kpis.mass_resolution = self.reports.mass_resolution() if self.reports is not None else None
        self.kpis.set_series(self.reports.series if self.reports is not None else None)
        self._update_convergence()
        self._update_charts()
        self.updated.emit()

    def mean_window(self, quantity: str) -> int:
        """The iterations a report's mean is taken over: the window of a mean-stable criterion watching
        it, else the oscillation window (D-059, D-118)."""
        stop = self.judged_criteria()
        if stop is None:
            return 100
        for c in stop.criteria:
            if isinstance(c, MeanStableCriterion) and c.quantity == quantity:
                return c.window
        return stop.oscillation_window

    def monitored_quantities(self) -> list[str]:
        """Quantities checked for oscillation: the asymptotic criteria's and the assigned report
        slots' (y+ is written only at write times and is left out)."""
        names: list[str] = []
        stop = self.judged_criteria()
        if stop is not None:
            names += [c.quantity for c in stop.criteria if isinstance(c, AsymptoticCriterion)]
        names += [r for r in self.kpis.assignments
                  if r and not r.startswith("yplus") and r != "mass_imbalance" and not r.startswith("x_cp")]
        return list(dict.fromkeys(names))

    def set_transient_record(self, record: dict | None) -> None:
        """The transient part of the shown run's record (D-181): its statistics and when it stopped."""
        self.transient_record = record
        self._dirty = True
        self.refresh()

    def transient_summary(self) -> dict | None:
        """The statistics of the shown transient run: the record's for a finished run, else computed from the files
        (at most every TRANSIENT_STATS_S seconds while it runs)."""
        import time

        if self.transient is None or self.transient.sampling_start is None or self.reports is None:
            return None
        running = self.outcome is not None and self.outcome[0] is None
        if not running and self.transient_record and self.transient_record.get("statistics"):
            return self.transient_record["statistics"]
        stamp, cached = self._transient_stats
        if cached is not None and running and time.monotonic() - stamp < TRANSIENT_STATS_S:
            return cached
        series = {q: self.reports.series(q) for q in ("Cd", "Cl", "CmPitch")}
        series = {q: rows for q, rows in series.items() if rows}
        found = transient.summary(series, self.transient.sampling_start, self.transient.length,
                                  self.transient.speed) if series else None
        self._transient_stats = (time.monotonic(), found)
        return found

    def _update_transient(self) -> None:
        """The convergence box of a transient run (D-181): the banner (time, sampling, the end) and the statistics."""
        state = self.outcome[0] if self.outcome is not None else None
        steps = self.history.series.get("p") or []
        now = steps[-1][0] if steps else None
        text, colour = transient.banner(self.transient, state, now, self.transient_record)
        if self.outcome is None:
            text, colour = BANNER_NO_RUN, None
        summary = self.transient_summary()
        note = transient.statistics_text(summary, self.transient.convective_time)
        self.convergence.set_view(True, (text, colour), [], [], "Transient run", note)
        self._sync_criteria_section()

    def _update_convergence(self) -> None:
        if self.transient is not None:
            self._update_transient()
            return
        stop = self.judged_criteria()
        has = stop is not None and bool(stop.criteria)
        series_of = self.reports.series if self.reports is not None else (lambda _q: [])
        statuses = evaluate(stop, self.history.series, series_of) if has and self.outcome is not None else []
        if self.outcome is None:
            banner = (BANNER_NO_RUN, None)
        else:
            banner = banner_for(*self.outcome)
        warnings = []
        oscillating: set[str] = set()
        if stop is not None and self.reports is not None:
            floors = {c.quantity: c.effective_floor for c in stop.criteria if isinstance(c, AsymptoticCriterion)}
            for name in self.monitored_quantities():
                osc = oscillation(name, series_of(name), stop.oscillation_window, stop.oscillation_threshold,
                                  floors.get(name))
                if osc is not None:
                    stable = any(isinstance(c, MeanStableCriterion) and c.quantity == name for c in stop.criteria)
                    warnings.append(osc.message(suggest_mean_stable=not stable))
                    oscillating.add(name)
            if statuses:  # the residual criteria hold, a force coefficient still changes (D-178)
                warnings += [drift_warning(name) for name in
                             still_changing(stop, statuses, self.monitored_quantities(), series_of)
                             if name not in oscillating]
        if self.reports is not None:
            balance = self.reports.mass_balance()
            if balance is not None and balance[2] is not None and abs(balance[2]) > MASS_WARNING:
                warnings.append(mass_warning(balance[2]))
        caption, note = "", ""
        if self.outcome is None and has:
            note = f"The project's stopping criteria (they apply to the next run): {criteria_labels(stop)}."
        elif self.outcome is not None and self.run_criteria_known and not has:  # a run without criteria
            banner = banner_without_criteria(self.outcome[0])
        if self.outcome is not None and not self.run_criteria_known:
            caption = CAPTION_UNRECORDED
        elif self.outcome is not None:
            running = self.outcome[0] is None
            caption = CAPTION_RUNNING if running else CAPTION_LAST_RUN
            note = project_note(self.run_stopping, self.project_stopping, running)
        self.convergence.set_view(has, banner, statuses, warnings, caption, note)
        self._sync_criteria_section()

    # -- the residual chart and the criteria in their own windows (D-156) -----------------------------------------

    def _sync_criteria_section(self) -> None:
        """The criteria's place in the column: shown when it has something to show and is docked."""
        if "criteria" not in self.windows:
            self.sections["criteria"].setVisible(self.convergence.has_content)

    def is_detached(self, key: str) -> bool:
        return key in self.windows

    def toggle_window(self, key: str) -> None:
        if key in self.windows:
            self.dock(key)
        else:
            self.detach(key)

    def detach(self, key: str, geometry: QByteArray | None = None) -> FloatingPanel:
        """``key`` ("residuals" or "criteria") into its own window: the same widgets, so live updates go on."""
        if key in self.windows:
            return self.windows[key]
        section = self.sections[key]
        window = FloatingPanel(DETACHABLE[key][0], lambda k=key: self.dock(k), (16, 12 if key == "residuals" else 8))
        window.setWindowIcon(self.window().windowIcon())
        u = metrics().u
        width, height = max(section.width(), 24 * u), max(section.height(), (20 if key == "residuals" else 12) * u)
        if key == "criteria":
            self.convergence.set_always_visible(True)
            self.criteria_header.hide()  # the window's title says it
        window.take(section)
        section.show()
        self.windows[key] = window
        window.resize(width, height)
        if geometry is not None:
            window.restoreGeometry(geometry)
        window.show()
        self.detach_buttons[key].setToolTip(DETACHABLE[key][2])
        self._save_window(key)
        return window

    def dock(self, key: str, remember: bool = True) -> None:
        """Back into the column (also when its window is closed). ``remember`` False: the state is not saved (the
        application is closing)."""
        window = self.windows.pop(key, None)
        if window is None:
            return
        if remember:
            self._save_window(key, window)
        section = self.sections[key]
        index = 0 if key == "residuals" else 1
        window.release()
        self._layout.insertWidget(index, section, 1 if key == "residuals" else 0)
        section.show()
        if key == "criteria":
            self.criteria_header.show()
            self.convergence.set_always_visible(False)
            self._sync_criteria_section()
        window.close()
        window.deleteLater()
        self.detach_buttons[key].setToolTip(DETACHABLE[key][1])
        if remember:
            s = settings()
            s.setValue(f"{WINDOWS_KEY}/{key}/detached", False)
            s.sync()

    def _save_window(self, key: str, window: FloatingPanel | None = None) -> None:
        window = window or self.windows.get(key)
        s = settings()
        s.setValue(f"{WINDOWS_KEY}/{key}/detached", key in self.windows)
        if window is not None:
            s.setValue(f"{WINDOWS_KEY}/{key}/geometry", window.saveGeometry())
            s.setValue(f"{WINDOWS_KEY}/{key}/frame", window.frameGeometry())
        s.sync()

    def save_windows(self) -> None:
        """At exit: each window's state and geometry remembered, then the windows closed (docked, not saved so)."""
        for key in list(self.windows):
            self._save_window(key)
            self.dock(key, remember=False)

    def restore_windows(self) -> None:
        """The windows as the user left them; a window whose saved place is on no screen now stays docked."""
        s = settings()
        for key in DETACHABLE:
            if str(s.value(f"{WINDOWS_KEY}/{key}/detached", False)).lower() not in ("true", "1"):
                continue
            geometry = s.value(f"{WINDOWS_KEY}/{key}/geometry")
            frame = s.value(f"{WINDOWS_KEY}/{key}/frame")
            if not isinstance(geometry, QByteArray) or not isinstance(frame, QRect) or not on_a_screen(frame):
                s.setValue(f"{WINDOWS_KEY}/{key}/detached", False)
                continue
            self.detach(key, geometry)

    def floating_windows(self) -> list[FloatingPanel]:
        return [*self.windows.values(), *self.chart_windows.values()]

    # -- the report charts in their own windows (D-170) ----------------------------------------------------------

    def _open_slot_chart(self, index: int) -> None:
        report_id = self.kpis.assignments[index]
        if report_id:
            self.open_chart(report_id)

    def open_chart(self, report_id: str, geometry: QByteArray | None = None) -> ReportChartWindow:
        """The chart window of ``report_id`` (raised when it is open); at its remembered place unless that is on no
        screen now."""
        window = self.chart_windows.get(report_id)
        if window is not None:
            window.raise_()
            window.activateWindow()
            return window
        window = ReportChartWindow(report_id, lambda r=report_id: self._chart_closed(r))
        window.setWindowIcon(self.window().windowIcon())
        window.configure(self._theme)
        window.export_requested.connect(self._export_chart)
        u = metrics().u
        window.resize(48 * u, 30 * u)
        s = settings()
        key = _chart_key(report_id)
        geometry = geometry if geometry is not None else s.value(f"{CHARTS_KEY}/{key}/geometry")
        frame = s.value(f"{CHARTS_KEY}/{key}/frame")
        if isinstance(geometry, QByteArray) and isinstance(frame, QRect) and on_a_screen(frame):
            window.restoreGeometry(geometry)
        self.chart_windows[report_id] = window
        self._fill_chart(report_id)
        window.show()
        self._save_charts()
        return window

    def close_chart(self, report_id: str, remember: bool = True) -> None:
        window = self.chart_windows.get(report_id)
        if window is not None:
            if not remember:
                self.chart_windows.pop(report_id, None)
            window.close()

    def _chart_closed(self, report_id: str) -> None:
        """A chart window closed (by the user or at exit): its place remembered, the list of open charts saved."""
        window = self.chart_windows.pop(report_id, None)
        if window is not None:
            self._save_chart_geometry(report_id, window)
            window.release()
            window.deleteLater()
            self._save_charts()

    def _save_chart_geometry(self, report_id: str, window) -> None:
        s = settings()
        key = _chart_key(report_id)
        s.setValue(f"{CHARTS_KEY}/{key}/geometry", window.saveGeometry())
        s.setValue(f"{CHARTS_KEY}/{key}/frame", window.frameGeometry())
        s.sync()

    def _save_charts(self) -> None:
        s = settings()
        s.setValue(f"{CHARTS_KEY}/open", list(self.chart_windows))
        s.sync()

    def _fill_chart(self, report_id: str) -> None:
        window = self.chart_windows[report_id]
        points = self.reports.series(report_id) if self.reports is not None else []
        if self.transient is not None:  # the running mean from the sampling start (D-181)
            start = self.transient.sampling_start
            running = transient.running_mean_points(points, start) if has_running_mean(report_id) else []
            window.set_transient(points, running, start)
            return
        window.set_data(points, self.mean_window(report_id))

    def _update_charts(self) -> None:
        for report_id in list(self.chart_windows):
            self._fill_chart(report_id)

    def _export_chart(self, report_id: str, kind: str) -> None:
        window = self.chart_windows.get(report_id)
        if window is None:
            return
        name = report_id.replace(":", "_").replace("@", "_") + f"_chart.{kind}"
        path = self.ask_export((self.export_folder or Path.home()) / name, kind)
        if path is None:
            return
        (window.write_png if kind == "png" else window.write_csv)(Path(path))

    def save_charts(self) -> None:
        """At exit: the open charts and their places remembered, then the windows closed."""
        s = settings()
        s.setValue(f"{CHARTS_KEY}/open", list(self.chart_windows))
        for report_id, window in list(self.chart_windows.items()):
            self._save_chart_geometry(report_id, window)
        open_ids = list(self.chart_windows)
        for report_id in open_ids:
            window = self.chart_windows.pop(report_id)
            window.release()
            window.close()
            window.deleteLater()
        s.setValue(f"{CHARTS_KEY}/open", open_ids)
        s.sync()

    def restore_charts(self) -> None:
        """The charts open at the last exit, each where it was (or placed anew when that is on no screen now)."""
        value = settings().value(f"{CHARTS_KEY}/open", [])
        ids = [value] if isinstance(value, str) else list(value or [])
        for report_id in ids:
            if isinstance(report_id, str) and report_id:
                self.open_chart(report_id)

    def configure(self, m: Metrics, t: Theme) -> None:
        self.header.configure(m)
        self.criteria_header.configure(m)
        for button in self.detach_buttons.values():
            button.setFixedSize(m.u, m.u)
        self.chart.configure(m, t)
        self.convergence.configure(m, t)
        self.kpis.configure(m, t)
        self._theme = t
        for window in self.chart_windows.values():
            window.configure(t)
