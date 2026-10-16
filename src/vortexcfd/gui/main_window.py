"""Main window bound to a Project: simulation tree, properties panel, menus."""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QMainWindow,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.gui.dialogs import Dialogs
from vortexcfd.gui.icons import ICON_TOKENS, make_icon
from vortexcfd.gui.properties_panel import PropertiesPanel
from vortexcfd.gui.theme import (
    DEFAULT_POINT_SIZE,
    THEMES,
    Theme,
    apply_theme,
    clamp_point_size,
    load_appearance,
    save_appearance,
)

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
        self.resize(1280, 800)
        self._theme, self._point_size = load_appearance()
        apply_theme(self._theme, self._point_size)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.properties = PropertiesPanel(project)
        self.properties.message.connect(lambda text: self.show_message(text, "warning"))

        self._layouts: list[QVBoxLayout] = []
        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self._pane("Simulation", self.tree))
        left.addWidget(self._pane("Properties", self.properties))
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 2)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.setStretchFactor(0, 24)
        splitter.setStretchFactor(1, 76)
        splitter.setSizes([24, 76])  # proportions; Qt scales them to the actual width
        self._splitter = splitter

        self.viewer = None
        if with_viewer:
            # Placeholder from the spike; Task 2.2 replaces it.
            import pyvista as pv
            from pyvistaqt import QtInteractor

            self.viewer = QtInteractor(splitter)
            self.plotter = self.viewer
            self.viewer.add_mesh(pv.Sphere(), color="lightblue", show_edges=True)
            self.viewer.add_axes()
            self.viewer.reset_camera()
            splitter.addWidget(self.viewer)
        self.setCentralWidget(splitter)

        self._parts_label = QLabel()
        self.statusBar().addPermanentWidget(self._parts_label)
        self._build_actions()
        self._apply_appearance()

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
            self.show_message(f"Internal error refreshing the UI: {exc}", "error")

    def show_message(self, text: str, level: str = "info") -> None:
        """Show ``text`` in the status bar; level is info, success, warning or error."""
        bar = self.statusBar()
        bar.setProperty("level", level)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        bar.showMessage(text)

    # -- appearance ----------------------------------------------------------

    def _pane(self, title: str, body: QWidget) -> QWidget:
        pane = QWidget()
        pane.setObjectName("pane")
        pane.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        layout = QVBoxLayout(pane)
        layout.addWidget(label)
        layout.addWidget(body)
        self._layouts.append(layout)
        return pane

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def point_size(self) -> int:
        return self._point_size

    def set_theme(self, name: str) -> None:
        self._theme = THEMES[name]
        self._persist_and_apply()

    def set_point_size(self, size: int) -> None:
        self._point_size = clamp_point_size(size)
        self._persist_and_apply()

    def _persist_and_apply(self) -> None:
        save_appearance(self._theme, self._point_size)
        self._apply_appearance()

    def _apply_appearance(self) -> None:
        apply_theme(self._theme, self._point_size)
        unit = self.fontMetrics().height()
        small, large = round(unit * 0.5), round(unit * 0.75)
        for layout in self._layouts:
            layout.setContentsMargins(large, large, large, large)
            layout.setSpacing(small)
        self.properties.apply_metrics(unit)
        self.statusBar().setContentsMargins(large, 0, large, 0)
        self.tree.setIconSize(QSize(unit, unit))
        if self.viewer is not None:
            self.viewer.set_background(self._theme.viewer_bottom, top=self._theme.viewer_top)
            self.viewer.render()
        for act, name in ((self.act_dark, "dark"), (self.act_light, "light")):
            act.setChecked(self._theme.name == name)
        if hasattr(self, "_unsubscribe") and self._unsubscribe is not None:
            self._refresh()  # rebuild tree icons for the new colors and size

    def _icon(self, kind: str):
        color = QColor(getattr(self._theme, ICON_TOKENS[kind]))
        size = self.tree.iconSize().height()
        return make_icon(
            kind, color, size, self.devicePixelRatioF(), QColor(self._theme.accent_text)
        )

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

    def _make_item(self, parent, text: str, node: Selection) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent, [text])
        item.setData(0, _NODE_ROLE, node)
        item.setIcon(0, self._icon(node[0]))
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
        # Delete applies only while the tree has focus, so text fields keep their Delete key.
        self.act_remove_part.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.tree.addAction(self.act_remove_part)

        self.act_zoom_in = action("Zoom &In", lambda: self.set_point_size(self._point_size + 1))
        self.act_zoom_in.setShortcuts([QKeySequence("Ctrl+="), QKeySequence("Ctrl++")])
        self.act_zoom_out = action("Zoom &Out", lambda: self.set_point_size(self._point_size - 1), "Ctrl+-")
        self.act_zoom_reset = action(
            "&Reset Zoom", lambda: self.set_point_size(DEFAULT_POINT_SIZE), "Ctrl+0"
        )
        self.act_dark = action("&Dark", lambda: self.set_theme("dark"))
        self.act_light = action("&Light", lambda: self.set_theme("light"))
        group = QActionGroup(self)
        group.setExclusive(True)
        for act in (self.act_dark, self.act_light):
            act.setCheckable(True)
            group.addAction(act)

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
        view_menu = self.menuBar().addMenu("&View")
        view_menu.addActions([self.act_zoom_in, self.act_zoom_out, self.act_zoom_reset])
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("&Theme")
        theme_menu.addActions([self.act_dark, self.act_light])

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
            self.show_message(str(exc), "warning")

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
        previous = self._selection
        self._selection = ("part", len(taken))  # the observer refresh selects the new part
        try:
            self._project.add_part(part)
        except (ValueError, TypeError, IndexError) as exc:
            self._selection = previous
            self.show_message(str(exc), "warning")

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
            self.show_message(f"Save failed: {exc}", "error")
            return False
        self.show_message(f"Saved {self._project.path}", "success")
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
            log.exception("Could not open project %s", path)
            self.show_message(f"Could not open {path}: {exc}", "error")
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
            log.exception("Could not open project %s", args[0])
            error = f"Could not open {args[0]}: {exc}"
    window = MainWindow(project if project is not None else Project.new("Untitled"))
    if error:
        window.show_message(error, "error")
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
