"""Small composite widgets shared by the main window panels."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QAction, QColor, QPainter
from PySide6.QtWidgets import (
    QLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from vortexcfd.gui.icons import make_glyph
from vortexcfd.gui.theme import Metrics, Theme, repolish, set_text_role


def set_invalid(widget: QWidget, reason: str | None, tooltip: str = "") -> None:
    """Inline validation: a highlighted border (the ``invalid`` property in the stylesheet) and the reason as the
    widget's tooltip; ``reason`` None clears it and restores ``tooltip``."""
    widget.setProperty("invalid", reason is not None)
    widget.setToolTip(reason if reason is not None else tooltip)
    repolish(widget)


def glyph_pixmap(widget: QWidget, name: str, color: str, size: int):
    icon = make_glyph(name, QColor(color), size, widget.devicePixelRatioF())
    return icon.pixmap(QSize(size, size))


class Badge(QLabel):
    """Small mono label with a border; optionally with a status dot inside the pill."""

    def __init__(self, text: str = "", with_dot: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._with_dot = with_dot
        self._state = ""
        self._theme: Theme | None = None
        self._dot_d = 0
        self._pad = 0
        self.setProperty("dot", "true" if with_dot else "false")

    def set_state(self, state: str) -> None:
        """state: '' (accent), 'success', 'warning' or 'error'."""
        self._state = state
        self.setProperty("state", state)
        repolish(self)
        self.update()

    def dot_color(self) -> str | None:
        """Token color of the dot for the current state (None if no dot)."""
        if not self._with_dot or self._theme is None:
            return None
        return {"success": self._theme.success, "warning": self._theme.warning,
                "error": self._theme.error}.get(
            self._state, self._theme.accent
        )

    def configure(self, m: Metrics | None = None, t: Theme | None = None) -> None:
        set_text_role(self, "badge")
        if m is not None and t is not None:
            self._theme, self._dot_d, self._pad = t, m.dot, m.s2 + m.line
        self.updateGeometry()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        color = self.dot_color()
        if color is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        d = self._dot_d
        painter.drawEllipse(self._pad, (self.height() - d) // 2, d, d)
        painter.end()


class DotButton(QPushButton):
    """Checkable button with a small dot on the left: muted when off, accent when on."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("dotBtn")
        self._theme: Theme | None = None
        self._dot_d = 0
        self._pad = 0

    def configure(self, m: Metrics, t: Theme) -> None:
        self._theme, self._dot_d, self._pad = t, m.dot, m.s3 + m.line

    def dot_color(self) -> str | None:
        if self._theme is None:
            return None
        return self._theme.accent if self.isChecked() else self._theme.muted_text

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        color = self.dot_color()
        if color is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        d = self._dot_d
        painter.drawEllipse(self._pad, (self.height() - d) // 2, d, d)
        painter.end()


class SectionHeader(QWidget):
    """Uppercase title, optional badge and optional trailing widget, 1px bottom border."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sectionHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.title = QLabel(title.upper())
        self.title.setObjectName("sectionTitle")
        self.badge: Badge | None = None
        self.row = QHBoxLayout(self)
        self.row.addWidget(self.title)
        self.row.addStretch(1)

    def add_badge(self, text: str) -> Badge:
        self.badge = Badge(text)
        self.row.addWidget(self.badge)
        return self.badge

    def configure(self, m: Metrics) -> None:
        self.setFixedHeight(m.header + m.s2)
        self.title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.row.setContentsMargins(m.s3, 0, m.s3, 0)
        self.row.setSpacing(m.s2)
        set_text_role(self.title, "section_title")
        if self.badge is not None:
            self.badge.configure()


class SearchField(QLineEdit):
    """Filter box with a drawn magnifier."""

    def __init__(self, placeholder: str = "Search...", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self._action = QAction(self)
        self.addAction(self._action, QLineEdit.ActionPosition.LeadingPosition)

    def configure(self, m: Metrics, t: Theme) -> None:
        self._action.setIcon(
            make_glyph("search", QColor(t.muted_text), m.u, self.devicePixelRatioF())
        )
        set_text_role(self, "control")


class FlowLayout(QLayout):
    """Left-to-right layout that wraps its items onto further rows when they do not fit (the Qt
    flow layout example). Items keep their size hints; ``stretch_last`` pushes the last item to the
    right end of its row (used for a trailing button)."""

    def __init__(self, parent: QWidget | None = None, stretch_last: bool = False) -> None:
        super().__init__(parent)
        self._items: list = []
        self._stretch_last = stretch_last
        self._hspace = 0
        self._vspace = 0

    def set_spacing(self, horizontal: int, vertical: int) -> None:
        self._hspace, self._vspace = horizontal, vertical
        self.invalidate()

    def addItem(self, item) -> None:  # noqa: N802 (Qt API)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _visible(self) -> list:
        return [i for i in self._items if not (i.widget() is not None and i.widget().isHidden())]

    def _layout(self, rect, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = area.x(), area.y(), 0
        rows: list[list] = [[]]
        for item in self._visible():
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y, row_h = area.x(), y + row_h + self._vspace, 0
                rows.append([])
            rows[-1].append((item, QPoint(x, y), hint))
            x += hint.width() + self._hspace
            row_h = max(row_h, hint.height())
        if apply:
            for row in rows:
                for k, (item, pos, hint) in enumerate(row):
                    if self._stretch_last and row is rows[-1] and k == len(row) - 1 and item is self._visible()[-1]:
                        pos = QPoint(max(pos.x(), area.right() + 1 - hint.width()), pos.y())
                    item.setGeometry(QRect(pos, hint))
        return y + row_h - rect.y() + m.bottom()
