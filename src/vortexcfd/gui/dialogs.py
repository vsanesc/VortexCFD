"""User dialogs behind a small interface so tests can inject a fake."""

from pathlib import Path
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from vortexcfd.gui.properties_panel import ALLOWED_UNITS

SURFACE_FILTER = ("Geometry (*.stl *.obj *.ply *.step *.stp *.iges *.igs *.brep *.brp);;"
                  "Surface files (*.stl *.obj *.ply);;CAD files (*.step *.stp *.iges *.igs *.brep *.brp);;All files (*)")
SAVE_FILTER = "VortexCFD project (*.vcfd)"
OPEN_FILTER = "VortexCFD projects (*.vcfd *.json);;All files (*)"  # .json: projects before D-076

DiscardChoice = Literal["save", "discard", "cancel"]


class Dialogs:
    """Default implementation using QFileDialog / QMessageBox (modal)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        self.parent = parent

    def ask_open_path(self) -> Path | None:
        name, _ = QFileDialog.getOpenFileName(
            self.parent, "Open project", "", OPEN_FILTER
        )
        return Path(name) if name else None

    def ask_save_path(self, suggested: Path | None) -> Path | None:
        """The project file to save to. The dialog never confirms an overwrite itself: the window
        checks the target first (never a non-project file) and then asks ``confirm_overwrite``."""
        name, _ = QFileDialog.getSaveFileName(
            self.parent,
            "Save project as",
            str(suggested) if suggested else "",
            SAVE_FILTER,
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        return Path(name) if name else None

    def confirm_overwrite(self, path: Path) -> bool:
        """An existing VortexCFD project would be replaced: ask first."""
        answer = QMessageBox.question(
            self.parent, "Save project", f"{path.name} already exists. Replace this project?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def show_error(self, title: str, text: str) -> None:
        QMessageBox.critical(self.parent, title, text)

    def ask_csv_path(self, suggested: Path | None) -> Path | None:
        name, _ = QFileDialog.getSaveFileName(
            self.parent, "Export sections", str(suggested) if suggested else "", "CSV files (*.csv)"
        )
        return Path(name) if name else None

    def ask_import_path(self) -> Path | None:
        name, _ = QFileDialog.getOpenFileName(
            self.parent, "Import geometry", "", SURFACE_FILTER
        )
        return Path(name) if name else None

    def ask_units(self) -> str | None:
        units, ok = QInputDialog.getItem(
            self.parent, "Import surface", "Units of the file:", list(ALLOWED_UNITS), 0, False
        )
        return units if ok else None

    def ask_solids_mode(self, file_name: str, solids: list[str]) -> str | None:
        """A file with several solids: "regions" (one Part, a region per solid; the default),
        "parts" (one Part per solid) or None (cancel the import)."""
        box = QMessageBox(self.parent)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Import surface")
        shown = ", ".join(solids[:8]) + (", ..." if len(solids) > 8 else "")
        box.setText(f"{file_name} has {len(solids)} solids: {shown}.")
        regions = box.addButton("One part, a region per solid", QMessageBox.ButtonRole.AcceptRole)
        parts = box.addButton("One part per solid", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(regions)
        box.exec()
        clicked = box.clickedButton()
        return "regions" if clicked is regions else "parts" if clicked is parts else None

    def show_repair_report(self, part: str, method: str, rows: list[tuple[str, str, str]],
                           notes: list[str]) -> None:
        """The before / after table of a repair (modal, information only)."""
        cells = "".join(f"<tr><td>{q}</td><td align='right'>{b}</td><td align='right'>{a}</td></tr>"
                        for q, b, a in rows)
        text = (f"<p>Repair of <b>{part}</b>: {method}</p><table cellspacing='6'>"
                f"<tr><th></th><th>Before</th><th>After</th></tr>{cells}</table>"
                + "".join(f"<p>{n}</p>" for n in notes))
        box = QMessageBox(self.parent)
        box.setWindowTitle("Repair report")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(text)
        box.exec()

    def ask_paraview_path(self, current: str, detected: Path | None) -> str | None:
        """Preferences: the ParaView executable (empty text = detect automatically)."""
        hint = f"Detected: {detected}" if detected else "Not detected under /mnt/c/Program Files/ParaView*"
        text, ok = QInputDialog.getText(
            self.parent, "Preferences",
            f"ParaView executable (paraview.exe, WSL path; empty = detect).\n{hint}", text=current,
        )
        return text if ok else None

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
