"""A report's chart in a window of its own (D-170): the whole history of a report slot's quantity, zoomed and panned
along the iterations (gui/chart_axis), with its windowed mean as a line and the oscillation's half range around it as
a band, exported to PNG and CSV, and updated live during a run. Opened from a slot's sparkline (double click) or its
"Open chart" button; several can be open at once, each remembered like the monitors' windows (D-156)."""

import csv
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from vortexcfd.core.reports import report_label, report_unit
from vortexcfd.foam.convergence import rolling_window, unique_by_iteration, window_stats
from vortexcfd.foam.residuals import decimate
from vortexcfd.gui.chart_axis import ZoomPanMixin, draw_x_axis, draw_y_axis, y_label_width
from vortexcfd.gui.panel_widgets import FloatingPanel
from vortexcfd.gui.theme import DARK, Theme, metrics, role_font, set_text_role

MAX_DRAWN = 4000  # points drawn per line (the shown range, decimated)
CHART_MIN_U = (20, 10)  # the chart's and its window's minimum sizes, in font heights
WINDOW_MIN_U = (26, 16)
EMPTY_MESSAGE = "No values yet: the report is written while the solver runs"


def has_mean(report_id: str) -> bool:
    """Whether a report gets the windowed mean and the band: every report but y+ (written at write times only)."""
    return not report_id.startswith("yplus")


