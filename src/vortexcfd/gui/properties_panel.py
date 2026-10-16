"""Properties panel: edits the node selected in the simulation tree through the Project."""

from typing import get_args

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.gui.theme import DARK, Metrics, Theme, metrics, mono_font

# Allowed units are read from the model so the two never drift apart.
ALLOWED_UNITS: tuple[str, ...] = get_args(Part.model_fields["units"].annotation)


class PropertiesPanel(QWidget):
    """Form for the selected node. Never mutates the model: all edits use the Project API.

    The panel does not subscribe to the project; its owner calls ``refresh()`` on changes.
    """

    message = Signal(str)  # short text for the status bar
    pending_changed = Signal()  # an uncommitted name edit appeared or was resolved

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._kind = "root"
        self._index: int | None = None
        self._name_pending = False  # user typed in the name field without committing yet

        self.name_edit = QLineEdit()
        self.source_label = QLineEdit()  # read-only field (import comes in Phase 3)
        self.source_label.setReadOnly(True)
        self.units_combo = QComboBox()
        self.units_combo.addItems(ALLOWED_UNITS)
        self.info_label = QLabel("No properties yet")
        self.info_label.setObjectName("muted")

        # Rows: label on the left, value box on the right, 1px divider below.
        self._rows: dict[str, QWidget] = {}
        self._row_layouts: list[QHBoxLayout] = []
        self._labels: list[QLabel] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        for key, text, field in (
            ("name", "Name", self.name_edit),
            ("source", "Source file", self.source_label),
            ("units", "Units", self.units_combo),
        ):
            self._layout.addWidget(self._make_row(key, text, field))
        self._layout.addWidget(self.info_label)
        self._layout.addStretch(1)
        self.apply_metrics(metrics(), DARK)

        self.name_edit.editingFinished.connect(self._commit_name)
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.units_combo.currentTextChanged.connect(self._commit_units)
        self.refresh()

    def _make_row(self, key: str, text: str, field: QWidget) -> QWidget:
        row = QWidget()
        row.setObjectName("propRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        label = QLabel(text)
        label.setObjectName("muted")
        box = QHBoxLayout(row)
        box.addWidget(label, 2)
        box.addWidget(field, 3)
        self._rows[key] = row
        self._row_layouts.append(box)
        self._labels.append(label)
        return row

    def apply_metrics(self, m: Metrics, theme: Theme) -> None:
        """Paddings and fonts derived from the font height."""
        for box in self._row_layouts:
            box.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
            box.setSpacing(m.s3)
        mono = mono_font(QApplication.font(), 0.9)
        for widget in (self.name_edit, self.source_label, self.units_combo):
            widget.setFont(mono)
        self.info_label.setContentsMargins(m.s3, m.s3, m.s3, m.s3)

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
        for key in ("source", "units"):
            self._rows[key].setVisible(part is not None)
        self._rows["name"].setVisible(show_name)
        self.info_label.setVisible(not show_name)

    def commit_pending(self) -> None:
        """Commit an uncommitted name edit through the Project API (idempotent).

        A rejected value is reverted and reported through ``message``.
        """
        if self._name_pending:
            self._commit_name()

    @property
    def has_pending(self) -> bool:
        return self._name_pending

    def _on_name_edited(self, _text: str) -> None:
        self._name_pending = True
        self.pending_changed.emit()

    def _commit_name(self) -> None:
        was_pending = self._name_pending
        self._name_pending = False
        if was_pending:
            self.pending_changed.emit()
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
