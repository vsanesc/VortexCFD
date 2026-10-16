"""Main window bound to a Project: simulation tree, properties panel, menus."""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.gui.dialogs import Dialogs
from vortexcfd.gui.icons import ICON_TOKENS, make_icon
from vortexcfd.gui.properties_panel import PropertiesPanel
from vortexcfd.gui.widgets import ProjectHeader, SearchField, StagePill, ViewPill, make_strip
from vortexcfd.gui.theme import (
    DEFAULT_POINT_SIZE,
    Theme,
    Metrics,
    apply_theme,
    clamp_point_size,
    load_appearance,
    metrics,
    save_appearance,
    section_title_font,
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


class _RowDelegate(QStyledItemDelegate):
    """Tree rows: fixed height, full-width hover/selection fill, 2px accent bar on the left
    edge of the selected row and a drawn chevron slot for rows with children."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._metrics: Metrics | None = None
        self._theme: Theme | None = None

    def configure(self, m: Metrics, theme: Theme) -> None:
        self._metrics = m
        self._theme = theme

    @property
    def slot(self) -> int:
        """Width reserved for the chevron at the left of every row."""
        return self._metrics.u if self._metrics else 0

    def sizeHint(self, option, index) -> QSize:
        hint = super().sizeHint(option, index)
        if self._metrics is not None:
            hint.setHeight(self._metrics.row)
            hint.setWidth(hint.width() + self.slot)
        return hint

    def paint(self, painter: QPainter, option, index) -> None:
        m, t = self._metrics, self._theme
        if m is None or t is None:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        hover = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        r = opt.rect
        row = QRect(0, r.top(), opt.widget.viewport().width(), r.height())
        if selected:
            painter.fillRect(row, QColor(t.selection))
            painter.fillRect(QRect(0, r.top(), m.bar, r.height()), QColor(t.accent))
        elif hover:
            painter.fillRect(row, QColor(t.elevated))
        if index.model().hasChildren(index):
            self._draw_chevron(painter, r, bool(opt.state & QStyle.StateFlag.State_Open), hover, m, t)
        opt.state &= ~(
            QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_MouseOver
            | QStyle.StateFlag.State_HasFocus
        )
        opt.rect = r.adjusted(self.slot, 0, 0, 0)
        super().paint(painter, opt, index)

    def _draw_chevron(self, painter, r, expanded: bool, hover: bool, m: Metrics, t: Theme) -> None:
        pen = QPen(QColor(t.accent if hover else t.muted_text), max(1.2, m.u / 12))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(pen)
        cx, cy, h = r.left() + self.slot / 2, r.center().y() + 0.5, m.u * 0.16
        if expanded:
            pts = [QPointF(cx - h, cy - h / 2), QPointF(cx, cy + h / 2), QPointF(cx + h, cy - h / 2)]
        else:
            pts = [QPointF(cx - h / 2, cy - h), QPointF(cx + h / 2, cy), QPointF(cx - h / 2, cy + h)]
        painter.drawPolyline(QPolygonF(pts))
        painter.restore()


class _Tree(QTreeWidget):
    """Tree whose chevron slot toggles expansion without changing the selection."""

    def mousePressEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        delegate = self.itemDelegate()
        if item is not None and item.childCount() and isinstance(delegate, _RowDelegate):
            rect = self.visualItemRect(item)
            if rect.left() <= event.position().x() < rect.left() + delegate.slot:
                item.setExpanded(not item.isExpanded())
                return
        super().mousePressEvent(event)


class _Handle(QSplitterHandle):
    """Splitter handle with a wide hit area and a single 1px divider line."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        line = metrics().line
        color = self.palette().color(QPalette.ColorRole.Mid)
        # The 1px line sits on the edge facing the viewer (the center column, index 1).
        splitter = self.splitter()
        on_right = splitter is not None and splitter.indexOf(self) == 1
        x = self.width() - line if on_right else 0
        painter.fillRect(QRect(x, 0, line, self.height()), color)


class _Splitter(QSplitter):
    def createHandle(self) -> QSplitterHandle:
        return _Handle(self.orientation(), self)


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
        self._theme, self._point_size = load_appearance()
        apply_theme(self._theme, self._point_size)
        self._apply_default_size()
        self._first_show = True

        self.tree = _Tree()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)  # chevrons are drawn by the delegate
        self.tree.setMouseTracking(True)
        self._delegate = _RowDelegate(self.tree)
        self.tree.setItemDelegate(self._delegate)
        self._root_item: QTreeWidgetItem | None = None
        self._filter = ""
        self._sidebar_sizes: list[int] | None = None
        self.properties = PropertiesPanel(project)
        self.properties.message.connect(lambda text: self.show_message(text, "warning"))
        self.properties.pending_changed.connect(self._update_actions)
        self._build_actions()

        # Left sidebar: project header, search, tree.
        self.header = ProjectHeader(
            [self.act_new, self.act_open, None, self.act_save, self.act_save_as]
        )
        self.header.name_clicked.connect(self._select_root)
        self.header.collapse_clicked.connect(self.act_toggle_sidebars.trigger)
        self.search = SearchField()
        self.search.textChanged.connect(self._set_filter)
        self._search_row = QWidget()
        search_layout = QVBoxLayout(self._search_row)
        search_layout.addWidget(self.search)
        self._search_layout = search_layout
        self._left = QWidget()
        self._left.setObjectName("pane")
        self._left.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        left_layout = QVBoxLayout(self._left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.header)
        left_layout.addWidget(self._search_row)
        left_layout.addWidget(self.tree, 1)

        self._titles: list[QLabel] = []
        self._layouts: list[QVBoxLayout] = []
        self._right = self._pane("Properties", self.properties)
        splitter = _Splitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._left)

        # Center column: stage strip, viewer, view strip (strips never overlay the viewer).
        self.stage_pill = StagePill()
        self.stage_pill.stage_clicked.connect(self._select_stage)
        self.view_pill = ViewPill(lambda: self.viewer)
        self._center = QWidget()
        center_layout = QVBoxLayout(self._center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(make_strip(self.stage_pill, "stripTop"))
        self.viewer = None
        if with_viewer:
            # Placeholder from the spike; Task 2.2 replaces it.
            import pyvista as pv
            from pyvistaqt import QtInteractor

            self.viewer = QtInteractor(self._center)
            self.plotter = self.viewer
            self.viewer.add_mesh(pv.Sphere(), color="lightblue", show_edges=True)
            self.viewer.reset_camera()
            canvas: QWidget = self.viewer
        else:
            canvas = QWidget()
            canvas.setObjectName("canvas")
            canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._canvas = canvas
        center_layout.addWidget(canvas, 1)
        center_layout.addWidget(make_strip(self.view_pill, "stripBottom"))
        self.view_pill.setEnabled(self.viewer is not None)
        # Ignored: no widget may drive column or window width through its size hint.
        for w in (self.tree, self._left, self._right, self._center, canvas):
            w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        splitter.addWidget(self._center)
        splitter.addWidget(self._right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        for i in range(3):
            splitter.setCollapsible(i, False)
        self._splitter = splitter
        self.setCentralWidget(splitter)

        self._parts_label = QLabel()
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addPermanentWidget(self._parts_label)
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
        label = QLabel(title.upper())
        label.setObjectName("sectionTitle")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(label)
        layout.addWidget(body, 1)
        self._titles.append(label)
        return pane

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def point_size(self) -> int:
        return self._point_size

    def set_point_size(self, size: int) -> None:
        self._point_size = clamp_point_size(size)
        self._persist_and_apply()

    def _persist_and_apply(self) -> None:
        save_appearance(self._theme, self._point_size)
        self._apply_appearance()

    def _apply_appearance(self) -> None:
        apply_theme(self._theme, self._point_size)
        m = metrics()
        for label in self._titles:
            label.setFont(section_title_font(QApplication.font()))
            label.setFixedHeight(m.header)
        t = self._theme
        self.properties.apply_metrics(m, t)
        self._delegate.configure(m, t)
        self.header.configure(m, t)
        self.search.configure(m, t)
        self._search_layout.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
        self.tree.setIndentation(m.u)
        for strip_pill in (self.stage_pill, self.view_pill):
            strip_pill.configure(m)
        for pane in (self._center,):
            for strip in pane.findChildren(QWidget, "stripTop") + pane.findChildren(QWidget, "stripBottom"):
                strip.setFixedHeight(m.strip)
        self.menuBar().setFixedHeight(m.menubar)
        self.statusBar().setFixedHeight(m.status)
        self._splitter.setHandleWidth(m.hit)
        self._left.setMinimumWidth(11 * m.u)
        self._left.setMaximumWidth(22 * m.u)
        self._center.setMinimumWidth(20 * m.u)
        self._right.setMinimumWidth(14 * m.u)
        self._right.setMaximumWidth(28 * m.u)
        self.statusBar().setContentsMargins(m.s3, 0, m.s3, 0)
        self.tree.setIconSize(QSize(m.u, m.u))
        if self.viewer is not None:
            self._style_viewer()
        if self._unsubscribe is not None:
            self._refresh()  # rebuild tree icons for the new size
        if not self._first_show:
            self._apply_initial_sizes()

    def _style_viewer(self) -> None:
        t = self._theme
        self.viewer.set_background(t.canvas)
        self.viewer.hide_axes()
        # pyvista add_axes: color = label text color; x/y/z_color = axis colors; label_size is
        # forwarded to the marker. The widget occupies ~7u square, so labels scale with the font.
        m = metrics()
        side = max(1, min(self.viewer.width(), self.viewer.height()))
        frac = min(0.5, 7 * m.u / side)
        self.viewer.add_axes(
            color=t.text, x_color=t.axis_x, y_color=t.axis_y, z_color=t.axis_z,
            line_width=max(2, round(m.u / 9)), viewport=(0, 0, frac, frac),
            label_size=(0.4, 0.16),
        )
        self.viewer.render()

    def _apply_default_size(self) -> None:
        """78u x 47u, clamped to 90% of the available screen."""
        u = metrics().u
        w, h = 78 * u, 47 * u
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            w, h = min(w, int(avail.width() * 0.9)), min(h, int(avail.height() * 0.9))
        self.resize(w, h)

    def _apply_initial_sizes(self) -> None:
        u = metrics().u
        width = self._splitter.width()
        left, right = 14 * u, 17 * u
        self._splitter.setSizes([left, max(0, width - left - right), right])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            self._apply_initial_sizes()  # needs the real width
            if self.viewer is not None:
                self._style_viewer()  # axes viewport depends on the real viewer size

    def _icon(self, kind: str):
        color = QColor(getattr(self._theme, ICON_TOKENS[kind]))
        size = self.tree.iconSize().height()
        # Same tint when selected (Qt would otherwise auto-tint the selected variant).
        return make_icon(kind, color, size, self.devicePixelRatioF(), color)

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
            self._root_item = root
            self.tree.setRootIndex(self.tree.indexFromItem(root))  # the header shows the root
            self._items = items
            if wanted not in items:
                wanted = ("root", None)
            self._selection = wanted
            self.tree.setCurrentItem(items[wanted])
        finally:
            self.tree.blockSignals(False)
        self._apply_filter()
        self._update_stage()

    def _select_root(self) -> None:
        if self._root_item is not None:
            self.tree.setCurrentItem(self._root_item)

    def _select_stage(self, kind: str) -> None:
        item = self._items.get((kind, None))
        if item is not None:
            item.setExpanded(True)
            self.tree.setCurrentItem(item)

    def _update_stage(self) -> None:
        kind = self._selection[0] if self._selection else "root"
        if kind == "part":
            kind = "geometry"
        if kind in self.stage_pill._by_kind:  # the root selection keeps the previous stage
            self.stage_pill.set_stage(kind)

    def _set_filter(self, text: str) -> None:
        self._filter = text.strip().casefold()
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Hide rows that neither match nor have a matching child (empty text shows all)."""
        if self._root_item is None:
            return

        def visit(item: QTreeWidgetItem) -> bool:
            child_match = False
            for i in range(item.childCount()):
                child_match |= visit(item.child(i))
            match = not self._filter or self._filter in item.text(0).casefold()
            item.setHidden(not (match or child_match))
            return match or child_match

        for i in range(self._root_item.childCount()):
            visit(self._root_item.child(i))

    def _toggle_sidebars(self) -> None:
        """Hide/show both side panels, restoring the previous widths."""
        if self._left.isHidden():
            self._left.show()
            self._right.show()
            if self._sidebar_sizes:
                self._splitter.setSizes(self._sidebar_sizes)
        else:
            self._sidebar_sizes = self._splitter.sizes()
            self._left.hide()
            self._right.hide()

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
        self._update_stage()
        self._update_actions()

    def _update_title(self, name: str) -> None:
        path = self._project.path
        self.setWindowTitle(f"{name}[*] - {path.name if path else 'Untitled'} - VortexCFD")
        self.setWindowModified(self._project.dirty)
        self.header.set_name(name, self._project.dirty)

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

        self.act_toggle_sidebars = action("Toggle &Sidebars", self._toggle_sidebars, "Ctrl+B")

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
        view_menu.addAction(self.act_toggle_sidebars)

    def _update_actions(self) -> None:
        p = self._project
        # A pending field edit is committed by Undo first, so it counts as undoable.
        self.act_undo.setEnabled(p.can_undo or self.properties.has_pending)
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

    def _flush_edits(self) -> None:
        """Commit any uncommitted field edit before an action that reads the project."""
        self.properties.commit_pending()

    def _undo(self) -> None:
        self._flush_edits()
        self._project.undo()

    def _redo(self) -> None:
        self._flush_edits()
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
        self._flush_edits()
        if self._project.path is None:
            return self.save_as()
        return self._save_to(None)

    def save_as(self) -> bool:
        self._flush_edits()
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
        self._flush_edits()
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
