"""Right column: live residual chart and report slots (empty states until a solver runs)."""

import math
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.core.model import REPORT_SLOTS, AsymptoticCriterion, MeanStableCriterion, StoppingCriteria
from vortexcfd.core.reports import YPLUS, available_reports, report_label
from vortexcfd.foam.convergence import CriterionStatus, evaluate, oscillation, window_stats
from vortexcfd.foam.forces import MASS_WARNING
from vortexcfd.foam.logparse import TimeStep
from vortexcfd.foam.postprocessing import ReportMonitor
from vortexcfd.foam.residuals import ResidualHistory
from vortexcfd.gui.icons import make_glyph
from vortexcfd.gui.panel_widgets import FloatingPanel
from vortexcfd.gui.settings_store import settings
from vortexcfd.gui.theme import DARK, Metrics, Theme, metrics, repolish, residual_style, role_font, set_text_role
from vortexcfd.gui.widgets import SectionHeader

EMPTY = "—"


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
        font = role_font("data")
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
    """Report slot cards: title, chevron menu to assign a report, last value, its windowed mean and
    oscillation (D-118), sparkline, name."""

    NOT_ASSIGNED = "Not assigned"
    ASSIGN_TOOLTIP = ("Assign a report: force coefficients of all walls or of one part (with their pressure "
                      "and viscous parts and the centre of pressure), the mass imbalance, y+ min / avg / max on "
                      "the walls (written at each write interval) or a probe's p and U")
    assigned = Signal(int, object)  # slot (0-based), report id or None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("kpiRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.titles: dict[int, QLabel] = {}
        self.values: dict[int, QLabel] = {}
        self.means: dict[int, QLabel] = {}  # windowed mean and oscillation (D-118)
        self.window_of = lambda _report_id: 100  # iterations averaged for a report (set by the panel)
        self.subtitles: dict[int, QLabel] = {}
        self.sparks: dict[int, Sparkline] = {}
        self.assign_buttons: dict[int, QToolButton] = {}
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
            title = QLabel(f"REPORT {slot}")
            title.setObjectName("kpiTitle")
            button = QToolButton()
            button.setObjectName("chevronBtn")
            button.setToolTip(self.ASSIGN_TOOLTIP)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(self)
            self._fill_menu(menu, slot - 1)
            button.setMenu(menu)
            head.addWidget(title)
            head.addStretch(1)
            head.addWidget(button)
            value = QLabel(EMPTY)
            value.setObjectName("kpiValue")
            mean = QLabel("")
            mean.setObjectName("kpiSub")
            mean.setToolTip("Mean over the last iterations and the half range of the oscillation (max - min) / 2 "
                            "as a share of |mean| (the oscillation check's scale, D-059)")
            spark = Sparkline()
            sub = QLabel(self.NOT_ASSIGNED)
            sub.setObjectName("kpiSub")
            box.addLayout(head)
            box.addWidget(value)
            box.addWidget(mean)
            box.addWidget(spark)
            box.addWidget(sub)
            self.titles[slot], self.values[slot], self.means[slot] = title, value, mean
            self.subtitles[slot], self.assign_buttons[slot] = sub, button
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
            self._fill_menu(self.menus[slot], slot - 1)

    def set_series(self, series_of) -> None:
        """Fill the values from ``series_of(report_id)`` -> [(iteration, value)] (None: no run)."""
        for slot in range(1, REPORT_SLOTS + 1):
            report_id = self.assignments[slot - 1]
            points = series_of(report_id) if (report_id and series_of is not None) else []
            self.values[slot].setText(f"{points[-1][1]:.4g}" if points else EMPTY)
            stats = None
            if points and not report_id.startswith("yplus"):
                stats = window_stats(points, self.window_of(report_id), quantity=report_id)
            self.means[slot].setText(stats.text() if stats is not None else "")
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
        self.has_content = False
        self.always_visible = False  # in its own window (D-156): shown even with nothing to show
        self.empty_label = QLabel(NO_CRITERIA)
        self.empty_label.setObjectName("muted")
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(False)
        self._layout = QVBoxLayout(self)
        self._layout.addWidget(self.empty_label)
        self._layout.addWidget(self.banner)
        self._layout.addWidget(self._grid_host)
        self._layout.addLayout(self._warning_box)
        for col, text in enumerate(self.HEADERS):
            head = QLabel(text)
            head.setObjectName("kpiTitle")
            self.grid.addWidget(head, 0, col)
        self.grid.setColumnStretch(0, 1)
        self._has_criteria = False
        self.set_view(False, ("", None), [], [])

    def set_view(self, has_criteria: bool, banner: tuple[str, str | None], statuses: list[CriterionStatus],
                 warnings: list[str]) -> None:
        """``warnings``: oscillation and mass balance messages (warning colour)."""
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
                set_text_role(label, "data_small")
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
        for text in warnings:
            label = QLabel(text)
            label.setObjectName("checkValue")
            label.setWordWrap(True)
            set_state(label, "warn")
            self._warning_box.addWidget(label)
            self.warnings.append(label)
        self.has_content = has_criteria or bool(warnings)
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


