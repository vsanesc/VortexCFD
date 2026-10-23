"""Output console: shows the application's log records."""

import html
import logging
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.gui.theme import DARK, Metrics, Theme, set_text_role

APP_LOGGER = "vortexcfd"


class ConsolePanel(QWidget):
    """Tab strip ("Output Console", "Clear log") over a read-only mono log view."""

    log_record = Signal(float, str, str)  # created, level name, message

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme: Theme = DARK
        bar = QWidget()
        bar.setObjectName("consoleBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.tab = QLabel("Output Console")
        self.tab.setObjectName("consoleTab")
        self.clear_button = QPushButton("Clear log")
        self.clear_button.setObjectName("flatBtn")
        self.clear_button.clicked.connect(self.clear)
        self._bar = bar
        self._bar_row = QHBoxLayout(bar)
        self._bar_row.addWidget(self.tab)
        self._bar_row.addStretch(1)
        self._bar_row.addWidget(self.clear_button)
        self.view = QPlainTextEdit()
        self.view.setObjectName("console")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(2000)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.view, 1)
        self.log_record.connect(self._append)

    def configure(self, m: Metrics, t: Theme) -> None:
        self._theme = t
        self._bar.setFixedHeight(m.tab_bar)
        self._bar_row.setContentsMargins(m.s3, 0, m.s3, 0)
        self.tab.setFixedHeight(m.tab_bar - m.line)
        set_text_role(self.view, "control")
        set_text_role(self.clear_button, "control")

    def append_output(self, text: str) -> None:
        """Append one line of tool output verbatim (mono, normal text colour)."""
        self.view.appendHtml(f'<span style="color:{self._theme.text}">{html.escape(text)}</span>')

    def append_error(self, text: str) -> None:
        """Append tool output in the error colour (e.g. a solver crash block), line by line."""
        for line in text.splitlines() or [""]:
            self.view.appendHtml(f'<span style="color:{self._theme.error}">{html.escape(line)}</span>')

    def clear(self) -> None:
        self.view.clear()

    def text(self) -> str:
        return self.view.toPlainText()

    def _append(self, created: float, level: str, message: str) -> None:
        t = self._theme
        color = {"WARNING": t.warning, "ERROR": t.error, "CRITICAL": t.error}.get(level, t.success)
        stamp = time.strftime("%H:%M:%S", time.localtime(created))
        self.view.appendHtml(
            f'<span style="color:{t.muted_text}">[{stamp}]</span> '
            f'<span style="color:{color}">{html.escape(level)}</span> '
            f'<span style="color:{t.text}">{html.escape(message)}</span>'
        )


class ConsoleHandler(logging.Handler):
    """Forwards log records to a ConsolePanel (via a Qt signal, so any thread is safe)."""

    def __init__(self, panel: ConsolePanel) -> None:
        super().__init__(logging.INFO)
        self._panel = panel

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._panel.log_record.emit(record.created, record.levelname, record.getMessage())
        except RuntimeError:  # the panel's C++ object is already gone
            pass


def attach(panel: ConsolePanel) -> ConsoleHandler:
    """Attach a handler for ``panel`` to the application logger and return it."""
    logger = logging.getLogger(APP_LOGGER)
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
    handler = ConsoleHandler(panel)
    logger.addHandler(handler)
    return handler


def detach(handler: ConsoleHandler) -> None:
    logging.getLogger(APP_LOGGER).removeHandler(handler)

