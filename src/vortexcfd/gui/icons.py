"""Tree node icons drawn in code (no image files)."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

# Token (Theme attribute) that tints each node kind.
ICON_TOKENS = {
    "root": "accent",
    "geometry": "text",
    "part": "text",
    "mesh": "muted_text",
    "physics": "warning",
    "solvers": "success",
    "reports": "accent",
}


def make_icon(
    kind: str, color: QColor, size: int, dpr: float = 1.0, selected_color: QColor | None = None
) -> QIcon:
    """Draw a glyph for ``kind`` in a ``size`` x ``size`` logical-pixel icon, crisp at ``dpr``.

    ``selected_color`` tints the variant Qt uses on a selected row (it needs contrast with
    the selection background).
    """
    icon = QIcon(_draw(kind, color, size, dpr))
    if selected_color is not None:
        icon.addPixmap(_draw(kind, selected_color, size, dpr), QIcon.Mode.Selected)
    return icon


def _draw(kind: str, color: QColor, size: int, dpr: float) -> QPixmap:
    px = max(1, round(size * dpr))
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, max(1.2, size / 12))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    m = size * 0.14
    a, b = m, size - m  # glyph box
    c = size / 2
    fill = QColor(color)
    fill.setAlpha(110)
    if kind == "root":  # target: ring with a dot
        p.drawEllipse(QRectF(a, a, b - a, b - a))
        p.setBrush(color)
        r = size * 0.14
        p.drawEllipse(QPointF(c, c), r, r)
    elif kind == "geometry":  # cube outline
        hexagon = QPolygonF(
            [QPointF(c, a), QPointF(b, size * 0.3), QPointF(b, size * 0.7),
             QPointF(c, b), QPointF(a, size * 0.7), QPointF(a, size * 0.3)]
        )
        p.drawPolygon(hexagon)
        p.drawLine(QPointF(c, c), QPointF(c, b))
        p.drawLine(QPointF(c, c), QPointF(a, size * 0.3))
        p.drawLine(QPointF(c, c), QPointF(b, size * 0.3))
    elif kind == "part":  # filled rounded square
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(a, a, b - a, b - a), size * 0.15, size * 0.15)
    elif kind == "mesh":  # grid
        p.drawRect(QRectF(a, a, b - a, b - a))
        for f in (1 / 3, 2 / 3):
            x = a + (b - a) * f
            p.drawLine(QPointF(x, a), QPointF(x, b))
            p.drawLine(QPointF(a, x), QPointF(b, x))
    elif kind == "physics":  # wave
        path = QPainterPath(QPointF(a, c))
        path.cubicTo(size * 0.35, a - size * 0.1, size * 0.4, b + size * 0.1, c, c)
        path.cubicTo(size * 0.6, a - size * 0.1, size * 0.65, b + size * 0.1, b, c)
        p.drawPath(path)
    elif kind == "solvers":  # play triangle
        p.setBrush(color)
        p.drawPolygon(QPolygonF([QPointF(a + size * 0.08, a), QPointF(b, c), QPointF(a + size * 0.08, b)]))
    elif kind == "reports":  # bars
        p.setBrush(color)
        w = (b - a) / 5
        for i, h in enumerate((0.45, 0.8, 0.6)):
            x = a + i * 2 * w
            p.drawRect(QRectF(x, b - (b - a) * h, w, (b - a) * h))
    p.end()
    return pm