NO_CRITERIA = "No stopping criteria and no warnings (set the criteria under Solver > Stopping criteria)."
# The parts of the column that open in their own window (D-156): key -> (window title, detach tip, dock tip).
DETACHABLE = {
    "residuals": ("Residuals", "Detach the residual chart into its own window (it keeps updating live; close the "
                  "window or click again to dock it)", "Dock the residual chart back into the main window"),
    "criteria": ("Convergence criteria", "Detach the convergence criteria into their own window (they keep "
                 "updating live; close the window or click again to dock them)",
                 "Dock the convergence criteria back into the main window"),
}
WINDOWS_KEY = "monitors/windows"  # per user: <key>/detached, <key>/geometry


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
        self.header = SectionHeader("Residuals & Force Monitors")
        self.header.add_badge("Log10 Scale")
        self.chart = ResidualChart()
        self.convergence = ConvergencePanel()
        self.kpis = ReportSlots()
        self.kpis.assigned.connect(self.slot_assigned)
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
        self._layout = layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(residuals, 1)
        layout.addWidget(criteria)
        layout.addWidget(self.kpis)
        self.convergence.setVisible(False)
        self._sync_criteria_section()
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
        self.case_dir = None
        self.outcome = None
        self.chart.set_series({})
        self.kpis.set_series(None)
        self.set_stage("")
        self._update_convergence()
        self.updated.emit()

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
        self.case_dir = Path(case_dir)
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

    def load_run(self, case_dir: Path, steps, outcome: tuple[str, tuple[str, ...], int | None] | None = None) -> None:
        """Show a finished run (project open): its log's steps and its postProcessing files."""
        self.clear()
        self.history.extend(steps)
        self.reports = ReportMonitor(case_dir)
        self.case_dir = Path(case_dir)
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
        self.kpis.window_of = self.mean_window
        self.kpis.set_series(self.reports.series if self.reports is not None else None)
        self._update_convergence()
        self.updated.emit()

    def mean_window(self, quantity: str) -> int:
        """The iterations a report's mean is taken over: the window of a mean-stable criterion watching
        it, else the oscillation window (D-059, D-118)."""
        stop = self.stopping
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
        if self.stopping is not None:
            names += [c.quantity for c in self.stopping.criteria if isinstance(c, AsymptoticCriterion)]
        names += [r for r in self.kpis.assignments
                  if r and not r.startswith("yplus") and r != "mass_imbalance" and not r.startswith("x_cp")]
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
        warnings = []
        if stop is not None and self.reports is not None:
            floors = {c.quantity: c.effective_floor for c in stop.criteria if isinstance(c, AsymptoticCriterion)}
            for name in self.monitored_quantities():
                osc = oscillation(name, series_of(name), stop.oscillation_window, stop.oscillation_threshold,
                                  floors.get(name))
                if osc is not None:
                    stable = any(isinstance(c, MeanStableCriterion) and c.quantity == name for c in stop.criteria)
                    warnings.append(osc.message(suggest_mean_stable=not stable))
        if self.reports is not None:
            balance = self.reports.mass_balance()
            if balance is not None and balance[2] is not None and abs(balance[2]) > MASS_WARNING:
                warnings.append(mass_warning(balance[2]))
        self.convergence.set_view(has, banner, statuses, warnings)
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
        window = FloatingPanel(DETACHABLE[key][0], lambda k=key: self.dock(k))
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
        index = 1 if key == "residuals" else 2
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
        return list(self.windows.values())

    def configure(self, m: Metrics, t: Theme) -> None:
        self.header.configure(m)
        self.criteria_header.configure(m)
        for button in self.detach_buttons.values():
            button.setFixedSize(m.u, m.u)
        self.chart.configure(m, t)
        self.convergence.configure(m, t)
        self.kpis.configure(m, t)
