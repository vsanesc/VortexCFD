"""Properties panel: edits the node selected in the simulation tree through the Project."""

from typing import get_args

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QWidget

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project

# Allowed units are read from the model so the two never drift apart.
ALLOWED_UNITS: tuple[str, ...] = get_args(Part.model_fields["units"].annotation)


class PropertiesPanel(QWidget):
    """Form for the selected node. Never mutates the model: all edits use the Project API.

    The panel does not subscribe to the project; its owner calls ``refresh()`` on changes.
    """

    message = Signal(str)  # short text for the status bar

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._kind = "root"
        self._index: int | None = None
        self._name_pending = False  # user typed in the name field without committing yet

        self.name_edit = QLineEdit()
        self.source_label = QLabel()
        self.units_combo = QComboBox()
        self.units_combo.addItems(ALLOWED_UNITS)
        self.info_label = QLabel("No properties yet")

        self._form = QFormLayout(self)
        self._form.addRow("Name", self.name_edit)
        self._form.addRow("Source file", self.source_label)
        self._form.addRow("Units", self.units_combo)
        self._form.addRow(self.info_label)

        self.name_edit.editingFinished.connect(self._commit_name)
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.units_combo.currentTextChanged.connect(self._commit_units)
        self.refresh()

    def set_project(self, project: Project) -> None:
        self._project = project
        self._name_pending = False
        self.show_node("root", None)

    def show_node(self, kind: str, index: int | None) -> None:
        if self._name_pending and (kind, index) != (self._kind, self._index):
            self._commit_name()  # commit the old node's pending edit before switching
        self._kind = kind
        self._index = index
        self.refresh()

    def refresh(self) -> None:
        """Repopulate from the project without triggering any commit."""
        sim = self._project.sim
        part: Part | None = None
        if self._kind == "part" and self._index is not None:
            if 0 <= self._index < len(sim.geometry.parts):
                part = sim.geometry.parts[self._index]
        show_name = self._kind == "root" or part is not None
        for widget in (self.name_edit, self.source_label, self.units_combo):
            widget.blockSignals(True)
        try:
            if self._kind == "root":
                self.name_edit.setText(sim.name)
            elif part is not None:
                self.name_edit.setText(part.name)
                self.source_label.setText(part.source_file)
                self.units_combo.setCurrentText(part.units)
        finally:
            for widget in (self.name_edit, self.source_label, self.units_combo):
                widget.blockSignals(False)
        self._form.setRowVisible(self.name_edit, show_name)
        self._form.setRowVisible(self.source_label, part is not None)
        self._form.setRowVisible(self.units_combo, part is not None)
        self._form.setRowVisible(self.info_label, not show_name)

    def _on_name_edited(self, _text: str) -> None:
        self._name_pending = True

    def _commit_name(self) -> None:
        self._name_pending = False
        text = self.name_edit.text()
        try:
            if self._kind == "root":
                self._project.rename(text)
            elif self._kind == "part" and self._index is not None:
                self._project.update_part(self._index, name=text)
        except (ValueError, TypeError, IndexError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()  # reverts a rejected value, normalizes a stripped one

    def _commit_units(self, units: str) -> None:
        try:
            if self._kind == "part" and self._index is not None:
                self._project.update_part(self._index, units=units)
        except (ValueError, TypeError, IndexError) as exc:
            self.message.emit(str(exc))
        self.refresh()
