"""Small composite widgets shared by the main window panels."""

import math

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QAction, QColor, QFontMetrics, QPainter, QTextDocument
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
from vortexcfd.gui.theme import Metrics, Theme, repolish, role_font, set_text_role


def set_invalid(widget: QWidget, reason: str | None, tooltip: str = "") -> None:
    """Inline validation: a highlighted border (the ``invalid`` property in the stylesheet) and the reason as the
    widget's tooltip; ``reason`` None clears it and restores ``tooltip``."""
    widget.setProperty("invalid", reason is not None)
    widget.setToolTip(reason if reason is not None else tooltip)
    repolish(widget)


def glyph_pixmap(widget: QWidget, name: str, color: str, size: int):
    icon = make_glyph(name, QColor(color), size, widget.devicePixelRatioF())
    return icon.pixmap(QSize(size, size))


def wrapped_height(label: QLabel, width: int | None = None) -> int:
    """A word-wrapped label's height for its text at ``width`` (default: its own), padding and border included:
    measured as the label lays the text out (QLabel.heightForWidth overestimates a padded label)."""
    margins = label.contentsMargins()
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(label.font())
    document.setPlainText(label.text())
    width = label.width() if width is None else width
    document.setTextWidth(max(width - margins.left() - margins.right(), 1))
    return math.ceil(document.size().height()) + margins.top() + margins.bottom()


def discard(widget: QWidget) -> None:
    """Remove a widget taken out of its layout: hidden at once (a deleteLater'd widget is drawn where it was until the
    event loop deletes it, over the rows that replace it), then deleted."""
    widget.hide()
    widget.deleteLater()


class ElidedLabel(QLabel):
    """A one-line label that elides its text to its width (D-155); ``text()`` is the full text, and when elided the
    full text leads the tooltip (before any tooltip of its own)."""

    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle) -> None:
        super().__init__()
        self.full_text = ""
        self._mode = mode
        self._tip = ""
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:
        self.full_text = text
        self._elide()

    def text(self) -> str:
        return self.full_text

    def setToolTip(self, tip: str) -> None:
        self._tip = tip
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width() if self.width() > 1 else 10_000
        shown = self.fontMetrics().elidedText(self.full_text, self._mode, max(width, 0))
        QLabel.setText(self, shown)
        tip = self._tip if shown == self.full_text else "\n".join(t for t in (self.full_text, self._tip) if t)
        QLabel.setToolTip(self, tip)


class Badge(QLabel):
    """Small mono label with a border; optionally with a status dot inside the pill.

    Where room is short (the top bar, D-155) a badge can be compact: ``set_compact(1)`` shows its short text,
    ``set_compact(2)`` (a badge with a dot) only the dot; the full text is then its tooltip. ``text()`` is always the
    full text."""

    def __init__(self, text: str = "", with_dot: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("badge")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)  # never squeezed: compact instead
        self._with_dot = with_dot
        self._state = ""
        self._theme: Theme | None = None
        self._dot_d = 0
        self._pad = 0
        self._full = ""
        self._short = ""
        self._compact = 0
        self.setProperty("dot", "true" if with_dot else "false")
        self.setText(text)

    def setText(self, text: str, short: str = "") -> None:
        self._full, self._short = text, short
        self._show_text()

    def text(self) -> str:
        return self._full

    def set_compact(self, level: int) -> None:
        """0: the full text; 1: the short text (if any); 2: only the dot (a badge with a dot)."""
        self._compact = level
        self._show_text()

    def _show_text(self) -> None:
        if self._compact >= 2 and self._with_dot:
            shown = ""
        elif self._compact >= 1 and self._short:
            shown = self._short
        else:
            shown = self._full
        super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")

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
        self.ensurePolished()
        # The height from the badge role's font (descenders included) and the stylesheet's padding and border, fixed
        # so a tight row (the top bar) cannot squeeze the text.
        margins = self.contentsMargins()
        self.setFixedHeight(QFontMetrics(role_font("badge")).height() + margins.top() + margins.bottom())
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
