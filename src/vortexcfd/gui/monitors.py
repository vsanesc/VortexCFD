"""Right column: live residual chart and report slots (empty states until a solver runs)."""

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.core.model import REPORT_IDS, REPORT_SLOTS, AsymptoticCriterion, StoppingCriteria
from vortexcfd.foam.convergence import CriterionStatus, Oscillation, evaluate, oscillation
from vortexcfd.foam.logparse import TimeStep
from vortexcfd.foam.postprocessing import REPORT_LABELS, ReportMonitor
from vortexcfd.foam.residuals import ResidualHistory
from vortexcfd.gui.icons import make_glyph
from vortexcfd.gui.theme import DARK, Metrics, Theme, mono_font, residual_style
from vortexcfd.gui.widgets import SectionHeader

EMPTY = "—"
# Decades shown on the log10 axis without data: 1e0 down to 1e-6 (data can widen the range).
DECADES = tuple(range(0, -7, -1))
REFRESH_MS = 250  # while a run is live, the chart and the report values refresh at most this often
SPARK_POINTS = 200  # points drawn in a report sparkline (the last ones)


def _pen_style(name: str) -> Qt.PenStyle:
    return getattr(Qt.PenStyle, name)


def nice_ticks(lo: float, hi: float, count: int = 4) -> list[float]:
    """About ``count`` round tick values covering [lo, hi]."""
    span = max(hi - lo, 1e-12)
    raw = span / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    first = math.ceil(lo / step) * step
    ticks, v = [], first
    while v <= hi + 1e-9 * span:
        ticks.append(round(v, 10))
        v += step
    return ticks


