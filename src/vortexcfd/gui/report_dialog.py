"""File > Create Report's section choice (D-136): a check box per report section; the choice is saved in the
project (Simulation.results.report_omit)."""

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from vortexcfd.core.model import REPORT_SECTIONS


class ReportSectionsDialog(QDialog):
    def __init__(self, omit: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create report")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Sections in the report (remembered for this project):"))
        self.boxes: dict[str, QCheckBox] = {}
        for key, title in REPORT_SECTIONS.items():
            box = QCheckBox(title)
            box.setChecked(key not in omit)
            layout.addWidget(box)
            self.boxes[key] = box
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create report")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        for box in self.boxes.values():
            box.toggled.connect(self._update_ok)

    def _update_ok(self) -> None:
        self._ok.setEnabled(any(b.isChecked() for b in self.boxes.values()))  # an empty report is not offered

    def omitted(self) -> list[str]:
        return [k for k, b in self.boxes.items() if not b.isChecked()]
