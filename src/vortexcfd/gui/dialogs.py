"""User dialogs behind a small interface so tests can inject a fake."""

from pathlib import Path
from typing import Literal

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

PROJECT_FILTER = "VortexCFD projects (*.json);;All files (*)"

DiscardChoice = Literal["save", "discard", "cancel"]


class Dialogs:
    """Default implementation using QFileDialog / QMessageBox (modal)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        self.parent = parent

    def ask_open_path(self) -> Path | None:
        name, _ = QFileDialog.getOpenFileName(
            self.parent, "Open project", "", PROJECT_FILTER
        )
        return Path(name) if name else None

    def ask_save_path(self, suggested: Path | None) -> Path | None:
        name, _ = QFileDialog.getSaveFileName(
            self.parent,
            "Save project as",
            str(suggested) if suggested else "",
            PROJECT_FILTER,
        )
        return Path(name) if name else None

    def confirm_discard(self) -> DiscardChoice:
        box = QMessageBox(self.parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText("The project has unsaved changes.")
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            return "save"
        if clicked is discard:
            return "discard"
        return "cancel"
