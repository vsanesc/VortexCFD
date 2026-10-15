"""Main window bound to a Project: simulation tree, properties panel, menus."""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.gui.dialogs import Dialogs
from vortexcfd.gui.properties_panel import PropertiesPanel

log = logging.getLogger(__name__)

_NODE_ROLE = Qt.ItemDataRole.UserRole
_SECTIONS = (
    ("geometry", "Geometry"),
    ("mesh", "Mesh"),
    ("physics", "Physics"),
    ("solvers", "Solvers"),
    ("reports", "Reports"),
)

Selection = tuple[str, int | None]  # (node kind, part index)


class MainWindow(QMainWindow):
    """Main window with a simulation tree, a properties panel and a 3D viewer placeholder.

    All changes go through the Project edit API. Only the GUI thread may call Project methods
    (Project is not thread-safe).
    """

    def __init__(
        self,
        project: Project,
        dialogs: Dialogs | None = None,
        with_viewer: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._unsubscribe = None
        self._selection: Selection | None = None
        self.dialogs = dialogs if dialogs is not None else Dialogs(self)
        self.resize(1024, 768)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Simulation Tree")
        self.properties = PropertiesPanel(project)
        self.properties.message.connect(self.show_message)

        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self.tree)
        left.addWidget(self.properties)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)

        self.viewer = None
        if with_viewer:
            # Placeholder from the spike; Task 2.2 replaces it.
            import pyvista as pv
            from pyvistaqt import QtInteractor

            self.viewer = QtInteractor(splitter)
            self.plotter = self.viewer
            self.viewer.add_mesh(pv.Sphere(), color="lightblue", show_edges=True)
            self.viewer.reset_camera()
            splitter.addWidget(self.viewer)
            splitter.setSizes([300, 724])
        self.setCentralWidget(splitter)

        self._parts_label = QLabel()
        self.statusBar().addPermanentWidget(self._parts_label)
        self._build_actions()

        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.set_project(project)

    # -- project binding -----------------------------------------------------

    @property
    def project(self) -> Project:
        return self._project

    def set_project(self, project: Project) -> None:
        """Bind the window to ``project``: swap observer, clear selection, refresh."""
        if self._unsubscribe is not None:
            self._unsubscribe()
        self._project = project
        self._selection = None
        self.properties.set_project(project)
        self._unsubscribe = project.subscribe(self._on_project_changed)
        self._refresh()

    def _on_project_changed(self, project: Project) -> None:
        # The Project swallows observer exceptions; surface them here instead.
        try:
            self._refresh()
        except Exception as exc:
            log.exception("UI refresh failed")
            self.show_message(f"Internal error refreshing the UI: {exc}")

    def show_message(self, text: str) -> None:
        self.statusBar().showMessage(text)

    # -- refresh -------------------------------------------------------------

    def _refresh(self) -> None:
        sim = self._project.sim
        self._rebuild_tree(sim.name, [p.name for p in sim.geometry.parts])
        self.properties.show_node(*(self._selection or ("root", None)))
        self._parts_label.setText(f"Parts: {len(sim.geometry.parts)}")
        self._update_actions()
        self._update_title(sim.name)

    def _rebuild_tree(self, name: str, part_names: list[str]) -> None:
        wanted = self._selection
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            root = self._make_item(self.tree, name, ("root", None))
            items: dict[Selection, QTreeWidgetItem] = {("root", None): root}
            for kind, label in _SECTIONS:
                node = self._make_item(root, label, (kind, None))
                items[(kind, None)] = node
                if kind == "geometry":
                    for i, part_name in enumerate(part_names):
                        items[("part", i)] = self._make_item(node, part_name, ("part", i))
            self.tree.expandAll()
            if wanted not in items:
                wanted = ("root", None)
            self._selection = wanted
            self.tree.setCurrentItem(items[wanted])
        finally:
            self.tree.blockSignals(False)

    @staticmethod
    def _make_item(parent, text: str, node: Selection) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent, [text])
        item.setData(0, _NODE_ROLE, node)
        return item

    def _on_current_item_changed(self, current, _previous) -> None:
        if current is None:
            return
        self._selection = current.data(0, _NODE_ROLE)
        self.properties.show_node(*self._selection)
        self._update_actions()

    def _update_title(self, name: str) -> None:
        path = self._project.path
        self.setWindowTitle(f"{name}[*] - {path.name if path else 'Untitled'} - VortexCFD")
        self.setWindowModified(self._project.dirty)

    # -- actions -------------------------------------------------------------

    def _build_actions(self) -> None:
        def action(text: str, slot, shortcut=None) -> QAction:
            act = QAction(text, self)
            act.triggered.connect(slot)
            if shortcut is not None:
                act.setShortcut(QKeySequence(shortcut))
            return act

        S = QKeySequence.StandardKey
        self.act_new = action("&New", self.new_project, S.New)
        self.act_open = action("&Open...", self.open_project, S.Open)
        self.act_save = action("&Save", self.save, S.Save)
        self.act_save_as = action("Save &As...", self.save_as, S.SaveAs)
        self.act_quit = action("&Quit", self.close, S.Quit)
        self.act_undo = action("Undo", self._undo, S.Undo)
        self.act_redo = action("Redo", self._redo, S.Redo)
        self.act_add_part = action("Add part (placeholder)", self.add_placeholder_part)
        self.act_remove_part = action("&Remove part", self.remove_selected_part, S.Delete)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.act_new, self.act_open])
        file_menu.addSeparator()
        file_menu.addActions([self.act_save, self.act_save_as])
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)
        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addActions([self.act_undo, self.act_redo])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_add_part, self.act_remove_part])

    def _update_actions(self) -> None:
        p = self._project
        self.act_undo.setEnabled(p.can_undo)
        self.act_undo.setText(f"Undo {p.undo_label}" if p.undo_label else "Undo")
        self.act_redo.setEnabled(p.can_redo)
        self.act_redo.setText(f"Redo {p.redo_label}" if p.redo_label else "Redo")
        self.act_remove_part.setEnabled(self._selected_part_index() is not None)

    def _selected_part_index(self) -> int | None:
        if self._selection and self._selection[0] == "part":
            return self._selection[1]
        return None

    def _run_edit(self, edit) -> None:
        try:
            edit()
        except (ValueError, TypeError, IndexError) as exc:
            self.show_message(str(exc))

    def _undo(self) -> None:
        self._project.undo()

    def _redo(self) -> None:
        self._project.redo()

    def add_placeholder_part(self) -> None:
        # PLACEHOLDER: real geometry import comes in Phase 3; this only adds an empty part.
        taken = {p.name for p in self._project.sim.geometry.parts}
        n = 1
        while f"Part {n}" in taken:
            n += 1
        part = Part(name=f"Part {n}", source_file="", units="m")
        self._run_edit(lambda: self._project.add_part(part))

    def remove_selected_part(self) -> None:
        index = self._selected_part_index()
        if index is not None:
            self._run_edit(lambda: self._project.remove_part(index))

    # -- file operations -----------------------------------------------------

    def save(self) -> bool:
        """Save to the project's path (Save As if it has none). False if not saved."""
        if self._project.path is None:
            return self.save_as()
        return self._save_to(None)

    def save_as(self) -> bool:
        path = self.dialogs.ask_save_path(self._project.path)
        if path is None:
            return False
        return self._save_to(path)

    def _save_to(self, path: Path | None) -> bool:
        try:
            self._project.save(path)
        except (OSError, ValueError) as exc:
            self.show_message(f"Save failed: {exc}")
            return False
        self.show_message(f"Saved {self._project.path}")
        return True

    def _confirm_discard(self) -> bool:
        """True if it is OK to drop the current project (saved, discarded or not dirty)."""
        if not self._project.dirty:
            return True
        choice = self.dialogs.confirm_discard()
        if choice == "save":
            return self.save()
        return choice == "discard"

    def new_project(self) -> None:
        if self._confirm_discard():
            self.set_project(Project.new("Untitled"))

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        path = self.dialogs.ask_open_path()
        if path is None:
            return
        try:
            project = Project.open(path)
        except Exception as exc:  # ProjectFileError, OSError, ...
            self.show_message(f"Could not open {path}: {exc}")
            return
        self.set_project(project)
        self.show_message(f"Opened {path}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        if self.viewer is not None:
            self.viewer.close()  # release VTK interactor resources
        super().closeEvent(event)


def main() -> int:
    """Application entry point: ``vortexcfd [path]``."""
    logging.basicConfig(level=logging.INFO)
    app = QApplication.instance() or QApplication(sys.argv)
    args = app.arguments()[1:]
    error = None
    project = None
    if args:
        try:
            project = Project.open(Path(args[0]))
        except Exception as exc:
            error = f"Could not open {args[0]}: {exc}"
    window = MainWindow(project if project is not None else Project.new("Untitled"))
    if error:
        window.show_message(error)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
