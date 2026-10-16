"""Right column: residual chart area (empty until a solver runs) and KPI cards."""


from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.gui.theme import DARK, Metrics, Theme, mono_font
from vortexcfd.gui.widgets import SectionHeader

EMPTY = "—"
# Decades shown on the log10 axis: 1e0 down to 1e-6.
DECADES = tuple(range(0, -7, -1))


class ResidualChart(QWidget):
    """Log-scale axis with grid and labels, drawn with QPainter. Empty for now."""

    EMPTY_MESSAGE = "No solver run yet"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("canvas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme: Theme = DARK
        self._margin = 0
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def configure(self, m: Metrics, t: Theme) -> None:
        self._theme, self._margin = t, m.s3
        self.update()

    def axis_labels(self) -> list[str]:
        return [f"1e{d}" for d in DECADES]

    def paintEvent(self, event) -> None:
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = mono_font(QApplication.font(), 0.8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        label_w = fm.horizontalAdvance("1e-6")
        top = self._margin + fm.height() / 2
        bottom = self.height() - self._margin - fm.height() / 2
        left = self._margin + label_w + self._margin
        right = self.width() - self._margin
        n = len(DECADES) - 1
        grid = QPen(QColor(t.border), 1)
        for i, d in enumerate(DECADES):
            y = top + (bottom - top) * i / n
            painter.setPen(grid)
            painter.drawLine(int(left), round(y), int(right), round(y))
            painter.setPen(QColor(t.muted_text))
            painter.drawText(
                QRectF(self._margin, y - fm.height() / 2, label_w, fm.height()),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"1e{d}",
            )
        painter.setFont(QApplication.font())
        area = QRectF(left, top, right - left, bottom - top)
        text_w = painter.fontMetrics().horizontalAdvance(self.EMPTY_MESSAGE) + 2 * self._margin
        box = QRectF(0, 0, text_w, painter.fontMetrics().height() + self._margin)
        box.moveCenter(area.center())
        painter.fillRect(box, QColor(t.canvas))  # keep the message clear of the grid lines
        painter.setPen(QColor(t.muted_text))
        painter.drawText(area, int(Qt.AlignmentFlag.AlignCenter), self.EMPTY_MESSAGE)
        painter.end()


class KpiRow(QWidget):
    """Three KPI cells (title over value); every value is "—" until a solver runs."""

    TITLES = (("cl", "LIFT COEFF (CL)"), ("cd", "DRAG COEFF (CD)"), ("yplus", "MAX WALL Y+"))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("kpiRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.titles: dict[str, QLabel] = {}
        self.values: dict[str, QLabel] = {}
        self._cells: list[QWidget] = []
        self._layouts: list[QVBoxLayout] = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for i, (key, title) in enumerate(self.TITLES):
            cell = QWidget()
            cell.setObjectName("kpiCell")
            cell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            cell.setProperty("last", "true" if i == len(self.TITLES) - 1 else "false")
            box = QVBoxLayout(cell)
            t_label = QLabel(title)
            t_label.setObjectName("kpiTitle")
            v_label = QLabel(EMPTY)
            v_label.setObjectName("kpiValue")
            box.addWidget(t_label)
            box.addWidget(v_label)
            self.titles[key], self.values[key] = t_label, v_label
            self._cells.append(cell)
            self._layouts.append(box)
            row.addWidget(cell, 1)

    def configure(self, m: Metrics) -> None:
        for box in self._layouts:
            box.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
            box.setSpacing(m.s2)
        small = mono_font(QApplication.font(), 0.75)
        big = mono_font(QApplication.font(), 1.5)
        big.setBold(True)
        for label in self.titles.values():
            label.setFont(small)
        for label in self.values.values():
            label.setFont(big)


class MonitorsPanel(QWidget):
    """Header + residual chart + KPI cards."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header = SectionHeader("Residuals & Force Monitors")
        self.header.add_badge("Log10 Scale")
        self.chart = ResidualChart()
        self.kpis = KpiRow()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.chart, 1)
        layout.addWidget(self.kpis)

    def configure(self, m: Metrics, t: Theme) -> None:
        self.header.configure(m)
        self.chart.configure(m, t)
        self.kpis.configure(m)


