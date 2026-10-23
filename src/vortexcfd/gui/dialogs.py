"""User dialogs behind a small interface so tests can inject a fake."""

from pathlib import Path
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

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

    def ask_snapshot_name(self, suggested: str) -> str | None:
        """The name of a results snapshot (D-149), or None (cancelled)."""
        text, ok = QInputDialog.getText(self.parent, "Save results snapshot", "Snapshot name:", text=suggested)
        return text if ok and text.strip() else None

    def show_foam_file(self, title: str, entries, files) -> None:
        """Show in OpenFOAM file (D-150): the read-only viewer."""
        from vortexcfd.gui.foam_file_viewer import FoamFileViewer

        FoamFileViewer(title, entries, files, self.parent).exec()

    def confirm(self, title: str, text: str) -> bool:
        """A yes / no question (No is the default)."""
        answer = QMessageBox.question(self.parent, title, text,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def show_text(self, title: str, text: str) -> None:
        """A read-only text, selectable (e.g. the mesh report)."""
        box = QMessageBox(self.parent)
        box.setWindowTitle(title)
        box.setText(text)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.exec()

    def show_error(self, title: str, text: str) -> None:
        QMessageBox.critical(self.parent, title, text)

    def show_warning(self, title: str, text: str) -> None:
        QMessageBox.warning(self.parent, title, text)

    def ask_export_image(self, suggested: Path):
        """File > Export Image (D-133): an ExportSpec (file, size, transparency) or None (cancelled)."""
        from vortexcfd.gui.image_export import ExportImageDialog

        dialog = ExportImageDialog(suggested, self.parent)
        return dialog.spec() if dialog.exec() else None

    def ask_csv_path(self, suggested: Path | None) -> Path | None:
        name, _ = QFileDialog.getSaveFileName(
            self.parent, "Export sections", str(suggested) if suggested else "", "CSV files (*.csv)"
        )
        return Path(name) if name else None

    def ask_line_export(self, suggested: Path, kind: str) -> Path | None:
        """Where to export a line plot (D-136): ``kind`` "png" (the chart) or "csv" (the samples)."""
        name, _ = QFileDialog.getSaveFileName(
            self.parent, "Export line plot", str(suggested),
            "PNG images (*.png)" if kind == "png" else "CSV files (*.csv)")
        return Path(name) if name else None

    def ask_report_sections(self, omit: list[str]) -> list[str] | None:
        """The report sections to leave out (D-136), starting from ``omit``; None: cancelled."""
        from vortexcfd.gui.report_dialog import ReportSectionsDialog

        dialog = ReportSectionsDialog(omit, self.parent)
        return dialog.omitted() if dialog.exec() else None

    def ask_import_path(self) -> Path | None:
        name, _ = QFileDialog.getOpenFileName(
            self.parent, "Import geometry", "", SURFACE_FILTER
        )
        return Path(name) if name else None

    def ask_airfoil(self):
        """File > Import Airfoil (D-121): (the .dat file, scale, trailing-edge closure) or None (cancelled)."""
        name, _ = QFileDialog.getOpenFileName(self.parent, "Import airfoil", "",
                                              "Airfoil coordinates (*.dat *.txt);;All files (*)")
        if not name:
            return None
        scale, ok = QInputDialog.getDouble(self.parent, "Import airfoil", "Scale (the chord of a file in chord units, m):",
                                           1.0, 1e-6, 1e6, 6)
        if not ok:
            return None
        closure, ok = QInputDialog.getItem(
            self.parent, "Import airfoil", "Trailing edge: blunt keeps an open trailing edge (closed by a base); "
            "sharp moves the surfaces to meet:", ["blunt", "sharp"], 0, False)
        return (Path(name), scale, closure) if ok else None

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
        hint = (f"Detected: {detected}" if detected else
                "Not detected (paraview on PATH, /mnt/c/Program Files/ParaView*); ParaView is optional")
        text, ok = QInputDialog.getText(
            self.parent, "Preferences",
            f"ParaView executable (paraview, or a Windows paraview.exe as a WSL path; empty = detect).\n{hint}",
            text=current,
        )
        return text if ok else None

    # -- start screen, new simulation, presets (D-077) -------------------------------------------

    def ask_start(self, recent):
        """The Start dialog: ("new", None), ("open", None), ("recent", path) or None (closed)."""
        from vortexcfd.gui.start_dialogs import StartDialog

        dialog = StartDialog(recent, self.parent)
        dialog.exec()
        return dialog.choice

    def ask_new_simulation(self, store):
        """The New simulation dialog: a NewSimulationSpec, or None (cancelled)."""
        from vortexcfd.gui.start_dialogs import NewSimulationDialog

        dialog = NewSimulationDialog(store, self.parent)
        dialog.exec()
        return dialog.result_spec

    def ask_duplicate(self, current_name: str, current_parent: Path):
        """Save As (duplicate project, D-079): (name, parent folder) or None (cancelled)."""
        from vortexcfd.gui.start_dialogs import DuplicateProjectDialog

        dialog = DuplicateProjectDialog(current_name, current_parent, self.parent)
        dialog.exec()
        return dialog.result_target

    def ask_preset_name(self, suggested: str) -> str | None:
        text, ok = QInputDialog.getText(self.parent, "Save as preset",
                                        "Preset name (analysis type, domain and mesh settings only):", text=suggested)
        return text if ok else None

    def confirm_overwrite_preset(self, name: str) -> bool:
        answer = QMessageBox.question(
            self.parent, "Save as preset", f"A preset named '{name}' already exists. Replace it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def manage_presets(self, store) -> None:
        from vortexcfd.gui.start_dialogs import ManagePresetsDialog

        ManagePresetsDialog(store, self.parent).exec()

    def ask_generate_domain(self, part_names, checked, domain):
        """The Generate domain dialog (D-078): the Domain fields to apply, or None (cancelled)."""
        from vortexcfd.gui.domain_dialog import GenerateDomainDialog

        dialog = GenerateDomainDialog(part_names, checked, domain, self.parent)
        dialog.exec()
        return dialog.result_fields

    def ask_surface_prep(self, strategies, default):
        """The surface preparation strategy (D-093): a key of ``strategies`` [(key, label)], or None. The dialog says
        what the operation does and what each strategy means (D-146)."""
        dialog = SurfacePrepDialog(strategies, default, self.parent)
        return dialog.strategy() if dialog.exec() else None

    def show_about(self) -> None:
        from vortexcfd import __version__

        QMessageBox.about(self.parent, "About VortexCFD",
                          f"VortexCFD {__version__}\n\nAn integrated CFD workflow on top of OpenFOAM ESI v2606.\n"
                          "Licence: GPL-3.0-or-later.")

    def show_openfoam(self, check):
        """The OpenFOAM dialog (D-137): (the new check, the bashrc to remember or None) when the user chose a usable
        installation, None when closed."""
        from vortexcfd.gui.openfoam_dialog import OpenFOAMDialog

        dialog = OpenFOAMDialog(check, self.parent)
        if not dialog.exec():
            return None
        return dialog.result_check(), dialog.configured_path()

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


class SurfacePrepDialog(QDialog):
    """Surface Preparation: the explanation, one choice per strategy with what it does, Run / Cancel (D-146)."""

    def __init__(self, strategies, default, parent: QWidget | None = None) -> None:
        from vortexcfd.workflow.surface_prep import EXPLANATION, STRATEGY_HELP

        super().__init__(parent)
        self.setWindowTitle("Surface Preparation")
        layout = QVBoxLayout(self)
        intro = QLabel(EXPLANATION)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.buttons: dict[str, QRadioButton] = {}
        for key, label in strategies:
            radio = QRadioButton(label)
            radio.setChecked(key == default)
            help_text = QLabel(STRATEGY_HELP.get(key, ""))
            help_text.setObjectName("muted")
            help_text.setWordWrap(True)
            help_text.setContentsMargins(24, 0, 0, 8)
            layout.addWidget(radio)
            layout.addWidget(help_text)
            self.buttons[key] = radio
        if not any(b.isChecked() for b in self.buttons.values()) and self.buttons:
            next(iter(self.buttons.values())).setChecked(True)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        run = box.addButton("Run", QDialogButtonBox.ButtonRole.AcceptRole)
        run.setObjectName("primaryBtn")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        width = 34 * self.fontMetrics().height()
        self.setFixedWidth(width)
        inner = width - layout.contentsMargins().left() - layout.contentsMargins().right()
        for label in self.findChildren(QLabel):  # a dialog's layout does not ask wrapped labels for their height
            label.setMinimumHeight(label.heightForWidth(inner - label.contentsMargins().left()))

    def strategy(self) -> str | None:
        return next((key for key, b in self.buttons.items() if b.isChecked()), None)
