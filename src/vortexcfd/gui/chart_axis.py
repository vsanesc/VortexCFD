"""The axes of the QPainter charts (the residual chart and the report charts, D-169): ticks by core/ticks (1-2-5
steps, minor ticks, thousands separators, as many as the labels leave room for), a light grid, and zoom and pan of
the x axis (the iterations) with the wheel and a drag; a double click shows the whole history again."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from vortexcfd.core import ticks as tk

ZOOM_STEP = 1.25
MIN_SPAN = 4.0  # the narrowest view: 4 iterations
TIP = "Wheel: zoom the iterations; drag: pan; double-click: show the whole history"


class XView:
    """The shown x range of a chart: None follows the data (all of it, and the latest iterations as they come);
    zoomed or panned, a fixed range inside the data."""

    def __init__(self) -> None:
        self.view: tuple[float, float] | None = None

    @property
    def follows(self) -> bool:
        return self.view is None

    def range(self, lo: float, hi: float) -> tuple[float, float]:
        if self.view is None:
            return lo, hi
        v0, v1 = self.view
        return (v0, v1) if v1 > v0 else (lo, hi)

    def zoom(self, factor: float, at: float, lo: float, hi: float) -> None:
        """Scale the shown span by ``factor`` (< 1 zooms in) about ``at``, kept inside the data [lo, hi]."""
        v0, v1 = self.range(lo, hi)
        span = max((v1 - v0) * factor, min(MIN_SPAN, hi - lo))
        if span >= hi - lo:
            self.view = None
            return
        new0 = at - (at - v0) * span / max(v1 - v0, 1e-12)
        self.view = self._inside(new0, new0 + span, lo, hi)

    def pan(self, dx: float, lo: float, hi: float) -> None:
        """Move the shown range by ``dx`` data units, kept inside the data."""
        if self.view is None:
            return
        v0, v1 = self.view
        self.view = self._inside(v0 + dx, v1 + dx, lo, hi)

    def reset(self) -> None:
        self.view = None

    @staticmethod
    def _inside(v0: float, v1: float, lo: float, hi: float) -> tuple[float, float]:
        span = v1 - v0
        if v0 < lo:
            v0, v1 = lo, lo + span
        if v1 > hi:
            v0, v1 = hi - span, hi
        return max(v0, lo), min(v1, hi)


def draw_x_axis(painter: QPainter, area: QRectF, lo: float, hi: float, fm, grid: QColor, ink: QColor,
                integer: bool = True) -> tk.Ticks:
    """Vertical grid lines at the major ticks, short marks at the minor ones, and the labels under ``area``."""
    ticks = tk.fitted_ticks(lo, hi, area.width(), fm.horizontalAdvance, integer)
    span = max(hi - lo, 1e-12)

    def x_of(v: float) -> float:
        return area.left() + (v - lo) / span * area.width()

    minor = QColor(grid)
    minor.setAlphaF(grid.alphaF() * 0.45)
    painter.setPen(QPen(minor, 1))
    for v in ticks.minor:
        x = x_of(v)
        painter.drawLine(QPointF(x, area.bottom()), QPointF(x, area.bottom() - fm.height() / 4))
    painter.setPen(QPen(grid, 1))
    for v in ticks.major:
        x = x_of(v)
        painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
    painter.setPen(ink)
    for v, text in zip(ticks.major, ticks.labels()):
        w = fm.horizontalAdvance(text)
        x = min(max(x_of(v) - w / 2, area.left() - w / 2), area.right() - w / 2)
        painter.drawText(QRectF(x, area.bottom() + fm.height() / 4, w, fm.height()),
                         int(Qt.AlignmentFlag.AlignCenter), text)
    return ticks


def draw_y_axis(painter: QPainter, area: QRectF, lo: float, hi: float, fm, grid: QColor, ink: QColor,
                label_w: float, gap: float) -> tk.Ticks:
    """Horizontal grid lines at the major ticks of a linear y axis and their labels left of ``area``."""
    ticks = tk.fitted_ticks(lo, hi, area.height(), lambda _t: fm.height(), False, gap_px=fm.height(), max_target=8)
    span = max(hi - lo, 1e-12)
    painter.setPen(QPen(grid, 1))
    for v in ticks.major:
        y = area.bottom() - (v - lo) / span * area.height()
        painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
    painter.setPen(ink)
    for v, text in zip(ticks.major, ticks.labels()):
        y = area.bottom() - (v - lo) / span * area.height()
        painter.drawText(QRectF(area.left() - gap - label_w, y - fm.height() / 2, label_w, fm.height()),
                         int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), text)
    return ticks


def y_label_width(lo: float, hi: float, length_px: float, fm) -> float:
    """The width of the widest y label of a linear axis ``length_px`` high."""
    ticks = tk.fitted_ticks(lo, hi, length_px, lambda _t: fm.height(), False, gap_px=fm.height(), max_target=8)
    return max((fm.horizontalAdvance(t) for t in ticks.labels()), default=fm.horizontalAdvance("0"))


class ZoomPanMixin:
    """Wheel zoom, drag pan and double-click reset of a QPainter chart's x axis. The chart sets ``self.x_view``
    (XView), ``self._plot_area`` (the plot rectangle of its last paint) and ``data_x_range()``."""

    def _init_zoom_pan(self) -> None:
        self.x_view = XView()
        self._plot_area = QRectF()
        self._drag_from: float | None = None
        self.setToolTip(TIP)

    def data_x_range(self) -> tuple[float, float] | None:  # pragma: no cover - the chart's
        raise NotImplementedError

    def _x_at(self, px: float) -> float | None:
        data = self.data_x_range()
        if data is None or self._plot_area.width() <= 0:
            return None
        lo, hi = self.x_view.range(*data)
        return lo + (px - self._plot_area.left()) / self._plot_area.width() * (hi - lo)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt API)
        data = self.data_x_range()
        at = self._x_at(event.position().x())
        if data is None or at is None:
            event.ignore()
            return
        factor = 1 / ZOOM_STEP if event.angleDelta().y() > 0 else ZOOM_STEP
        self.x_view.zoom(factor, at, *data)
        event.accept()
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.position().x()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        data = self.data_x_range()
        if self._drag_from is not None and data is not None and self._plot_area.width() > 0:
            lo, hi = self.x_view.range(*data)
            dx = (self._drag_from - event.position().x()) / self._plot_area.width() * (hi - lo)
            self._drag_from = event.position().x()
            self.x_view.pan(dx, *data)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_from = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.x_view.reset()
        self.update()
        super().mouseDoubleClickEvent(event)