class ReportChart(ZoomPanMixin, QWidget):
    """The history of one report on linear axes; the mean and band when ``rolling`` is given."""

    def __init__(self, report_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report_id = report_id
        self.setObjectName("canvas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._apply_minimum()
        self._theme: Theme = DARK
        self.points: list[tuple[float, float]] = []
        self.rolling: list[tuple[float, float, float, float]] = []
        self.window = 0
        self.x_ticks = self.y_ticks = None
        self._init_zoom_pan()

    def configure(self, theme: Theme) -> None:
        self._theme = theme
        self._apply_minimum()
        self.update()

    def _apply_minimum(self) -> None:
        u = metrics().u
        self.setMinimumSize(CHART_MIN_U[0] * u, CHART_MIN_U[1] * u)  # follows the interface size

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.ApplicationFontChange):
            self._apply_minimum()

    def set_data(self, points, window: int) -> None:
        self.points = [(float(x), float(v)) for x, v in unique_by_iteration(points)]
        self.window = window
        self.rolling = rolling_window(self.points, window) if has_mean(self.report_id) else []
        self.update()

    def data_x_range(self) -> tuple[float, float] | None:
        if not self.points:
            return None
        lo, hi = self.points[0][0], self.points[-1][0]
        return (lo, hi) if hi > lo else (lo, lo + 1)

    def shown(self) -> tuple[float, float]:
        return self.x_view.range(*(self.data_x_range() or (0.0, 1.0)))

    def y_range(self, x0: float, x1: float) -> tuple[float, float]:
        """The values in the shown iterations (with the band), padded by 5 %."""
        ys = [v for x, v in self.points if x0 <= x <= x1]
        ys += [y for x, _m, lo, hi in self.rolling if x0 <= x <= x1 for y in (lo, hi)]
        if not ys:
            return 0.0, 1.0
        lo, hi = min(ys), max(ys)
        pad = (hi - lo) * 0.05 or abs(hi) * 0.05 or 0.5
        return lo - pad, hi + pad

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(role_font("data"))
        fm = painter.fontMetrics()
        pad = fm.height()
        x0, x1 = self.shown()
        y0, y1 = self.y_range(x0, x1)
        legend = self._legend_layout(fm, pad / 2, self.width() - pad)
        rows = 1 + max((row for *_, row in legend), default=0)
        top = pad / 2 + rows * fm.height() + pad / 2
        bottom = self.height() - pad / 2 - 2.5 * fm.height()
        label_w = y_label_width(y0, y1, max(bottom - top, 1), fm)
        left = pad / 2 + fm.height() + pad / 2 + label_w + pad / 2
        right = self.width() - pad
        area = QRectF(left, top, max(right - left, 1), max(bottom - top, 1))
        self._plot_area = QRectF(area)
        grid, ink = QColor(t.border), QColor(t.muted_text)
        self.y_ticks = draw_y_axis(painter, area, y0, y1, fm, grid, ink, label_w, pad / 2)
        if self.points:
            self.x_ticks = draw_x_axis(painter, area, x0, x1, fm, grid, ink, integer=True)
        painter.setPen(ink)
        painter.drawText(QRectF(area.left(), area.bottom() + 1.25 * fm.height(), area.width(), fm.height()),
                         int(Qt.AlignmentFlag.AlignCenter), "Iteration")
        unit = report_unit(self.report_id)
        painter.save()
        painter.translate(pad / 2 + fm.height() / 2, area.center().y())
        painter.rotate(-90)
        caption = report_label(self.report_id) + (f" [{unit}]" if unit else "")
        painter.drawText(QRectF(-area.height() / 2, -fm.height() / 2, area.height(), fm.height()),
                         int(Qt.AlignmentFlag.AlignCenter), caption)
        painter.restore()
        if not self.points:
            painter.drawText(area, int(Qt.AlignmentFlag.AlignCenter), EMPTY_MESSAGE)
            painter.end()
            return

        def px(x: float, y: float) -> QPointF:
            return QPointF(area.left() + (x - x0) / max(x1 - x0, 1e-12) * area.width(),
                           area.bottom() - (y - y0) / max(y1 - y0, 1e-12) * area.height())

        painter.save()
        painter.setClipRect(area)
        shown = [r for r in self.rolling if x0 <= r[0] <= x1]
        if shown:
            step = max(1, len(shown) // MAX_DRAWN)
            shown = shown[::step] + ([shown[-1]] if (len(shown) - 1) % step else [])
            band = QColor(t.accent)
            band.setAlphaF(0.16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(band)
            painter.drawPolygon(QPolygonF([px(x, hi) for x, _m, _lo, hi in shown]
                                          + [px(x, lo) for x, _m, lo, _hi in reversed(shown)]))
        visible = [p for p in self.points if x0 <= p[0] <= x1]
        line = [(x, v) for x, v in decimate(visible, MAX_DRAWN)] if visible else []
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(t.accent), 1.5))
        painter.drawPolyline(QPolygonF([px(x, v) for x, v in line]))
        if shown:
            pen = QPen(QColor(t.text), 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF([px(x, m) for x, m, _lo, _hi in shown]))
        painter.restore()
        # the legend above the plot, wrapped onto more rows when the window is narrow
        for color, style, text, x, row in legend:
            y = pad / 2 + row * fm.height()
            w = fm.horizontalAdvance(text)
            if color is None:
                band = QColor(t.accent)
                band.setAlphaF(0.16)
                painter.fillRect(QRectF(x, y + fm.height() / 4, 2 * fm.height(), fm.height() / 2), band)
            else:
                pen = QPen(color, 1.5)
                pen.setStyle(style)
                painter.setPen(pen)
                painter.drawLine(QPointF(x, y + fm.height() / 2), QPointF(x + 2 * fm.height(), y + fm.height() / 2))
            painter.setPen(QColor(t.text))
            painter.drawText(QRectF(x + 2.5 * fm.height(), y, w, fm.height()), int(Qt.AlignmentFlag.AlignVCenter),
                             text)
        painter.end()

    def _legend_layout(self, fm, left: float, right: float) -> list:
        """(colour, pen style, text, x, row) of each legend entry: as many per row as fit."""
        t = self._theme
        entries = [(QColor(t.accent), Qt.PenStyle.SolidLine, report_label(self.report_id))]
        if self.rolling:
            entries += [(QColor(t.text), Qt.PenStyle.DashLine, f"mean over {self.window} it."),
                        (None, None, "\u00b1 half range")]
        out, x, row = [], left, 0
        for color, style, text in entries:
            width = 2.5 * fm.height() + fm.horizontalAdvance(text)
            if x > left and x + width > right:
                x, row = left, row + 1
            out.append((color, style, text, x, row))
            x += width + fm.height()
        return out


class ReportChartWindow(FloatingPanel):
    """A report chart's window: its name and latest statistics, Export PNG / CSV, Show all, and the chart."""

    export_requested = Signal(str, str)  # report id, "png" or "csv"

    def __init__(self, report_id: str, on_close) -> None:
        super().__init__(f"Report chart: {report_label(report_id)}", on_close, WINDOW_MIN_U)
        self.report_id = report_id
        body = QWidget()
        box = QVBoxLayout(body)
        row = QHBoxLayout()
        self.stats = QLabel()
        self.stats.setObjectName("muted")
        self.stats.setWordWrap(True)
        self.png_button = QPushButton("Export PNG…")
        self.png_button.setToolTip("The chart as shown (zoom included) as a PNG image")
        self.csv_button = QPushButton("Export CSV…")
        self.csv_button.setToolTip("The whole history: iteration, value, windowed mean and the band's limits")
        self.all_button = QPushButton("Show all")
        self.all_button.setToolTip("The whole history again (as a double click on the chart)")
        row.addWidget(self.stats, 1)
        for button in (self.all_button, self.png_button, self.csv_button):
            row.addWidget(button)
        box.addLayout(row)
        self.chart = ReportChart(report_id)
        box.addWidget(self.chart, 1)
        self.take(body)
        self.png_button.clicked.connect(lambda: self.export_requested.emit(self.report_id, "png"))
        self.csv_button.clicked.connect(lambda: self.export_requested.emit(self.report_id, "csv"))
        self.all_button.clicked.connect(lambda: (self.chart.x_view.reset(), self.chart.update()))
        set_text_role(self.stats, "data_small")

    def configure(self, theme: Theme) -> None:
        self.chart.configure(theme)

    def set_data(self, points, window: int) -> None:
        self.chart.set_data(points, window)
        stats = window_stats(points, window, quantity=self.report_id) if has_mean(self.report_id) and points else None
        latest = f"latest {points[-1][1]:.5g} at iteration {points[-1][0]:g}" if points else "no values yet"
        self.stats.setText(latest + (f"; {stats.text()}" if stats is not None else ""))

    def write_png(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.chart.grab().save(str(path), "PNG")

    def write_csv(self, path: Path) -> None:
        """Every iteration: its value and, from the window's end on, the windowed mean and the band."""
        rolling = {x: (m, lo, hi) for x, m, lo, hi in self.chart.rolling}
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["iteration", self.report_id, "windowed_mean", "band_low", "band_high"])
            for x, v in self.chart.points:
                m = rolling.get(x)
                w.writerow([f"{x:g}", repr(v), *(("", "", "") if m is None else (repr(m[0]), repr(m[1]), repr(m[2])))])
