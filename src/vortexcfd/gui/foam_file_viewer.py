"""Show in OpenFOAM file (D-150): a read-only viewer of the case file a property is written to, scrolled to its entry
and highlighted, with Open in external editor (and the warning that the app regenerates these files)."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.gui.theme import load_appearance, mono_font
from vortexcfd.workflow.foam_entries import Entry, locate

OVERWRITE_WARNING = ("The app writes these files again on Generate Mesh and Run Solver: an edit made here or in an "
                     "external editor is overwritten. Change the value in the properties instead.")
PREVIEW_NOTE = ("The case has not been written yet: this is the file as the app will write it (in case_preview/). "
                "Generate Mesh writes the system/ dictionaries, Run Solver the 0/ fields and the solver settings.")


class FoamFileViewer(QDialog):
    """The entries of one property (a choice when there are several), the file's text, the entry's line selected.
    ``files``: entry -> (path, the real case's file?); ``opener(url) -> bool`` opens the external editor."""

    def __init__(self, title: str, entries: list[Entry], files: dict, parent: QWidget | None = None, opener=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Show in OpenFOAM file: {title}")
        self.entries, self.files = entries, files
        self.opener = opener or (lambda url: QDesktopServices.openUrl(url))
        self.theme = load_appearance()[0]
        layout = QVBoxLayout(self)
        self.entry_combo = QComboBox()
        for e in entries:
            self.entry_combo.addItem(e.text())
        self.entry_combo.setToolTip("Every entry this property is written to (found by the writers themselves)")
        self.entry_combo.currentIndexChanged.connect(lambda i: self.show_entry(i))
        layout.addWidget(self.entry_combo)
        self.path_label = QLabel()
        self.path_label.setObjectName("muted")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)
        self.preview_label = QLabel(PREVIEW_NOTE)
        self.preview_label.setObjectName("checkValue")
        self.preview_label.setProperty("warn", "true")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setFont(mono_font(self.font(), 1.0))
        layout.addWidget(self.text, 1)
        warning = QLabel(OVERWRITE_WARNING)
        warning.setObjectName("checkValue")
        warning.setProperty("warn", "true")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        row = QHBoxLayout()
        self.external_button = QPushButton("Open in external editor")
        self.external_button.setToolTip(OVERWRITE_WARNING)
        self.external_button.clicked.connect(self.open_external)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(self.external_button)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        self.line: int | None = None
        self.resize(900, 640)
        self.show_entry(0)

    def show_entry(self, index: int) -> None:
        if not 0 <= index < len(self.entries):
            return
        entry = self.entries[index]
        path, real = self.files[entry]
        self.path = Path(path)
        self.path_label.setText(str(self.path))
        self.preview_label.setVisible(not real)
        text = self.path.read_text(encoding="utf-8", errors="replace") if self.path.is_file() else ""
        self.text.setPlainText(text)
        self.line = locate(text, entry.keys)
        self._highlight(self.line)

    def _highlight(self, line: int | None) -> None:
        if line is None:
            self.text.setExtraSelections([])
            return
        block = self.text.document().findBlockByLineNumber(line)
        cursor = QTextCursor(block)
        self.text.setTextCursor(cursor)
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(self.theme.accent_dim))
        selection.format.setForeground(QColor(self.theme.accent))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = cursor
        self.text.setExtraSelections([selection])
        self.text.centerCursor()

    def highlighted_text(self) -> str:
        return self.text.document().findBlockByLineNumber(self.line).text() if self.line is not None else ""

    def open_external(self) -> bool:
        return bool(self.opener(QUrl.fromLocalFile(str(self.path))))
