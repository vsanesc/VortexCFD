"""The Generate domain dialog (D-078): the parts the domain is sized around, its shape and sizes."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from vortexcfd.core.model import DOMAIN_SHAPES, Domain
from vortexcfd.geometry.domain import SHAPE_LABELS

SHAPE_FIELDS = {
    "box": ("upstream", "downstream", "lateral", "vertical"),
    "bullet": ("radius", "downstream"),
    "c_type": ("radius", "downstream", "lateral"),
}
FIELD_LABELS = {"upstream": "Upstream", "downstream": "Downstream", "lateral": "Lateral", "vertical": "Vertical",
                "radius": "Radius"}


class GenerateDomainDialog(QDialog):
    """``fields()`` gives the Domain fields to apply (enabled, shape, sizes, symmetry, parts), or None
    when no part is checked."""

    def __init__(self, part_names: list[str], checked: list[str], domain: Domain,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate domain")
        self.setModal(True)
        self.result_fields: dict | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Size the domain around the parts:"))
        self.parts = QListWidget()
        for name in part_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked)
            self.parts.addItem(item)
        self.parts.itemChanged.connect(lambda _: self._update())
        layout.addWidget(self.parts, 1)
        form = QFormLayout()
        self.shape = QComboBox()
        for shape in DOMAIN_SHAPES:
            self.shape.addItem(SHAPE_LABELS[shape], shape)
        self.shape.setCurrentIndex(DOMAIN_SHAPES.index(domain.shape))
        form.addRow("Shape", self.shape)
        self.spins: dict[str, QDoubleSpinBox] = {}
        self._labels: dict[str, QLabel] = {}
        for key, label in FIELD_LABELS.items():
            spin = QDoubleSpinBox()
            spin.setRange(0.001, 10000.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.5)
            spin.setSuffix(" L")
            spin.setValue(getattr(domain, key))
            self.spins[key] = spin
            self._labels[key] = QLabel(label)
            form.addRow(self._labels[key], spin)
        self.symmetry = QComboBox()
        self.symmetry.addItems(["none", "y_min"])
        self.symmetry.setCurrentText(domain.symmetry)
        form.addRow("Symmetry", self.symmetry)
        layout.addLayout(form)
        self.note = QLabel("L is the largest extent of the checked parts' bounding box.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.addButton("Generate", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.shape.currentIndexChanged.connect(lambda _: self._update())
        self._update()

    def checked_parts(self) -> list[str]:
        return [self.parts.item(i).text() for i in range(self.parts.count())
                if self.parts.item(i).checkState() == Qt.CheckState.Checked]

    def set_checked(self, names: list[str]) -> None:
        for i in range(self.parts.count()):
            item = self.parts.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.text() in names else Qt.CheckState.Unchecked)

    def set_shape(self, shape: str) -> None:
        self.shape.setCurrentIndex(DOMAIN_SHAPES.index(shape))

    def _update(self) -> None:
        shape = self.shape.currentData()
        for key, spin in self.spins.items():
            shown = key in SHAPE_FIELDS[shape]
            spin.setVisible(shown)
            self._labels[key].setVisible(shown)
        self._labels["lateral"].setText("Half-width" if shape == "c_type" else "Lateral")
        self.ok.setEnabled(bool(self.checked_parts()))

    def fields(self) -> dict | None:
        checked = self.checked_parts()
        if not checked:
            return None
        shape = self.shape.currentData()
        out = {"enabled": True, "shape": shape, "symmetry": self.symmetry.currentText(),
               "parts": None if len(checked) == self.parts.count() else checked}
        out.update({key: self.spins[key].value() for key in SHAPE_FIELDS[shape]})
        return out

    def _accept(self) -> None:
        self.result_fields = self.fields()
        if self.result_fields is not None:
            self.accept()