class ResidualChart(QWidget):
    """Initial residual per iteration on a log10 axis (one line per field, legend), drawn with
    QPainter. The x axis always ends at the latest iteration (autoscroll)."""

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
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def configure(self, m: Metrics, t: Theme) -> None:
        self._theme, self._margin, self._line = t, m.s3, m.line
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

    def x_range(self) -> tuple[float, float]:
        xs = [x for s in self.series.values() for x, _ in s]
        lo, hi = min(xs), max(xs)
        return (lo, hi) if hi > lo else (lo, lo + 1)

    def legend_entries(self) -> list[tuple[str, str, str]]:
        """(field, colour, pen style name) in the order the fields appeared."""
        return [(name, *residual_style(self._theme, name)) for name in self.series]

    def paintEvent(self, event) -> None:
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = mono_font(QApplication.font(), 0.8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        decades = self.decades()
        label_w = max(fm.horizontalAdvance(f"1e{d}") for d in decades)
        legend_h = fm.height() + self._margin if self.series else 0
        top = self._margin + legend_h + fm.height() / 2
        x_labels_h = fm.height() if self.series else 0
        bottom = self.height() - self._margin - fm.height() * 1.5 - x_labels_h  # room for the x caption
        left = self._margin + fm.height() + self._margin + label_w + self._margin  # y caption
        right = self.width() - self._margin
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
            painter.setFont(QApplication.font())
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

        # x tick labels under the plot area
        painter.setPen(QColor(t.muted_text))
        for tick in nice_ticks(x0, x1):
            p = to_px(tick, 10.0 ** hi)
            text = f"{tick:g}"
            w = fm.horizontalAdvance(text)
            painter.drawText(QRectF(p.x() - w / 2, area.bottom() + fm.height() / 4, w, fm.height()),
                             int(Qt.AlignmentFlag.AlignCenter), text)
        painter.save()
        painter.setClipRect(area.adjusted(-2, -2, 2, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for name, color, style in self.legend_entries():
            pen = QPen(QColor(color), 2 * self._line)
            pen.setStyle(_pen_style(style))
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF([to_px(x, v) for x, v in self.series[name] if v > 0]))
        painter.restore()
        # legend: one row above the plot, a line sample in the series style + the name in text ink
        x = area.left()
        y = self._margin
        sample = 2 * fm.height()
        for name, color, style in self.legend_entries():
            pen = QPen(QColor(color), 2 * self._line)
            pen.setStyle(_pen_style(style))
            painter.setPen(pen)
            mid = y + fm.height() / 2
            painter.drawLine(QPointF(x, mid), QPointF(x + sample, mid))
            painter.setPen(QColor(t.text))
            w = fm.horizontalAdvance(name)
            painter.drawText(QRectF(x + sample + self._margin / 2, y, w, fm.height()),
                             int(Qt.AlignmentFlag.AlignVCenter), name)
            x += sample + self._margin / 2 + w + self._margin


class Sparkline(QWidget):
    """A tiny line of the last values of a report (no axes)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: list[float] = []
        self._color = QColor(DARK.accent)
        self._line = 1

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
    """Report slot cards: title, chevron menu to assign a report, last value, sparkline, name."""

    NOT_ASSIGNED = "Not assigned"
    ASSIGN_TOOLTIP = ("Assign a report: Cd, Cl and Cm (pitch) from forceCoeffs, y+ min / avg / max on the "
                      "walls from the yPlus function object (written at each write interval)")
    assigned = Signal(int, object)  # slot (0-based), report id or None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("kpiRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.titles: dict[int, QLabel] = {}
        self.values: dict[int, QLabel] = {}
        self.subtitles: dict[int, QLabel] = {}
        self.sparks: dict[int, Sparkline] = {}
        self.assign_buttons: dict[int, QToolButton] = {}
        self.menus: dict[int, QMenu] = {}
        self.assignments: list[str | None] = [None] * REPORT_SLOTS
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
            title = QLabel(f"REPORT {slot}")
            title.setObjectName("kpiTitle")
            button = QToolButton()
            button.setObjectName("chevronBtn")
            button.setToolTip(self.ASSIGN_TOOLTIP)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = self._build_menu(slot - 1)
            button.setMenu(menu)
            head.addWidget(title)
            head.addStretch(1)
            head.addWidget(button)
            value = QLabel(EMPTY)
            value.setObjectName("kpiValue")
            spark = Sparkline()
            sub = QLabel(self.NOT_ASSIGNED)
            sub.setObjectName("kpiSub")
            box.addLayout(head)
            box.addWidget(value)
            box.addWidget(spark)
            box.addWidget(sub)
            self.titles[slot], self.values[slot] = title, value
            self.subtitles[slot], self.assign_buttons[slot] = sub, button
            self.sparks[slot], self.menus[slot] = spark, menu
            self._layouts.append(box)
            row.addWidget(cell, 1)

    def _build_menu(self, index: int) -> QMenu:
        menu = QMenu(self)
        group = QActionGroup(menu)
        for report_id in (None, *REPORT_IDS):
            action = QAction(REPORT_LABELS[report_id] if report_id else self.NOT_ASSIGNED, menu)
            action.setCheckable(True)
            action.setData(report_id)
            action.setChecked(report_id is None)
            group.addAction(action)
            menu.addAction(action)
            action.triggered.connect(lambda _=False, r=report_id: self.assigned.emit(index, r))
        return menu

    def set_assignments(self, assignments: list[str | None]) -> None:
        """Show which report each slot carries (values are cleared until ``set_series``)."""
        self.assignments = list(assignments)
        for slot in range(1, REPORT_SLOTS + 1):
            report_id = self.assignments[slot - 1]
            self.subtitles[slot].setText(REPORT_LABELS[report_id] if report_id else self.NOT_ASSIGNED)
            for action in self.menus[slot].actions():
                action.setChecked(action.data() == report_id)

    def set_series(self, series_of) -> None:
        """Fill the values from ``series_of(report_id)`` -> [(iteration, value)] (None: no run)."""
        for slot in range(1, REPORT_SLOTS + 1):
            report_id = self.assignments[slot - 1]
            points = series_of(report_id) if (report_id and series_of is not None) else []
            self.values[slot].setText(f"{points[-1][1]:.4g}" if points else EMPTY)
            self.sparks[slot].set_values([v for _, v in points])

    def configure(self, m: Metrics, t: Theme) -> None:
        for box in self._layouts:
            box.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
            box.setSpacing(m.s2)
        small = mono_font(QApplication.font(), 0.75)
        big = mono_font(QApplication.font(), 1.5)
        big.setBold(True)
        for label in (*self.titles.values(), *self.subtitles.values()):
            label.setFont(small)
        for label in self.values.values():
            label.setFont(big)
        for spark in self.sparks.values():
            spark.configure(m, t)
        icon = make_glyph("chevron_down", QColor(t.muted_text), m.u, self.devicePixelRatioF())
        for button in self.assign_buttons.values():
            button.setIcon(icon)
            button.setIconSize(QSize(m.u, m.u))


def set_state(label: QLabel, state: str | None) -> None:
    """Colour a value label: "ok" (success), "warn", "error" or None (text)."""
    for prop in ("ok", "warn", "error"):
        label.setProperty(prop, "true" if state == prop else "false")
    label.style().unpolish(label)
    label.style().polish(label)


# Banner texts (D-058). The run states are those of foam/solver_run.py.
BANNER_RUNNING = "Solving: stopping criteria not met yet"
BANNER_LIMIT = "Iteration limit reached without meeting the criteria"
BANNER_STOPPED = "Stopped by the user before the criteria were met"
BANNER_CRASHED = "The solver crashed before the criteria were met"
BANNER_NO_RUN = "No solver run yet"


def banner_for(state: str | None, stopped_by: tuple[str, ...], iterations: int | None) -> tuple[str, str | None]:
    """(text, colour state) of the convergence banner for a run state (None: running)."""
    if state is None:
        return BANNER_RUNNING, None
    if state == "converged":
        at = f" at iteration {iterations}" if iterations else ""
        if stopped_by:
            return f"Criteria met{at}: " + "; ".join(stopped_by), "ok"
        return f"Converged{at} (SIMPLE residual control)", "ok"
    if state == "iteration_limit":
        return BANNER_LIMIT, "warn"
    if state == "stopped":
        return BANNER_STOPPED, "warn"
    if state == "crashed":
        return BANNER_CRASHED, "error"
    return BANNER_NO_RUN, None


class ConvergencePanel(QWidget):
    """Convergence banner, per-criterion state and oscillation warnings (D-058, D-059).

    The banner and the criteria table are shown only when stopping criteria exist; oscillation
    warnings whenever a monitored quantity oscillates.
    """

    HEADERS = ("Criterion", "Value", "Threshold", "Satisfied")

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
        self._layout = QVBoxLayout(self)
        self._layout.addWidget(self.banner)
        self._layout.addWidget(self._grid_host)
        self._layout.addLayout(self._warning_box)
        for col, text in enumerate(self.HEADERS):
            head = QLabel(text)
            head.setObjectName("kpiTitle")
            self.grid.addWidget(head, 0, col)
        self.grid.setColumnStretch(0, 1)
        self._has_criteria = False
        self._font = mono_font(QApplication.font(), 0.75)
        self.set_view(False, ("", None), [], [])

    def set_view(self, has_criteria: bool, banner: tuple[str, str | None], statuses: list[CriterionStatus],
                 oscillations: list[Oscillation]) -> None:
        self._has_criteria = has_criteria
        self.banner.setText(banner[0])
        set_state(self.banner, banner[1])
        self.banner.setVisible(has_criteria)
        self._grid_host.setVisible(has_criteria and bool(statuses))
        while len(self.rows) > len(statuses):
            for label in self.rows.pop():
                self.grid.removeWidget(label)
                label.deleteLater()
        while len(self.rows) < len(statuses):
            r = len(self.rows) + 1
            labels = tuple(QLabel() for _ in self.HEADERS)
            for col, label in enumerate(labels):
                label.setObjectName("checkValue")
                label.setFont(self._font)
                if col == 0:  # elided by the layout instead of widening the column
                    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                self.grid.addWidget(label, r, col)
            self.rows.append(labels)  # type: ignore[arg-type]
        for labels, status in zip(self.rows, statuses):
            name, value, threshold, met = labels
            name.setText(status.label or status.description)
            name.setToolTip(status.description + (f" ({status.note})" if status.note else ""))
            value.setText(EMPTY if status.value is None else f"{status.value:.3g}")
            threshold.setText(f"{status.threshold:.3g}")
            met.setText("yes" if status.satisfied else "no")
            met.setToolTip(status.note)
            set_state(met, "ok" if status.satisfied else None)
        for label in self.warnings:
            self._warning_box.removeWidget(label)
            label.deleteLater()
        self.warnings = []
        for osc in oscillations:
            label = QLabel(osc.message())
            label.setObjectName("checkValue")
            label.setWordWrap(True)
            set_state(label, "warn")
            self._warning_box.addWidget(label)
            self.warnings.append(label)
        self.setVisible(has_criteria or bool(oscillations))

    @property
    def statuses_text(self) -> list[tuple[str, str, str, str]]:
        return [tuple(label.text() for label in row) for row in self.rows]  # type: ignore[misc]

    def configure(self, m: Metrics, t: Theme) -> None:
        self._layout.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
        self._layout.setSpacing(m.s1)
        self.grid.setHorizontalSpacing(m.s2)
        self.grid.setVerticalSpacing(m.s1)
        self._font = mono_font(QApplication.font(), 0.75)
        small = mono_font(QApplication.font(), 0.75)
        for i in range(self.grid.count()):
            widget = self.grid.itemAt(i).widget()
            if widget is not None:
                widget.setFont(small)
        self.banner.setFont(QApplication.font())


class MonitorsPanel(QWidget):
    """Header + residual chart + report slots, fed live while the solver runs.

    ``add_step`` is called from GUI-thread slots (queued signals); the postProcessing files are
    polled on a GUI-thread timer (they are tailed: each poll reads only the new bytes).
    """

    slot_assigned = Signal(int, object)  # slot (0-based), report id or None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header = SectionHeader("Residuals & Force Monitors")
        self.header.add_badge("Log10 Scale")
        self.chart = ResidualChart()
        self.convergence = ConvergencePanel()
        self.kpis = ReportSlots()
        self.kpis.assigned.connect(self.slot_assigned)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.chart, 1)
        layout.addWidget(self.convergence)
        layout.addWidget(self.kpis)
        self.history = ResidualHistory()
        self.reports: ReportMonitor | None = None
        # The criteria the shown run uses, and its outcome: (state, stopped_by, iterations);
        # state None = running, outcome None = no run.
        self.stopping: StoppingCriteria | None = None
        self.outcome: tuple[str | None, tuple[str, ...], int | None] | None = None
        self._dirty = False
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

    def clear(self) -> None:
        """No run: empty chart and report values."""
        self._timer.stop()
        self.history.clear()
        self.reports = None
        self.outcome = None
        self.chart.set_series({})
        self.kpis.set_series(None)
        self._update_convergence()

    def set_stopping(self, stopping: StoppingCriteria | None) -> None:
        """The stopping criteria to evaluate (the run's, or the project's when no run is going)."""
        if stopping != self.stopping:
            self.stopping = stopping
            self._dirty = True
            self.refresh()

    def start_run(self, case_dir: Path, stopping: StoppingCriteria | None = None) -> None:
        """A solver run starts in ``case_dir``: forget the previous run, poll its files."""
        self.clear()
        self.stopping = stopping
        self.reports = ReportMonitor(case_dir)
        self.outcome = (None, (), None)
        self._timer.start()
        self._update_convergence()

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

    def load_run(self, case_dir: Path, steps, outcome: tuple[str, tuple[str, ...], int | None] | None = None) -> None:
        """Show a finished run (project open): its log's steps and its postProcessing files."""
        self.clear()
        self.history.extend(steps)
        self.reports = ReportMonitor(case_dir)
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
        self.chart.set_series(self.history.decimated())
        self.kpis.set_series(self.reports.series if self.reports is not None else None)
        self._update_convergence()

    def monitored_quantities(self) -> list[str]:
        """Quantities checked for oscillation: the asymptotic criteria's and the assigned report
        slots' (y+ is written only at write times and is left out)."""
        names: list[str] = []
        if self.stopping is not None:
            names += [c.quantity for c in self.stopping.criteria if isinstance(c, AsymptoticCriterion)]
        names += [r for r in self.kpis.assignments if r and not r.startswith("yplus")]
        return list(dict.fromkeys(names))

    def _update_convergence(self) -> None:
        stop = self.stopping
        has = stop is not None and bool(stop.criteria)
        series_of = self.reports.series if self.reports is not None else (lambda _q: [])
        statuses = evaluate(stop, self.history.series, series_of) if has and self.outcome is not None else []
        if self.outcome is None:
            banner = (BANNER_NO_RUN, None)
        else:
            banner = banner_for(*self.outcome)
        oscillations = []
        if stop is not None and self.reports is not None:
            for name in self.monitored_quantities():
                osc = oscillation(name, series_of(name), stop.oscillation_window, stop.oscillation_threshold)
                if osc is not None:
                    oscillations.append(osc)
        self.convergence.set_view(has, banner, statuses, oscillations)

    def configure(self, m: Metrics, t: Theme) -> None:
        self.header.configure(m)
        self.chart.configure(m, t)
        self.convergence.configure(m, t)
        self.kpis.configure(m, t)
