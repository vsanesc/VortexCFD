"""Small composite widgets shared by the main window panels."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QWidget,
)

from vortexcfd.gui.icons import make_glyph
from vortexcfd.gui.theme import Metrics, Theme, mono_font, section_title_font


def glyph_pixmap(widget: QWidget, name: str, color: str, size: int):
    icon = make_glyph(name, QColor(color), size, widget.devicePixelRatioF())
    return icon.pixmap(QSize(size, size))


class Badge(QLabel):
    """Small mono label with a border (counts, states)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_state(self, state: str) -> None:
        """state: '' (accent_secondary), 'success' or 'warning'."""
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)

    def configure(self) -> None:
        self.setFont(mono_font(QApplication.font(), 0.8))


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
        self.title.setFont(section_title_font(QApplication.font()))
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
        self.setFont(mono_font(QApplication.font(), 0.85))
