"""Results windows of the mesh study (D-066) and the polar sweep (D-067): tables, QPainter charts and
Export CSV. Non-modal; the owner sets the record and handles the export file dialog."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from vortexcfd.core.reports import report_label
from vortexcfd.foam.mesh_study import StudyRecord, quantity_rows
from vortexcfd.foam.polar_sweep import SweepRecord
from vortexcfd.gui.charts import LineChart
from vortexcfd.gui.theme import DARK, Theme, residual_style


def _num(value, fmt: str = "{:.5g}") -> str:
    return "—" if value is None else fmt.format(value)


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill(table: QTableWidget, rows: list[list[str]], warn_rows: set[int] = frozenset(), warn_color: str = "") -> None:
    from PySide6.QtGui import QColor

    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            item = QTableWidgetItem(text)
            if r in warn_rows and warn_color:
                item.setForeground(QColor(warn_color))
            table.setItem(r, c, item)


STUDY_HEADERS = ["Quantity", "h coarse [m]", "h medium [m]", "h fine [m]", "Coarse", "Medium", "Fine",
                 "Order p", "Extrapolated", "GCI fine", "Asymptotic ratio", "Note"]
LEVEL_HEADERS = ["Level", "Cells", "h [m]", "Run", "Iterations", "Time [s]"]


class MeshStudyWindow(QDialog):
    """The GCI table per quantity, the levels and a chart of the chosen quantity against h."""

    export_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mesh study")
        self.setModal(False)
        self.record: StudyRecord | None = None
        self._theme = DARK
        self.table = _table(STUDY_HEADERS)
        self.levels = _table(LEVEL_HEADERS)
        self.quantity = QComboBox()
        self.chart = LineChart("h [m]", "value")
        self.chart.EMPTY_MESSAGE = "No mesh study results yet"
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.export = QPushButton("Export CSV")
        top = QHBoxLayout()
        for w in (QLabel("Chart"), self.quantity):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(self.export)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 2)
        layout.addWidget(self.levels, 1)
        layout.addWidget(self.chart, 3)
        layout.addWidget(self.status)
        self.quantity.currentIndexChanged.connect(lambda _i: self._chart())
        self.export.clicked.connect(self.export_requested)
        self.resize(980, 720)
        self.set_record(None)

    def configure(self, theme: Theme) -> None:
        self._theme = theme
        self.chart.configure(theme)
        self.set_record(self.record)

    def set_record(self, record: StudyRecord | None) -> None:
        self.record = record
        self.export.setEnabled(record is not None and any(lv.values for lv in record.levels))
        if record is None:
            _fill(self.table, [])
            _fill(self.levels, [])
            self.status.setText("No mesh study yet")
            self.quantity.clear()
            self._chart()
            return
        rows, warn = [], set()
        for i, row in enumerate(quantity_rows(record)):
            r = row.result
            ok = r is not None and r.applicable
            rows.append([
                report_label(row.quantity), *(_num(h, "{:.4g}") for h in row.sizes), *(_num(v) for v in row.values),
                _num(r.order if ok else None, "{:.3g}"), _num(r.extrapolated if ok else None),
                _num(100 * r.gci_fine if ok else None, "{:.3g} %"),
                _num(r.asymptotic_ratio if ok else None, "{:.3g}")
                + ("" if not ok else (" (in range)" if r.in_asymptotic_range else " (not in range)")),
                row.note,
            ])
            if not row.reliable or not ok:
                warn.add(i)
        _fill(self.table, rows, warn, self._theme.warning)
        level_rows, level_warn = [], set()
        for i, lv in enumerate(record.levels):
            level_rows.append([lv.name, _num(lv.cells, "{:,}"), _num(lv.h, "{:.4g}"),
                               lv.error or lv.state_label or "not run", _num(lv.iterations, "{}"),
                               _num(lv.duration_s, "{:.0f}")])
            if lv.state is not None and not lv.reliable:
                level_warn.add(i)
        _fill(self.levels, level_rows, level_warn, self._theme.warning)
        hs = [lv.h for lv in record.levels]
        actual = (f", actual h ratios {hs[0] / hs[1]:.3g} and {hs[1] / hs[2]:.3g}"
                  if all(h is not None for h in hs) else "")
        self.status.setText(f"Study {record.status}; ratio {record.ratio:.4g}{actual}, current settings = "
                            f"{record.current_as} level; GCI: Celik et al. 2008")
        current = self.quantity.currentData()
        self.quantity.blockSignals(True)
        self.quantity.clear()
        for q in record.quantities:
            self.quantity.addItem(report_label(q), q)
        if current in record.quantities:
            self.quantity.setCurrentIndex(record.quantities.index(current))
        self.quantity.blockSignals(False)
        self._chart()

    def _chart(self) -> None:
        q = self.quantity.currentData()
        if self.record is None or q is None:
            self.chart.set_series([])
            return
        pts = [(lv.h, lv.values[q], not lv.reliable) for lv in self.record.levels
               if lv.h is not None and q in lv.values]
        color = residual_style(self._theme, "p")[0]
        series = [(report_label(q), color, "SolidLine", [(x, y) for x, y, _ in pts])]
        self.chart.y_caption = report_label(q)
        self.chart.set_series(series, {0: pts})


SWEEP_HEADERS = ["alpha [deg]", "CL", "CD", "CM", "L/D", "Iterations", "Status"]


class PolarSweepWindow(QDialog):
    """The polar table and the CL-alpha, CL-CD (drag polar) and CM-alpha charts; points that did not
    meet their stopping criteria are drawn hollow in the warning colour."""

    export_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Polar sweep")
        self.setModal(False)
        self.record: SweepRecord | None = None
        self._theme = DARK
        self.table = _table(SWEEP_HEADERS)
        self.cl_alpha = LineChart("alpha [deg]", "CL")
        self.drag_polar = LineChart("CD", "CL")
        self.cm_alpha = LineChart("alpha [deg]", "CM")
        for chart in (self.cl_alpha, self.drag_polar, self.cm_alpha):
            chart.EMPTY_MESSAGE = "No sweep results yet"
            chart.setMinimumSize(260, 220)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.export = QPushButton("Export CSV")
        top = QHBoxLayout()
        top.addWidget(self.status, 1)
        top.addWidget(self.export)
        grid = QGridLayout()
        grid.addWidget(self.cl_alpha, 0, 0)
        grid.addWidget(self.drag_polar, 0, 1)
        grid.addWidget(self.cm_alpha, 1, 0)
        grid.addWidget(self.table, 1, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(grid, 1)
        self.export.clicked.connect(self.export_requested)
        self.resize(1000, 760)
        self.set_record(None)

    def configure(self, theme: Theme) -> None:
        self._theme = theme
        for chart in (self.cl_alpha, self.drag_polar, self.cm_alpha):
            chart.configure(theme)
        self.set_record(self.record)

    def set_record(self, record: SweepRecord | None) -> None:
        self.record = record
        run = [p for p in record.points if p.state is not None] if record is not None else []
        self.export.setEnabled(bool(run))
        if record is None:
            _fill(self.table, [])
            self.status.setText("No polar sweep yet")
        else:
            rows, warn = [], set()
            for i, p in enumerate(record.points):
                rows.append([f"{p.alpha:g}", _num(p.cl), _num(p.cd), _num(p.cm), _num(p.lift_to_drag, "{:.4g}"),
                             _num(p.iterations, "{}"), p.state_label or "not run"])
                if p.flagged:
                    warn.add(i)
            _fill(self.table, rows, warn, self._theme.warning)
            flagged = sum(p.flagged for p in record.points)
            self.status.setText(f"Sweep {record.status}: {len(run)} of {len(record.points)} points run"
                                + (f", {flagged} did not meet their stopping criteria (hollow)" if flagged else ""))
        color = residual_style(self._theme, "Ux")[0]
        with_values = [p for p in run if p.cl is not None and p.cd is not None]

        def show(chart: LineChart, name: str, pts: list[tuple[float, float, bool]]) -> None:
            chart.set_series([(name, color, "SolidLine", [(x, y) for x, y, _ in pts])], {0: pts})

        show(self.cl_alpha, "CL", [(p.alpha, p.cl, p.flagged) for p in with_values])
        show(self.drag_polar, "CL against CD", [(p.cd, p.cl, p.flagged) for p in with_values])
        show(self.cm_alpha, "CM", [(p.alpha, p.cm, p.flagged) for p in with_values if p.cm is not None])
