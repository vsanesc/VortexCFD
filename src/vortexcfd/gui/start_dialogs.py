"""Start, New simulation and Manage presets dialogs (D-077).

Each dialog is a plain QDialog whose state can be driven without ``exec`` (tests); ``Dialogs`` in
gui/dialogs.py runs them modally.
"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.core.presets import BUILTIN_PRESETS, Preset, PresetError, PresetStore
from vortexcfd.core.project import check_new_project_folder
from vortexcfd.core.model import DIMENSION_LABELS, DIMENSIONS
from vortexcfd.foam.parallel import physical_cores, recommended_cores
from vortexcfd.gui.recent import RecentProjects
from vortexcfd.gui.settings_store import settings

NOT_FOUND = "not found"
LAST_PARENT_KEY = "new/parent"
ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_EXISTS = Qt.ItemDataRole.UserRole + 1


def _muted() -> QColor:
    from PySide6.QtWidgets import QApplication

    return QApplication.palette().color(QApplication.palette().ColorGroup.Disabled,
                                        QApplication.palette().ColorRole.Text)


class StartDialog(QDialog):
    """New simulation, Open project... and the recent projects. ``choice`` after it closes:
    ("new", None), ("open", None), ("recent", path) or None (closed)."""

    def __init__(self, recent: RecentProjects, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VortexCFD")
        self.setModal(True)
        self.recent = recent
        self.choice: tuple[str, Path | None] | None = None
        layout = QVBoxLayout(self)
        title = QLabel("Start")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        buttons = QHBoxLayout()
        self.new_button = QPushButton("New simulation")
        self.open_button = QPushButton("Open project…")
        self.new_button.clicked.connect(lambda: self._choose("new"))
        self.open_button.clicked.connect(lambda: self._choose("open"))
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("Recent projects"))
        self.list = QListWidget()
        self.list.itemActivated.connect(self._open_item)
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.open_recent_button = QPushButton("Open")
        self.remove_button = QPushButton("Remove from list")
        self.open_recent_button.clicked.connect(lambda: self._open_item(self.list.currentItem()))
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.open_recent_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.resize(520, 380)
        self.fill()

    def fill(self) -> None:
        self.list.clear()
        for path, exists in self.recent.entries():
            text = f"{path.stem}  —  {path}" + ("" if exists else f"  ({NOT_FOUND})")
            item = QListWidgetItem(text)
            item.setData(ROLE_PATH, str(path))
            item.setData(ROLE_EXISTS, exists)
            item.setToolTip(str(path))
            if not exists:
                item.setForeground(_muted())
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._update_buttons()

    def items(self) -> list[tuple[str, bool]]:
        """(text, enabled) of every listed recent project (for tests)."""
        return [(self.list.item(i).text(), bool(self.list.item(i).data(ROLE_EXISTS)))
                for i in range(self.list.count())]

    def _update_buttons(self) -> None:
        item = self.list.currentItem()
        self.open_recent_button.setEnabled(item is not None and bool(item.data(ROLE_EXISTS)))
        self.remove_button.setEnabled(item is not None)

    def select(self, row: int) -> None:
        self.list.setCurrentRow(row)

    def remove_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        self.recent.remove(Path(item.data(ROLE_PATH)))
        self.fill()

    def _open_item(self, item: QListWidgetItem | None) -> None:
        if item is None or not item.data(ROLE_EXISTS):
            return  # a missing file cannot be opened; it can only be removed
        self.choice = ("recent", Path(item.data(ROLE_PATH)))
        self.accept()

    def _choose(self, what: str) -> None:
        self.choice = (what, None)
        self.accept()


@dataclass(frozen=True)
class NewSimulationSpec:
    """What the New simulation dialog returns."""

    name: str
    parent: Path
    preset: Preset
    cores: int  # 1 = serial
    dimension: str = "3d"  # "3d" or "2d" (D-121); the preset's unless changed in the dialog


def default_cores(preset: Preset, physical: int) -> int:
    """The recommended core count (foam/parallel.recommended_cores, D-064) for the preset's background
    cell target: the only cell count known before a mesh exists."""
    return recommended_cores(preset.mesh.background_cells_target, physical)


# What each analysis type creates (D-077, D-078, D-129).
ANALYSIS_DESCRIPTIONS = {
    "external": "External flow: a far-field domain is generated around the parts.",
    "empty": "Empty: nothing is generated; the domain is a Generate domain operation.",
    "internal": "Internal flow: no domain; the fluid is the inside of the closed geometry, each surface patch an "
                "inlet, an outlet or a wall.",
}


class NewSimulationDialog(QDialog):
    """Project name, parent folder, analysis preset and parallel run settings."""

    def __init__(self, store: PresetStore, parent: QWidget | None = None, physical: int | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New simulation")
        self.setModal(True)
        self.physical = physical or physical_cores()
        self.presets: list[Preset] = list(BUILTIN_PRESETS) + store.presets()
        self.result_spec: NewSimulationSpec | None = None
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("wing_study")
        form.addRow("Project name", self.name_edit)
        folder_row = QHBoxLayout()
        self.parent_edit = QLineEdit(str(settings().value(LAST_PARENT_KEY, str(Path.home()))))
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self._browse)
        folder_row.addWidget(self.parent_edit, 1)
        folder_row.addWidget(self.browse_button)
        form.addRow("Parent folder", folder_row)
        self.preset_combo = QComboBox()
        for i, preset in enumerate(self.presets):
            builtin = i < len(BUILTIN_PRESETS)
            self.preset_combo.addItem(preset.name if builtin else f"{preset.name} (user)")
        form.addRow("Analysis preset", self.preset_combo)
        self.analysis_label = QLabel()  # the preset's analysis type (D-077, D-129)
        self.analysis_label.setWordWrap(True)
        form.addRow("Analysis type", self.analysis_label)
        self.dimension_combo = QComboBox()
        for key in DIMENSIONS:
            self.dimension_combo.addItem(DIMENSION_LABELS[key], key)
        self.dimension_combo.setToolTip("2D section: the parts' section in the x-z plane meshed as one cell across "
                                        "the span (y), with empty front and back; forces per unit span")
        form.addRow("Analysis", self.dimension_combo)
        self.parallel_check = QCheckBox("Run in parallel")
        self.cores_spin = QSpinBox()
        self.cores_spin.setRange(1, self.physical)
        self.cores_spin.setSuffix(f" of {self.physical} physical cores")
        par_row = QHBoxLayout()
        par_row.addWidget(self.parallel_check)
        par_row.addWidget(self.cores_spin, 1)
        form.addRow("Solver", par_row)
        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)
        self.error_label = QLabel()
        self.error_label.setObjectName("checkValue")
        self.error_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.create_button = self.buttons.addButton("Create", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self._create)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.folder_label)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)
        self.name_edit.textChanged.connect(lambda _: self.validate())
        self.parent_edit.textChanged.connect(lambda _: self.validate())
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        self.parallel_check.toggled.connect(self.cores_spin.setEnabled)
        self._preset_changed()
        self.resize(560, 0)

    @property
    def preset(self) -> Preset:
        return self.presets[self.preset_combo.currentIndex()]

    def select_preset(self, name: str) -> None:
        index = next(i for i, p in enumerate(self.presets) if p.name == name)
        self.preset_combo.setCurrentIndex(index)

    @property
    def dimension(self) -> str:
        return self.dimension_combo.currentData()

    def _preset_changed(self, *_args) -> None:
        self.dimension_combo.setCurrentIndex(DIMENSIONS.index(self.preset.dimension))
        self.analysis_label.setText(ANALYSIS_DESCRIPTIONS[self.preset.analysis_type])
        cores = default_cores(self.preset, self.physical)
        self.cores_spin.setValue(cores)
        self.parallel_check.setChecked(cores > 1)
        self.cores_spin.setEnabled(self.parallel_check.isChecked())
        self.validate()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Parent folder", self.parent_edit.text())
        if folder:
            self.parent_edit.setText(folder)

    def validate(self) -> str | None:
        """The reason Create is disabled (shown under the form), or None."""
        reason = None
        try:
            folder = check_new_project_folder(Path(self.parent_edit.text().strip()), self.name_edit.text())
            self.folder_label.setText(f"Creates {folder}/")
        except (ValueError, TypeError) as exc:  # ProjectFolderError is a ValueError
            reason = str(exc)
            self.folder_label.setText("")
        self.error_label.setText(reason or "")
        self.create_button.setEnabled(reason is None)
        return reason

    def spec(self) -> NewSimulationSpec | None:
        if self.validate() is not None:
            return None
        cores = self.cores_spin.value() if self.parallel_check.isChecked() else 1
        return NewSimulationSpec(self.name_edit.text().strip(), Path(self.parent_edit.text().strip()),
                                 self.preset, cores, self.dimension)

    def _create(self) -> None:
        self.result_spec = self.spec()
        if self.result_spec is None:
            return
        s = settings()
        s.setValue(LAST_PARENT_KEY, str(self.result_spec.parent))
        s.sync()
        self.accept()


class DuplicateProjectDialog(QDialog):
    """Save As (duplicate project, D-079): the new project's name and parent folder, validated as in
    New simulation. ``result`` after it closes: (name, parent) or None."""

    def __init__(self, current_name: str, current_parent: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save As (duplicate project)")
        self.setModal(True)
        self.result_target: tuple[str, Path] | None = None
        form = QFormLayout()
        self.name_edit = QLineEdit(f"{current_name}_copy")
        form.addRow("New project name", self.name_edit)
        folder_row = QHBoxLayout()
        self.parent_edit = QLineEdit(str(current_parent))
        self.browse_button = QPushButton("Browse\u2026")
        self.browse_button.clicked.connect(self._browse)
        folder_row.addWidget(self.parent_edit, 1)
        folder_row.addWidget(self.browse_button)
        form.addRow("Parent folder", folder_row)
        note = QLabel("The geometry is copied; the mesh and results are not (the duplicate starts without them). "
                      "The original project is not changed.")
        note.setWordWrap(True)
        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)
        self.error_label = QLabel()
        self.error_label.setObjectName("checkValue")
        self.error_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.create_button = self.buttons.addButton("Duplicate", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self._create)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.folder_label)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)
        self.name_edit.textChanged.connect(lambda _: self.validate())
        self.parent_edit.textChanged.connect(lambda _: self.validate())
        self.validate()
        self.resize(560, 0)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Parent folder", self.parent_edit.text())
        if folder:
            self.parent_edit.setText(folder)

    def validate(self) -> str | None:
        reason = None
        try:
            folder = check_new_project_folder(Path(self.parent_edit.text().strip()), self.name_edit.text())
            self.folder_label.setText(f"Creates {folder}/")
        except (ValueError, TypeError) as exc:
            reason = str(exc)
            self.folder_label.setText("")
        self.error_label.setText(reason or "")
        self.create_button.setEnabled(reason is None)
        return reason

    def _create(self) -> None:
        if self.validate() is None:
            self.result_target = (self.name_edit.text().strip(), Path(self.parent_edit.text().strip()))
            self.accept()


class ManagePresetsDialog(QDialog):
    """Rename and delete user presets; broken preset files are listed (and can be deleted).
    ``ask_name(current) -> str | None`` and ``confirm(text) -> bool`` are injectable."""

    def __init__(self, store: PresetStore, parent: QWidget | None = None, ask_name=None, confirm=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage presets")
        self.setModal(True)
        self.store = store
        self.ask_name = ask_name or self._ask_name
        self.confirm = confirm or self._confirm
        self.error: str | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("User presets (the built-in presets cannot be changed)"))
        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.rename_button = QPushButton("Rename…")
        self.delete_button = QPushButton("Delete")
        self.rename_button.clicked.connect(self.rename_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        row.addWidget(self.rename_button)
        row.addWidget(self.delete_button)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.resize(460, 320)
        self.fill()

    def fill(self) -> None:
        self.list.clear()
        good, broken = self.store.scan()
        for stored in good:
            item = QListWidgetItem(stored.preset.name)
            item.setData(ROLE_PATH, ("preset", stored.preset.name))
            self.list.addItem(item)
        for bad in broken:
            item = QListWidgetItem(f"{bad.path.name} (broken: {bad.error})")
            item.setData(ROLE_PATH, ("broken", str(bad.path)))
            item.setForeground(_muted())
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._update_buttons()

    def texts(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def select(self, text: str) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).text() == text:
                self.list.setCurrentRow(i)
                return
        raise KeyError(text)

    def _selected(self):
        item = self.list.currentItem()
        return item.data(ROLE_PATH) if item is not None else None

    def _update_buttons(self) -> None:
        sel = self._selected()
        self.rename_button.setEnabled(sel is not None and sel[0] == "preset")
        self.delete_button.setEnabled(sel is not None)

    def rename_selected(self) -> None:
        sel = self._selected()
        if sel is None or sel[0] != "preset":
            return
        new = self.ask_name(sel[1])
        if not new:
            return
        try:
            self.store.rename(sel[1], new)
            self._say(None)
        except (PresetError, ValueError) as exc:
            self._say(str(exc))
        self.fill()

    def delete_selected(self) -> None:
        sel = self._selected()
        if sel is None:
            return
        what = f"the preset '{sel[1]}'" if sel[0] == "preset" else f"the broken file {Path(sel[1]).name}"
        if not self.confirm(f"Delete {what}?"):
            return
        try:
            if sel[0] == "preset":
                self.store.delete(sel[1])
            else:
                self.store.delete_file(Path(sel[1]))
            self._say(None)
        except (PresetError, OSError) as exc:
            self._say(str(exc))
        self.fill()

    def _say(self, error: str | None) -> None:
        self.error = error
        self.message.setText(error or "")

    def _ask_name(self, current: str) -> str | None:
        text, ok = QInputDialog.getText(self, "Rename preset", "New name:", text=current)
        return text if ok else None

    def _confirm(self, text: str) -> bool:
        answer = QMessageBox.question(self, "Manage presets", text,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

