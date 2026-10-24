"""Reports & Monitors views: the Forces table (D-060)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

from vortexcfd.foam.convergence import WindowStats
from vortexcfd.foam.forces import ForceRow
from vortexcfd.gui.theme import set_text_role
from vortexcfd.gui.widgets import discard

# (attribute of ForceRow, row label, tooltip, format); one column per wall set.
FORCE_TABLE_ROWS = (
    ("cd", "Cd", "Drag coefficient (total)", "{:.4g}"),
    ("cd_pressure", "Cd,p", "Pressure drag coefficient", "{:.4g}"),
    ("cd_viscous", "Cd,v", "Viscous (skin friction) drag coefficient", "{:.4g}"),
    ("cl", "Cl", "Lift coefficient (total)", "{:.4g}"),
    ("cl_pressure", "Cl,p", "Pressure lift coefficient", "{:.4g}"),
    ("cl_viscous", "Cl,v", "Viscous lift coefficient", "{:.4g}"),
    ("cm", "Cm", "Pitching moment coefficient about CofR (pitch axis +y, nose up positive)", "{:.4g}"),
    ("c_axial", "C_A", "Axial force coefficient along the parts' own x axis (body axes: turned with the angle "
     "of attack)", "{:.4g}"),
    ("c_normal", "C_N", "Normal force coefficient along the parts' own z axis (body axes)", "{:.4g}"),
    ("x_cp", "x_cp", "Centre of pressure along the body x axis: x_CofR - M_y / F_N, in the coordinates of the "
     "parts as imported; undefined when |F_N| < 0.001 q A_ref", "{:.4g} m"),
)
UNDEFINED = "undefined"  # x_cp with a near-zero normal force
# Windowed rows under the latest values (D-118): (quantity base, row label, tooltip).
WINDOW_TABLE_ROWS = (
    ("Cd", "Cd mean", "Drag coefficient (wind axes): mean over the last iterations \u00b1 half its range there (as a share "
     "of |mean|); for a steady run that oscillates, judge the mean"),
    ("Cl", "Cl mean", "Lift coefficient: mean over the last iterations \u00b1 half its range there (as a share "
     "of |mean|)"),
)


def window_text(stats: WindowStats | None) -> str:
    if stats is None:
        return "\u2014"
    half = "" if stats.amplitude is None else f" \u00b1{50 * stats.amplitude:.2g}%"
    return f"{stats.mean:.4g}{half}"


class ForcesTable(QWidget):
    """Rows: Cd and Cl with their pressure and viscous parts, Cm, x_cp; columns: all walls, then
    each part (latest iteration); then the windowed means of Cd and Cl with their oscillation (D-118)."""

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
        set_text_role(label, "data")
        if shrink:  # the row-name column gives way first
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def _add(self, label: QLabel, row: int, col: int) -> None:
        self.grid.addWidget(label, row, col)
        label.show()  # now: the panel measures the table's height right after set_rows

    def set_rows(self, rows: list[ForceRow], windowed=None) -> None:
        """``windowed(quantity base, column name)`` -> WindowStats | None (None: no windowed rows)."""
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                discard(item.widget())
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
        if windowed is not None:
            first = len(FORCE_TABLE_ROWS) + 1
            for r, (base, text, tip) in enumerate(WINDOW_TABLE_ROWS, start=first):
                name = self._label(text, muted=True, shrink=True)
                name.setToolTip(tip)
                self._add(name, r, 0)
                for col, row in enumerate(rows, start=1):
                    stats = windowed(base, row.name)
                    cell = self._label(window_text(stats))
                    cell.setAlignment(Qt.AlignmentFlag.AlignRight)
                    if stats is not None:
                        cell.setToolTip(f"Over the last {stats.n} iterations: mean {stats.mean:.6g}, "
                                        f"max - min {stats.spread:.3g}")
                    self._add(cell, r, col)
                    self.cells[(f"{base}_mean", row.name)] = cell
        self.grid.setColumnStretch(0, 1)

    def text(self, attr: str, column: str) -> str:
        return self.cells[(attr, column)].text()

    def configure(self, spacing: int) -> None:
        self.grid.setHorizontalSpacing(spacing)
        self.grid.setVerticalSpacing(max(1, spacing // 3))


# The internal-flow table (D-129): (attribute of postprocessing.InternalRow, row label, tooltip, format); one column
# per inlet, outlet and cutting plane.
INTERNAL_TABLE_ROWS = (
    ("mdot", "Mass flow", "Mass flow rate (kg/s): on an inlet or outlet positive out of the domain (an inlet is "
     "negative), on a plane along its normal", "{:.5g} kg/s"),
    ("p_area", "p area-avg", "Static pressure averaged over the area (Pa, gauge)", "{:.5g} Pa"),
    ("p_mass", "p mass-avg", "Static pressure averaged with the mass flux (Pa, gauge)", "{:.5g} Pa"),
    ("p0_area", "p0 area-avg", "Total pressure p + 0.5 rho |U|^2 averaged over the area (Pa, gauge)", "{:.5g} Pa"),
    ("p0_mass", "p0 mass-avg", "Total pressure averaged with the mass flux (Pa, gauge): the energy-consistent "
     "average for losses", "{:.5g} Pa"),
)
# Windowed rows (D-118): (flow quantity, row label, tooltip).
INTERNAL_WINDOW_ROWS = (
    ("mdot", "Mass flow mean", "Mass flow: mean over the last iterations ± half its range there"),
    ("p0_mass", "p0 mass-avg mean", "Mass-averaged total pressure: mean over the last iterations ± half its "
     "range there"),
)


class InternalFlowTable(ForcesTable):
    """Internal flow (D-129): rows mass flow and the four pressure averages, then their windowed means; columns the
    inlets and outlets, then the planes (latest iteration). ``drops`` (name, static, total, windowed total) are
    appended as rows below a header."""

    def set_internal(self, rows, drops=(), windowed=None) -> None:
        """``rows``: postprocessing.InternalRow list; ``drops``: (name, static Pa, total Pa); ``windowed(quantity,
        kind, name)`` -> WindowStats | None for the mean rows, and windowed("dp", "total", drop) for the drops."""
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                discard(item.widget())
        self.rows, self.cells = list(rows), {}
        if not rows and not drops:
            return
        for col, row in enumerate(rows, start=1):
            head = self._label(row.name, muted=True)
            head.setToolTip(f"{'Plane' if row.kind == 'plane' else 'Patch'} {row.name}")
            head.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._add(head, 0, col)
        r = 1
        for attr, text, tip, fmt in INTERNAL_TABLE_ROWS:
            name = self._label(text, muted=True, shrink=True)
            name.setToolTip(tip)
            self._add(name, r, 0)
            for col, row in enumerate(rows, start=1):
                value = getattr(row, attr)
                cell = self._label("—" if value is None else fmt.format(value))
                cell.setAlignment(Qt.AlignmentFlag.AlignRight)
                self._add(cell, r, col)
                self.cells[(attr, row.name)] = cell
            r += 1
        if windowed is not None:
            for quantity, text, tip in INTERNAL_WINDOW_ROWS:
                name = self._label(text, muted=True, shrink=True)
                name.setToolTip(tip)
                self._add(name, r, 0)
                for col, row in enumerate(rows, start=1):
                    stats = windowed(quantity, row.kind, row.name)
                    cell = self._label(window_text(stats))
                    cell.setAlignment(Qt.AlignmentFlag.AlignRight)
                    if stats is not None:
                        cell.setToolTip(f"Over the last {stats.n} iterations: mean {stats.mean:.6g}, "
                                        f"max - min {stats.spread:.3g}")
                    self._add(cell, r, col)
                    self.cells[(f"{quantity}_mean", row.name)] = cell
                r += 1
        for drop, static, total in drops:
            name = self._label(f"dp {drop}", muted=True, shrink=True)
            name.setToolTip("Pressure drop: mass-averaged upstream minus downstream (static, total; Pa)")
            self._add(name, r, 0)
            text = ("—" if static is None else f"{static:.5g}") + " / " + ("—" if total is None else f"{total:.5g}")
            stats = windowed("dp", "total", drop) if windowed is not None else None
            if stats is not None:
                text += f" (mean {window_text(stats)})"
            cell = self._label(text + " Pa")
            cell.setToolTip("static / total pressure drop at the latest iteration; the mean is the total's")
            self.grid.addWidget(cell, r, 1, 1, max(1, len(rows)))
            cell.show()
            self.cells[("dp", drop)] = cell
            r += 1
        self.grid.setColumnStretch(0, 1)
