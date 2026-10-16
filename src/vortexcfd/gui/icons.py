"""UI glyphs drawn in code (no image files)."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

def make_glyph(name: str, color: QColor, size: int, dpr: float = 1.0) -> QIcon:
    """Small UI glyphs drawn in code, crisp at ``dpr``.

    Names: logo, dot, folder, eye, eye_off, chevron_down, chevron_right, search, sidebar,
    plus, minus.
    """
    px = max(1, round(size * dpr))
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, max(1.2, size / 10))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    m = size * 0.2
    a, b, c = m, size - m, size / 2
    if name == "logo":  # filled rounded square
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(size * 0.1, size * 0.1, size * 0.8, size * 0.8), size * 0.22, size * 0.22)
    elif name == "dot":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        r = size * 0.2
        p.drawEllipse(QPointF(c, c), r, r)
    elif name == "folder":
        path = QPainterPath(QPointF(a, size * 0.3))
        path.lineTo(size * 0.42, size * 0.3)
        path.lineTo(size * 0.5, size * 0.4)
        path.lineTo(b, size * 0.4)
        path.lineTo(b, size * 0.74)
        path.lineTo(a, size * 0.74)
        path.closeSubpath()
        p.drawPath(path)
    elif name in ("eye", "eye_off"):
        eye = QPainterPath(QPointF(size * 0.08, c))
        eye.quadTo(c, size * 0.12, size * 0.92, c)
        eye.quadTo(c, size * 0.88, size * 0.08, c)
        p.drawPath(eye)
        r = size * 0.12
        p.drawEllipse(QPointF(c, c), r, r)
        if name == "eye_off":
            p.drawLine(QPointF(size * 0.15, size * 0.85), QPointF(size * 0.85, size * 0.15))
    elif name == "chevron_down":
        p.drawPolyline(QPolygonF([QPointF(a, size * 0.38), QPointF(c, size * 0.62), QPointF(b, size * 0.38)]))
    elif name == "chevron_right":
        p.drawPolyline(QPolygonF([QPointF(size * 0.38, a), QPointF(size * 0.62, c), QPointF(size * 0.38, b)]))
    elif name == "search":
        r = size * 0.28
        p.drawEllipse(QPointF(size * 0.43, size * 0.43), r, r)
        p.drawLine(QPointF(size * 0.64, size * 0.64), QPointF(size * 0.84, size * 0.84))
    elif name == "sidebar":
        p.drawRoundedRect(QRectF(size * 0.12, size * 0.2, size * 0.76, size * 0.6), size * 0.12, size * 0.12)
        p.drawLine(QPointF(size * 0.4, size * 0.2), QPointF(size * 0.4, size * 0.8))
    elif name in ("plus", "minus"):
        p.drawLine(QPointF(a, c), QPointF(b, c))
        if name == "plus":
            p.drawLine(QPointF(c, a), QPointF(c, b))
    p.end()
    return QIcon(pm)
