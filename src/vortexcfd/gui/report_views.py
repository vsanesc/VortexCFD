"""Reports & Monitors views: the Forces table (D-060)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QSizePolicy, QWidget

from vortexcfd.foam.forces import ForceRow
from vortexcfd.gui.theme import mono_font

# (attribute of ForceRow, row label, tooltip, format); one column per wall set.
FORCE_TABLE_ROWS = (
    ("cd", "Cd", "Drag coefficient (total)", "{:.4g}"),
    ("cd_pressure", "Cd,p", "Pressure drag coefficient", "{:.4g}"),
    ("cd_viscous", "Cd,v", "Viscous (skin friction) drag coefficient", "{:.4g}"),
    ("cl", "Cl", "Lift coefficient (total)", "{:.4g}"),
    ("cl_pressure", "Cl,p", "Pressure lift coefficient", "{:.4g}"),
    ("cl_viscous", "Cl,v", "Viscous lift coefficient", "{:.4g}"),
    ("cm", "Cm", "Pitching moment coefficient about CofR (pitch axis +y)", "{:.4g}"),
    ("x_cp", "x_cp", "Centre of pressure along the body x axis: x_CofR - M_y / F_z(body); body axes = the "
     "geometry axes (the free stream turns with alpha, the body does not); undefined when |F_z(body)| < "
     "0.001 q A_ref", "{:.4g} m"),
)
UNDEFINED = "undefined"  # x_cp with a near-zero normal force


class ForcesTable(QWidget):
    """Rows: Cd and Cl with their pressure and viscous parts, Cm, x_cp; columns: all walls, then
    each part (latest iteration)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.rows: list[ForceRow] = []
        self.cells: dict[tuple[str, str], QLabel] = {}  # (attribute, column name) -> label
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def _label(self, text: str, muted: bool = False, shrink: bool = False) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted" if muted else "checkValue")
        label.setFont(mono_font(QApplication.font(), 0.8))
        if shrink:  # the row-name column gives way first
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def _add(self, label: QLabel, row: int, col: int) -> None:
        self.grid.addWidget(label, row, col)
        label.show()  # now: the panel measures the table's height right after set_rows

    def set_rows(self, rows: list[ForceRow]) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.rows, self.cells = list(rows), {}
        if not rows:
            return
        for col, row in enumerate(rows, start=1):
            head = self._label(row.name, muted=True)
            head.setToolTip(row.name)
            head.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._add(head, 0, col)
        for r, (attr, text, tip, fmt) in enumerate(FORCE_TABLE_ROWS, start=1):
            name = self._label(text, muted=True, shrink=True)
            name.setToolTip(tip)
            self._add(name, r, 0)
            for col, row in enumerate(rows, start=1):
                value = getattr(row, attr)
                cell = self._label(UNDEFINED if value is None else fmt.format(value))
                cell.setAlignment(Qt.AlignmentFlag.AlignRight)
                if value is None:
                    cell.setToolTip("Centre of pressure undefined: the body normal force is near zero "
                                    "(|F_z(body)| < 0.001 q A_ref)")
                self._add(cell, r, col)
                self.cells[(attr, row.name)] = cell
        self.grid.setColumnStretch(0, 1)

    def text(self, attr: str, column: str) -> str:
        return self.cells[(attr, column)].text()

    def configure(self, spacing: int) -> None:
        self.grid.setHorizontalSpacing(spacing)
        self.grid.setVerticalSpacing(max(1, spacing // 3))
