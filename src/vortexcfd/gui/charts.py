"""Small QPainter charts (no plotting library): the y+ histogram of the wall faces (D-061), Cp
along wall sections (D-062), and the mesh study and polar charts with point markers (D-066, D-067)."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from vortexcfd.foam.wall_fields import YPLUS_LABELS, YPlusHistogram
from vortexcfd.gui.theme import DARK, Theme, role_font


def _nice_step(span: float, count: int) -> float:
    raw = max(span, 1e-12) / count
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    """Round tick values covering [lo, hi]."""
    step = _nice_step(hi - lo, count)
    first = math.floor(lo / step) * step
    out, v = [], first
    while v <= hi + 1e-9 * step:
        if v >= lo - 1e-9 * step:
            out.append(round(v, 10))
        v += step
    return out


class YPlusHistogramChart(QWidget):
    """Vertical bars: fraction of wall faces per y+ bin, labelled with the percentage."""

    EMPTY_MESSAGE = "No y+ field yet"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.histogram: YPlusHistogram | None = None
        self._theme: Theme = DARK
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def configure(self, theme: Theme, height: int) -> None:
        self._theme = theme
        self.setFixedHeight(height)
        self.update()

    def set_histogram(self, histogram: YPlusHistogram | None) -> None:
        self.histogram = histogram if histogram is not None and histogram.faces else None
        self.update()

    def bar_texts(self) -> list[str]:
        if self.histogram is None:
            return []
        return [f"{100 * f:.1f}%" for f in self.histogram.fractions]

    def paintEvent(self, event) -> None:
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(role_font("data_small"))
        fm = painter.fontMetrics()
        pad = fm.height() // 2
        if self.histogram is None:
            painter.setPen(QColor(t.muted_text))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.EMPTY_MESSAGE)
            painter.end()
            return
        n = len(YPLUS_LABELS)
        top = pad + fm.height()  # room for the percentage above the tallest bar
        bottom = self.height() - pad - fm.height()  # room for the bin labels
        slot = (self.width() - 2 * pad) / n
        painter.setPen(QPen(QColor(t.border), 1))
        painter.drawLine(QPointF(pad, bottom), QPointF(self.width() - pad, bottom))
        for i, (label, frac, text) in enumerate(zip(YPLUS_LABELS, self.histogram.fractions, self.bar_texts())):
            x = pad + i * slot
            h = (bottom - top) * frac
            bar = QRectF(x + slot * 0.15, bottom - h, slot * 0.7, h)
            painter.fillRect(bar, QColor(t.accent_secondary))
            painter.setPen(QColor(t.text))
            painter.drawText(QRectF(x, bar.top() - fm.height(), slot, fm.height()),
                             int(Qt.AlignmentFlag.AlignCenter), text)
            painter.setPen(QColor(t.muted_text))
            painter.drawText(QRectF(x, bottom, slot, fm.height() + pad), int(Qt.AlignmentFlag.AlignCenter), label)
        painter.end()


class LineChart(QWidget):
    """Lines on linear axes with a legend (Cp against x/c). ``invert_y`` puts negative values up
    (the aerodynamic Cp convention)."""

    EMPTY_MESSAGE = "No sections yet"

    def __init__(self, x_caption: str, y_caption: str, invert_y: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.x_caption, self.y_caption, self.invert_y = x_caption, y_caption, invert_y
        # (legend text, colour, pen style name, [(x, y)])
        self.series: list[tuple[str, str, str, list[tuple[float, float]]]] = []
        # Point markers per series index: [(x, y, flagged)]; a flagged point is drawn hollow in the
        # warning colour (a run that did not meet its stopping criteria).
        self.markers: dict[int, list[tuple[float, float, bool]]] = {}
        self._theme: Theme = DARK
        self.setObjectName("canvas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(320, 240)

    def configure(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_series(self, series, markers: dict[int, list[tuple[float, float, bool]]] | None = None) -> None:
        kept = [i for i, s in enumerate(series) if s[3]]
        self.series = [series[i] for i in kept]
        markers = markers or {}
        self.markers = {new: markers[old] for new, old in enumerate(kept) if old in markers}
        self.update()

    def ranges(self) -> tuple[tuple[float, float], tuple[float, float]]:
        xs = [x for *_, pts in self.series for x, _ in pts]
        ys = [y for *_, pts in self.series for _, y in pts]
        x0, x1 = (min(xs), max(xs)) if xs else (0.0, 1.0)
        y0, y1 = (min(ys), max(ys)) if ys else (0.0, 1.0)
        if x1 == x0:
            x1 = x0 + 1
        if y1 == y0:
            y0, y1 = y0 - 0.5, y1 + 0.5
        return (x0, x1), (y0, y1)

    def paintEvent(self, event) -> None:
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = role_font("data")
        painter.setFont(font)
        fm = painter.fontMetrics()
        pad = fm.height()
        legend_rows = max(1, math.ceil(len(self.series) / 2)) if self.series else 0
        top = pad + legend_rows * fm.height() + pad / 2
        (x0, x1), (y0, y1) = self.ranges()
        xt, yt = ticks(x0, x1), ticks(y0, y1)
        label_w = max((fm.horizontalAdvance(f"{v:g}") for v in yt), default=fm.horizontalAdvance("0"))
        left = pad + fm.height() + pad / 2 + label_w + pad / 2
        right = self.width() - pad
        bottom = self.height() - pad - 2 * fm.height()
        area = QRectF(left, top, right - left, bottom - top)

        def px(x: float, y: float) -> QPointF:
            fx = (x - x0) / (x1 - x0)
            fy = (y - y0) / (y1 - y0)
            return QPointF(area.left() + fx * area.width(),
                           area.top() + (fy if self.invert_y else 1 - fy) * area.height())

        grid = QPen(QColor(t.border), 1)
        for v in yt:
            p = px(x0, v)
            painter.setPen(grid)
            painter.drawLine(QPointF(area.left(), p.y()), QPointF(area.right(), p.y()))
            painter.setPen(QColor(t.muted_text))
            painter.drawText(QRectF(area.left() - label_w - pad / 2, p.y() - fm.height() / 2, label_w, fm.height()),
                             int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{v:g}")
        for v in xt:
            p = px(v, y0)
            painter.setPen(grid)
            painter.drawLine(QPointF(p.x(), area.top()), QPointF(p.x(), area.bottom()))
            painter.setPen(QColor(t.muted_text))
            w = fm.horizontalAdvance(f"{v:g}")
            painter.drawText(QRectF(p.x() - w / 2, area.bottom() + fm.height() / 4, w, fm.height()),
                             int(Qt.AlignmentFlag.AlignCenter), f"{v:g}")
        painter.setPen(QColor(t.muted_text))
        painter.drawText(QRectF(area.left(), area.bottom() + fm.height(), area.width(), fm.height()),
                         int(Qt.AlignmentFlag.AlignCenter), self.x_caption)
        painter.save()
        painter.translate(pad + fm.height() / 2, area.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-area.height() / 2, -fm.height() / 2, area.height(), fm.height()),
                         int(Qt.AlignmentFlag.AlignCenter), self.y_caption)
        painter.restore()
        if not self.series:
            painter.drawText(area, int(Qt.AlignmentFlag.AlignCenter), self.EMPTY_MESSAGE)
            painter.end()
            return
        painter.save()
        painter.setClipRect(area.adjusted(-2, -2, 2, 2))
        for _name, color, style, pts in self.series:
            pen = QPen(QColor(color), 2)
            pen.setStyle(getattr(Qt.PenStyle, style))
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF([px(x, y) for x, y in pts]))
        painter.restore()
        radius = max(3.0, fm.height() / 4)
        for i, points in self.markers.items():
            color = QColor(self.series[i][1])
            for x, y, flagged in points:
                if flagged:
                    painter.setPen(QPen(QColor(t.warning), 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                else:
                    painter.setPen(QPen(color, 1))
                    painter.setBrush(color)
                painter.drawEllipse(px(x, y), radius, radius)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        col_w = (self.width() - 2 * pad) / 2
        for i, (name, color, style, _pts) in enumerate(self.series):
            x = pad + (i % 2) * col_w
            y = pad + (i // 2) * fm.height()
            pen = QPen(QColor(color), 2)
            pen.setStyle(getattr(Qt.PenStyle, style))
            painter.setPen(pen)
            mid = y + fm.height() / 2
            painter.drawLine(QPointF(x, mid), QPointF(x + 2 * fm.height(), mid))
            painter.setPen(QColor(t.text))
            painter.drawText(QRectF(x + 2.5 * fm.height(), y, col_w - 3 * fm.height(), fm.height()),
                             int(Qt.AlignmentFlag.AlignVCenter), name)
        painter.end()
