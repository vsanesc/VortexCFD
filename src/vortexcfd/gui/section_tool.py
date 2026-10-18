"""Sections tool of the Results Scene: Cp against x/c on wall sections, one line per surface and
section, CSV export (D-062)."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from vortexcfd.gui.charts import LineChart
from vortexcfd.gui.sections import AXES, NEGATIVE_SIDES, Section, cut_section, export_csv, stations
from vortexcfd.gui.theme import DARK, Theme, residual_style

# Section colours cycle through the residual chart's three hue families (D-049); the positive side
# (upper, +y side) solid, the negative side (lower, -y side) dashed (a single line: solid).
_COLOURS = ("p", "Ux", "k")


def _colour(theme: Theme, i: int) -> str:
    return residual_style(theme, _COLOURS[i % len(_COLOURS)])[0]


class SectionTool(QDialog):
    """Non-modal window: plane axis, one position or N stations, the Cp chart and Export CSV."""

    export_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sections: Cp along x/c")
        self.setModal(False)
        self.patches: dict = {}
        self.u_ref = 1.0
        self.bounds: tuple[float, ...] | None = None  # parts' bounds
        self.sections: list[Section] = []
        self._theme = DARK
        self.axis = QComboBox()
        self.axis.addItems(list(AXES))
        self.axis.setToolTip("Normal of the cutting planes (y: spanwise, the default)")
        self.single = QRadioButton("Position")
        self.multi = QRadioButton("Stations")
        self.single.setChecked(True)
        self.position = QDoubleSpinBox()
        self.position.setDecimals(4)
        self.position.setRange(-1e6, 1e6)
        self.position.setSuffix(" m")
        self.count = QSpinBox()
        self.count.setRange(1, 20)
        self.count.setValue(3)
        self.count.setToolTip("Evenly spaced between the parts' extremes along the axis (extremes excluded)")
        self.compute = QPushButton("Cut")
        self.export = QPushButton("Export CSV")
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.chart = LineChart("x/c", "Cp (negative up)", invert_y=True)
        row = QHBoxLayout()
        for w in (QLabel("Axis"), self.axis, self.single, self.position, self.multi, self.count, self.compute,
                  self.export):
            row.addWidget(w)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.chart, 1)
        layout.addWidget(self.status)
        self.compute.clicked.connect(self.cut)
        self.export.clicked.connect(self.export_requested)
        self.axis.currentTextChanged.connect(lambda _t: self._centre_position())
        self.export.setEnabled(False)
        self.resize(760, 520)

    def set_results(self, patches: dict, u_ref: float, bounds) -> None:
        """The wall patches (cell field p), U_ref and the parts' bounds of the shown results."""
        self.patches, self.u_ref, self.bounds = dict(patches), u_ref, bounds
        self._centre_position()
        self.sections = []
        self._show()

    def configure(self, theme: Theme) -> None:
        self._theme = theme
        self.chart.configure(theme)
        self._show()

    def _range(self) -> tuple[float, float] | None:
        if self.bounds is None:
            return None
        i = AXES[self.axis.currentText()]
        return self.bounds[2 * i], self.bounds[2 * i + 1]

    def _centre_position(self) -> None:
        r = self._range()
        if r is not None:
            self.position.setValue((r[0] + r[1]) / 2)

    def positions(self) -> list[float]:
        if self.single.isChecked():
            return [self.position.value()]
        r = self._range()
        return stations(r[0], r[1], self.count.value()) if r is not None else []

    def cut(self) -> list[Section]:
        axis = self.axis.currentText()
        self.sections = [s for s in (cut_section(self.patches, axis, p, self.u_ref) for p in self.positions())
                         if s is not None]
        missed = len(self.positions()) - len(self.sections)
        self.status.setText(f"{len(self.sections)} section(s)" + (f", {missed} missed the walls" if missed else ""))
        self._show()
        return self.sections

    def _show(self) -> None:
        series = []
        for i, s in enumerate(self.sections):
            colour = _colour(self._theme, i)
            for line in s.lines:
                style = "DashLine" if line.surface.startswith(NEGATIVE_SIDES) else "SolidLine"
                name = s.label if line.surface == "all" else f"{s.label} {line.surface}"
                series.append((name, colour, style, list(zip(line.x_c.tolist(), line.cp.tolist()))))
        self.chart.set_series(series)
        self.export.setEnabled(bool(self.sections))

    def write_csv(self, path: Path) -> int:
        return export_csv(self.sections, Path(path))
