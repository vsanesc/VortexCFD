"""Right column: residual chart area (empty until a solver runs) and KPI cards."""


from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.gui.icons import make_glyph
from vortexcfd.gui.theme import DARK, Metrics, Theme, mono_font
from vortexcfd.gui.widgets import SectionHeader

EMPTY = "—"
# Decades shown on the log10 axis: 1e0 down to 1e-6.
DECADES = tuple(range(0, -7, -1))


class ResidualChart(QWidget):
    """Log-scale axis with grid and labels, drawn with QPainter. Empty for now."""

    EMPTY_MESSAGE = "No solver run yet"
    X_CAPTION = "Iteration"
    Y_CAPTION = "Residual"

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
        bottom = self.height() - self._margin - fm.height() * 1.5  # room for the x caption
        left = self._margin + fm.height() + self._margin + label_w + self._margin  # y caption
        right = self.width() - self._margin
        n = len(DECADES) - 1
        grid = QPen(QColor(t.border), 1)
        for i, d in enumerate(DECADES):
            y = top + (bottom - top) * i / n
            painter.setPen(grid)
            painter.drawLine(int(left), round(y), int(right), round(y))
            painter.setPen(QColor(t.muted_text))
            painter.drawText(
                QRectF(left - self._margin - label_w, y - fm.height() / 2, label_w, fm.height()),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"1e{d}",
            )
        painter.setFont(QApplication.font())
        area = QRectF(left, top, right - left, bottom - top)
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
            QRectF(left, bottom + fm.height() / 2, right - left, fm.height()),
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


REPORT_SLOTS = 3  # number of report slots in the monitors panel (the one place to change it)


class ReportSlots(QWidget):
    """Report slot cards: title, disabled assign button, value "—" and "Not assigned"."""

    NOT_ASSIGNED = "Not assigned"
    ASSIGN_TOOLTIP = "Assign a report (Phase 6)"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("kpiRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.titles: dict[int, QLabel] = {}
        self.values: dict[int, QLabel] = {}
        self.subtitles: dict[int, QLabel] = {}
        self.assign_buttons: dict[int, QToolButton] = {}
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
            button.setEnabled(False)
            button.setToolTip(self.ASSIGN_TOOLTIP)
            button.setCursor(Qt.CursorShape.ForbiddenCursor)
            head.addWidget(title)
            head.addStretch(1)
            head.addWidget(button)
            value = QLabel(EMPTY)
            value.setObjectName("kpiValue")
            sub = QLabel(self.NOT_ASSIGNED)
            sub.setObjectName("kpiSub")
            box.addLayout(head)
            box.addWidget(value)
            box.addWidget(sub)
            self.titles[slot], self.values[slot] = title, value
            self.subtitles[slot], self.assign_buttons[slot] = sub, button
            self._layouts.append(box)
            row.addWidget(cell, 1)

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
        icon = make_glyph("chevron_down", QColor(t.disabled_text),
                          m.u, self.devicePixelRatioF())
        for button in self.assign_buttons.values():
            button.setIcon(icon)
            button.setIconSize(QSize(m.u, m.u))


class MonitorsPanel(QWidget):
    """Header + residual chart + KPI cards."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header = SectionHeader("Residuals & Force Monitors")
        self.header.add_badge("Log10 Scale")
        self.chart = ResidualChart()
        self.kpis = ReportSlots()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.chart, 1)
        layout.addWidget(self.kpis)

    def configure(self, m: Metrics, t: Theme) -> None:
        self.header.configure(m)
        self.chart.configure(m, t)
        self.kpis.configure(m, t)


