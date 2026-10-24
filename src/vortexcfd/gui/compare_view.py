"""The Compare tab (D-149): results snapshots of this project and of others, overlaid plots and the value and set-up
difference tables, with PNG and CSV export. The comparison itself is workflow/snapshots.py (Qt-free)."""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.gui.plot_interaction import ZoomPan
from vortexcfd.gui.theme import role_point_size
from vortexcfd.workflow import snapshots as snapshot_module
from vortexcfd.workflow.snapshots import Snapshot

ROLE_KEY = Qt.ItemDataRole.UserRole
HINT = ("Save a results snapshot after a run (it keeps the residuals, the reports, the line plots and the set-up), "
        "run again with other settings, then tick two or more runs to compare them.")


def _num(v) -> str:
    return "" if v is None else f"{v:.6g}"


class CompareView(QWidget):
    """The snapshots list (checkable: the current run, this project's snapshots, those loaded from other projects)
    and the comparison of the ticked ones. ``action`` asks the window for what needs it: "save", "load", "delete",
    "png", "csv_values", "csv_setup"."""

    action = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._snaps: dict[str, Snapshot] = {}  # key -> snapshot (key: "current", a file path, "ext:" + path)
        split = QSplitter(Qt.Orientation.Horizontal)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.addWidget(split)

        left = QWidget()
        lbox = QVBoxLayout(left)
        lbox.setContentsMargins(0, 0, 0, 0)
        title = QLabel("RUNS")
        title.setObjectName("subSection")
        lbox.addWidget(title)
        self.list = QListWidget()
        self.list.setObjectName("recentList")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setToolTip("Tick the runs to compare; the first ticked one is the reference of the differences")
        self.list.itemChanged.connect(lambda _item: self.refresh_comparison())
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        lbox.addWidget(self.list, 1)
        self.save_button = QPushButton("Save results snapshot…")
        self.save_button.setObjectName("primaryBtn")
        self.save_button.setToolTip("Keep the current run's results under a name (in <project>/snapshots/)")
        self.load_button = QPushButton("Load from project…")
        self.load_button.setToolTip("Add the snapshots of another project (.vcfd), read-only")
        self.delete_button = QPushButton("Delete")
        self.delete_button.setToolTip("Delete the selected snapshot of this project")
        for button, key in ((self.save_button, "save"), (self.load_button, "load"), (self.delete_button, "delete")):
            button.clicked.connect(lambda _=False, k=key: self.action.emit(k))
            lbox.addWidget(button)
        split.addWidget(left)

        right = QWidget()
        rbox = QVBoxLayout(right)
        rbox.setContentsMargins(0, 0, 0, 0)
        self.hint = QLabel(HINT)
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        rbox.addWidget(self.hint)
        self.tabs = QTabWidget()
        rbox.addWidget(self.tabs, 1)
        # plots
        plots = QWidget()
        pbox = QVBoxLayout(plots)
        row = QHBoxLayout()
        self.plot_choice = QComboBox()
        self.plot_choice.setToolTip("What to overlay: the residuals, a report's history or a line plot's field")
        self.plot_choice.currentIndexChanged.connect(lambda _i: self._draw())
        self.png_button = QPushButton("Export PNG…")
        self.png_button.clicked.connect(lambda: self.action.emit("png"))
        row.addWidget(self.plot_choice, 1)
        row.addWidget(self.png_button)
        pbox.addLayout(row)
        self.figure = Figure(figsize=(6, 3.5), dpi=90)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.zoom_pan = ZoomPan(self.canvas)  # wheel zoom, drag pan, double-click: all (D-169)
        pbox.addWidget(self.canvas, 1)
        self.tabs.addTab(plots, "Plots")
        # values
        values = QWidget()
        vbox = QVBoxLayout(values)
        self.values_table = QTableWidget()
        self.values_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        vbox.addWidget(self.values_table, 1)
        self.values_csv = QPushButton("Export CSV…")
        self.values_csv.clicked.connect(lambda: self.action.emit("csv_values"))
        vbox.addWidget(self.values_csv, 0, Qt.AlignmentFlag.AlignRight)
        self.tabs.addTab(values, "Values")
        # set-up
        setup = QWidget()
        sbox = QVBoxLayout(setup)
        self.setup_table = QTableWidget()
        self.setup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        sbox.addWidget(self.setup_table, 1)
        self.setup_csv = QPushButton("Export CSV…")
        self.setup_csv.clicked.connect(lambda: self.action.emit("csv_setup"))
        sbox.addWidget(self.setup_csv, 0, Qt.AlignmentFlag.AlignRight)
        self.tabs.addTab(setup, "Set-up differences")
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 700])
        self.refresh_comparison()

    # -- the runs -----------------------------------------------------------------------------------------------

    def set_snapshots(self, current: Snapshot | None, saved: list[Snapshot], external: list[Snapshot]) -> None:
        """Fill the list, keeping the ticks of the runs still listed."""
        ticked = set(self.checked_keys())
        self.list.blockSignals(True)
        self.list.clear()
        self._snaps = {}
        entries = ([("current", current)] if current is not None else [])
        entries += [(s.path, s) for s in saved]
        entries += [(f"ext:{s.path}", s) for s in external]
        for key, snap in entries:
            text = snap.label + (" (read-only)" if snap.read_only else "")
            if key != "current":
                text += f"  — {snap.created.replace('T', ' ')}"
            item = QListWidgetItem(text)
            item.setData(ROLE_KEY, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in ticked else Qt.CheckState.Unchecked)
            item.setToolTip(f"{snap.label}: {snap.state or 'no run record'}, {snap.iterations} iterations")
            self.list.addItem(item)
            self._snaps[key] = snap
        self.list.blockSignals(False)
        self._update_buttons()
        self.refresh_comparison()

    def checked_keys(self) -> list[str]:
        return [self.list.item(i).data(ROLE_KEY) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def check(self, keys) -> None:
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(ROLE_KEY) in keys else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self.refresh_comparison()

    def keys(self) -> list[str]:
        return [self.list.item(i).data(ROLE_KEY) for i in range(self.list.count())]

    def selected_snapshots(self) -> list[Snapshot]:
        """The ticked runs, in list order (the first is the reference)."""
        return [self._snaps[k] for k in self.checked_keys() if k in self._snaps]

    def current_snapshot(self) -> Snapshot | None:
        item = self.list.currentItem()
        return self._snaps.get(item.data(ROLE_KEY)) if item is not None else None

    def _update_buttons(self) -> None:
        snap = self.current_snapshot()
        self.delete_button.setEnabled(snap is not None and not snap.read_only and snap.path is not None)

    # -- the comparison -----------------------------------------------------------------------------------------

    def refresh_comparison(self) -> None:
        snaps = self.selected_snapshots()
        enough = len(snaps) >= 2
        self.hint.setVisible(not enough)
        for w in (self.png_button, self.values_csv, self.setup_csv):
            w.setEnabled(enough)
        current = self.plot_choice.currentData()
        self.plot_choice.blockSignals(True)
        self.plot_choice.clear()
        for key, label in snapshot_module.plot_choices(snaps):
            self.plot_choice.addItem(label, key)
        index = self.plot_choice.findData(current)
        self.plot_choice.setCurrentIndex(index if index >= 0 else 0)
        self.plot_choice.blockSignals(False)
        self._fill_values(snaps)
        self._fill_setup(snaps)
        self._draw()

    def _fill_values(self, snaps: list[Snapshot]) -> None:
        rows = snapshot_module.value_rows(snaps) if len(snaps) >= 2 else []
        header = ["Quantity", "Value", *(s.label for s in snaps)]
        for s in snaps[1:]:
            header += [f"Δ {s.label}", "Δ %"]
        table = self.values_table
        table.clear()
        table.setColumnCount(len(header))
        table.setHorizontalHeaderLabels(header)
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cells = [row.label, row.kind, *(_num(v) for v in row.values)]
            for i in range(1, len(snaps)):
                rel = row.relative(i)
                cells += [_num(row.absolute(i)), "" if rel is None else f"{100 * rel:+.3g} %"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c >= 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()

    def _fill_setup(self, snaps: list[Snapshot]) -> None:
        rows = snapshot_module.setup_rows(snaps) if len(snaps) >= 2 else []
        table = self.setup_table
        table.clear()
        table.setColumnCount(1 + len(snaps))
        table.setHorizontalHeaderLabels(["Input", *(s.label for s in snaps)])
        table.setRowCount(len(rows))
        for r, (key, values) in enumerate(rows):
            for c, text in enumerate((key, *values)):
                table.setItem(r, c, QTableWidgetItem(text))
        table.resizeColumnsToContents()

    def plot_key(self) -> str | None:
        return self.plot_choice.currentData()

    def _draw(self) -> None:
        snaps = self.selected_snapshots()
        key = self.plot_key()
        if len(snaps) < 2 or key is None:
            self.figure.clear()
            self.figure.text(0.5, 0.5, "Tick two or more runs to overlay them", ha="center", va="center",
                             fontsize=role_point_size("body"))
        else:
            snapshot_module.draw(self.figure, snaps, key)
        self.canvas.draw_idle()
