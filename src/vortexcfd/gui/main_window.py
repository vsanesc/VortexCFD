"""Main window bound to a Project, laid out after docs/design/design_preview.png."""

import logging
import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QButtonGroup,
    QMainWindow,
    QPushButton,
    QSlider,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.gui import console as console_log
from vortexcfd.gui.console import ConsolePanel
from vortexcfd.gui.dialogs import Dialogs
from vortexcfd.gui.icons import logo_icon, make_glyph
from vortexcfd.gui.monitors import MonitorsPanel
from vortexcfd.geometry.checks import surface_report
from vortexcfd.geometry.loader import SurfaceLoadError
from vortexcfd.gui.properties_panel import PropertiesPanel
from vortexcfd.geometry.domain import BOUNDARY_NAMES
from vortexcfd.foam.mesh_case import CaseDirectoryNotOursError
from vortexcfd.foam.mesh_estimate import estimate_mesh
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.gui.mesh_worker import MeshWorker
from vortexcfd.foam.mesh_record import MeshRecord, read_mesh_record, write_mesh_record
from vortexcfd.gui.meshing import MeshingNotReady, case_dir_for, inputs_hash, prepare_job, readiness
from vortexcfd.gui.scene import (
    ERROR,
    MISSING,
    DomainView,
    MeshView,
    PartScene,
    domain_box_for,
    part_status,
    report_for_part,
)
from vortexcfd.gui.theme import (
    DEFAULT_POINT_SIZE,
    LAYOUT,
    LEFT_INITIAL_U,
    LIMITS_U,
    SECTION_PREVIEW_MS,
    SECTION_SLIDER_STEPS,
    WINDOW_ICON_SIZES,
    Metrics,
    Theme,
    apply_theme,
    clamp_point_size,
    load_appearance,
    metrics,
    mono_font,
    save_appearance,
    settings,
)
from vortexcfd.gui.topbar import FIT_METHOD, VIEW_BUTTONS, TopBar
from vortexcfd.gui.viewport import (
    EMPTY_MESSAGE,
    TELEMETRY_FIELDS,
    EmptySceneMessage,
    TelemetryCard,
    add_ground_grid,
    load_telemetry_settings,
    save_telemetry_settings,
)
from vortexcfd.gui.widgets import DotButton, SearchField, SectionHeader

log = logging.getLogger(__name__)

ROLE_NODE = Qt.ItemDataRole.UserRole  # (kind, part index)
ROLE_EYE = Qt.ItemDataRole.UserRole + 1  # None, or the part's visibility (bool)

Selection = tuple[str, int | None]  # (node kind, part index)

# Message level -> logging level (info/success lines are logged by the actions themselves).
_LOGGED_LEVELS = {"warning": logging.WARNING, "error": logging.ERROR}
MESSAGE_TIMEOUT_MS = 8000
EMPTY = "\u2014"


class _RowDelegate(QStyledItemDelegate):
    """Tree rows: fixed height, full-width hover/selection fill, 2px accent_secondary bar on the
    left edge of the selected row, drawn chevrons for rows with children and an eye for parts."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._metrics: Metrics | None = None
        self._theme: Theme | None = None
        self._eye = {True: QIcon(), False: QIcon()}

    def configure(self, m: Metrics, theme: Theme, eye_on: QIcon, eye_off: QIcon) -> None:
        self._metrics = m
        self._theme = theme
        self._eye = {True: eye_on, False: eye_off}

    @property
    def slot(self) -> int:
        """Width reserved for the chevron at the left of every row."""
        return self._metrics.u if self._metrics else 0

    @property
    def eye_zone(self) -> int:
        """Width of the clickable eye area at the right edge of a row."""
        return self._metrics.u + 2 * self._metrics.s3 if self._metrics else 0

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
        width = opt.widget.viewport().width()
        row = QRect(0, r.top(), width, r.height())
        if selected:
            painter.fillRect(row, QColor(t.selection))
            painter.fillRect(QRect(0, r.top(), m.bar, r.height()), QColor(t.accent_secondary))
        elif hover:
            painter.fillRect(row, QColor(t.elevated))
        if index.model().hasChildren(index):
            self._draw_chevron(painter, r, bool(opt.state & QStyle.StateFlag.State_Open), hover, m, t)
        eye = index.data(ROLE_EYE)
        if eye is not None:
            side = m.u
            box = QRect(width - m.s3 - side, r.center().y() - side // 2, side, side)
            self._eye[bool(eye)].paint(painter, box)
        opt.state &= ~(
            QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_MouseOver
            | QStyle.StateFlag.State_HasFocus
        )
        opt.rect = r.adjusted(self.slot, 0, 0, 0)
        super().paint(painter, opt, index)

    def _draw_chevron(self, painter, r, expanded: bool, hover: bool, m: Metrics, t: Theme) -> None:
        pen = QPen(QColor(t.accent_secondary_hover if hover else t.muted_text), max(1.2, m.u / 12))
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
    """Tree whose chevron slot toggles expansion and whose eye zone toggles part visibility."""

    from PySide6.QtCore import Signal as _Signal

    eye_clicked = _Signal(object)

    def mousePressEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        delegate = self.itemDelegate()
        if item is not None and isinstance(delegate, _RowDelegate):
            x = event.position().x()
            rect = self.visualItemRect(item)
            if item.data(0, ROLE_EYE) is not None and x >= self.viewport().width() - delegate.eye_zone:
                self.eye_clicked.emit(item)
                return
            if item.childCount() and rect.left() <= x < rect.left() + delegate.slot:
                item.setExpanded(not item.isExpanded())
                return
        super().mousePressEvent(event)


class _Handle(QSplitterHandle):
    """Splitter handle with a wide hit area and a single 1px divider line in `border`."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        line = metrics().line
        color = self.palette().color(QPalette.ColorRole.Mid)
        splitter = self.splitter()
        edge = getattr(splitter, "line_edge", "center")
        if self.orientation() == Qt.Orientation.Horizontal:
            x = {"start": 0, "end": self.width() - line}.get(edge, (self.width() - line) // 2)
            painter.fillRect(QRect(x, 0, line, self.height()), color)
        else:
            y = {"start": 0, "end": self.height() - line}.get(edge, (self.height() - line) // 2)
            painter.fillRect(QRect(0, y, self.width(), line), color)


class _Splitter(QSplitter):
    line_edge = "center"  # where the 1px line sits in the handle: start, center or end

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self.setChildrenCollapsible(False)

    def createHandle(self) -> QSplitterHandle:
        return _Handle(self.orientation(), self)


class MainWindow(QMainWindow):
    """Top bar, left column (tree + properties), scene, monitors and console.

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
        self._items: dict[Selection, QTreeWidgetItem] = {}
        self._root_item: QTreeWidgetItem | None = None
        self._filter = ""
        self._first_show = True
        self._saved_sizes: dict[str, list[int]] = {}
        # GUI-side visibility of each part (by name); Task 2.2 wires it to the viewer.
        self.part_visibility: dict[str, bool] = {}
        self.telemetry_rows: list[tuple[str, str]] = []
        self.scene_actors: list = []  # extra geometry actors (besides the parts) for the wireframe toggle
        self.scene: PartScene | None = None
        self.wireframe = False
        self.current_view = "ISO"  # ISO, XY, XZ, YZ or Custom (after the user rotates)
        self._telemetry_show, self._telemetry_fields = load_telemetry_settings()
        self.telemetry = None
        self._empty_message = None
        self._grid_actors: list = []
        self.mesh_report: MeshReport | None = None
        self.mesh_stale = False
        self._mesh_hash: str | None = None  # inputs hash of the mesh being shown
        self._run_hash: str | None = None  # inputs hash at the start of the running mesh
        self.mesh_view: MeshView | None = None
        self._scene_mode = "geometry"
        self._mesh_patches: tuple[str, ...] = ()
        self.mesh_worker = MeshWorker(self)
        self.mesh_worker.line.connect(self._on_mesh_line)
        self.mesh_worker.step.connect(self._on_mesh_step)
        self.mesh_worker.finished.connect(self._on_mesh_done)
        self.domain_view: DomainView | None = None
        self._domain_box = None
        self._framed_visibility = False
        self.dialogs = dialogs if dialogs is not None else Dialogs(self)
        self._theme, self._point_size = load_appearance()
        apply_theme(self._theme, self._point_size)
        self._apply_default_size()

        # -- tree + properties -------------------------------------------------------
        self.tree = _Tree()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)  # chevrons are drawn by the delegate
        self.tree.setMouseTracking(True)
        self._delegate = _RowDelegate(self.tree)
        self.tree.setItemDelegate(self._delegate)
        self.tree.eye_clicked.connect(self._on_eye_clicked)
        self.properties = PropertiesPanel(project)
        self.properties.message.connect(lambda text: self.show_message(text, "warning"))
        self.properties.pending_changed.connect(self._update_actions)
        self._build_actions()

        self.tree_header = SectionHeader("Simulation Tree")
        self.node_badge = self.tree_header.add_badge("0 Nodes")
        self.search = SearchField("Filter nodes...")
        self.search.textChanged.connect(self._set_filter)
        self._search_row = QWidget()
        self._search_layout = QHBoxLayout(self._search_row)
        self._search_layout.addWidget(self.search)
        tree_section = self._panel(self.tree_header, self._search_row, self.tree)

        self.props_header = SectionHeader("Properties \u2014")
        self.props_name = QLabel()
        self.props_name.setObjectName("accent2")
        self.props_header.row.insertWidget(1, self.props_name)
        props_section = self._panel(self.props_header, self.properties)

        self._left_split = _Splitter(Qt.Orientation.Vertical)
        self._left_split.addWidget(tree_section)
        self._left_split.addWidget(props_section)
        self._left_split.setStretchFactor(0, 1)
        self._left_split.setStretchFactor(1, 0)
        self._left_split.splitterMoved.connect(self._save_left_split)
        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        self._selection_label = QLabel()
        self._status_bar.addWidget(self._selection_label, 1)
        self._left = QWidget()
        self._left.setObjectName("panel")
        self._left.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        left_layout = QVBoxLayout(self._left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self._left_split, 1)
        left_layout.addWidget(self._status_bar)

        # -- center: scene tab bar + viewer (no widget is overlaid on the viewer) -----
        self._center = QWidget()
        self._center.setObjectName("panel")
        center_layout = QVBoxLayout(self._center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self._tab_bar = QWidget()
        self._tab_bar.setObjectName("tabBar")
        self._tab_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tab_row = QHBoxLayout(self._tab_bar)
        tab_row.setContentsMargins(0, 0, 0, 0)
        self.scene_tab = QPushButton("Geometry Scene")  # kept name: the geometry tab
        self.mesh_tab = QPushButton("Mesh Scene")
        self._tab_group = QButtonGroup(self)
        for button, mode in ((self.scene_tab, "geometry"), (self.mesh_tab, "mesh")):
            button.setObjectName("sceneTabBtn")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._tab_group.addButton(button)
            button.clicked.connect(lambda _=False, m=mode: self._set_scene_mode(m))
            tab_row.addWidget(button)
        self.scene_tab.setChecked(True)
        tab_row.addStretch(1)
        # Section-plane controls of the mesh scene (hidden until a mesh is shown).
        # They live in their own strip under the tabs, so they are never squeezed.
        self.section_controls = QWidget()
        self.section_controls.setObjectName("tabBar")
        self.section_controls.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sc_row = QHBoxLayout(self.section_controls)
        self._section_row = sc_row
        self.section_toggle = DotButton("Section")
        self.section_toggle.setCheckable(True)
        self.section_toggle.setChecked(True)
        self.section_toggle.setToolTip("Show a section plane through the volume mesh")
        self.section_toggle.toggled.connect(self._on_section_toggled)
        sc_row.addWidget(self.section_toggle)
        self.axis_buttons: dict[int, QPushButton] = {}
        self._axis_group = QButtonGroup(self)
        for axis, text in enumerate("XYZ"):
            button = QPushButton(text)
            button.setObjectName("tbBtn")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip(f"Section plane normal along {text}")
            self._axis_group.addButton(button)
            button.clicked.connect(lambda _=False, a=axis: self._on_section_axis(a))
            self.axis_buttons[axis] = button
            sc_row.addWidget(button)
        self.axis_buttons[1].setChecked(True)  # default normal +y
        self.section_slider = QSlider(Qt.Orientation.Horizontal)
        self.section_slider.setRange(0, SECTION_SLIDER_STEPS)
        self.section_slider.setToolTip("Section plane offset along its normal (within the domain)")
        self.section_slider.valueChanged.connect(self._on_section_slider)
        self.section_slider.sliderReleased.connect(self._on_section_slider_released)
        self._pending_slice: int | None = None
        self._slice_timer = QTimer(self)
        self._slice_timer.setSingleShot(True)
        self._slice_timer.setInterval(SECTION_PREVIEW_MS)
        self._slice_timer.timeout.connect(self._flush_slice_preview)
        sc_row.addWidget(self.section_slider)
        self.boundary_toggle = DotButton("Boundaries")
        self.boundary_toggle.setCheckable(True)
        self.boundary_toggle.setToolTip("Show the domain boundary patches as translucent faces")
        self.boundary_toggle.toggled.connect(self._on_boundaries_toggled)
        sc_row.addWidget(self.boundary_toggle)
        sc_row.addStretch(1)
        self.section_controls.hide()
        center_layout.addWidget(self._tab_bar)
        center_layout.addWidget(self.section_controls)
        self.viewer = None
        if with_viewer:
            # Placeholder from the spike; Task 2.2 replaces it.
            from pyvistaqt import QtInteractor

            self.viewer = QtInteractor(self._center, auto_update=False)  # explicit renders only
            self.plotter = self.viewer
            # Placeholder scene: ground grid and a centered "No geometry yet" (no mesh).
            self._grid_actors = add_ground_grid(self.viewer, self._theme)
            self._empty_message = EmptySceneMessage(self.viewer.renderer)
            self.telemetry = TelemetryCard(self.viewer.renderer)
            self.viewer.view_isometric()
            self.viewer.reset_camera()
            self.scene = PartScene(self.viewer, self._theme, self._on_viewer_pick)
            self.domain_view = DomainView(self.viewer, self._theme)
            self.mesh_view = MeshView(self.viewer, self._theme)
            try:
                self.scene.install_picking()
            except Exception:  # pragma: no cover - interactor without observers
                log.exception("Could not install viewer picking")
            try:  # a user rotation makes the view "Custom"
                self.viewer.iren.add_observer(
                    "EndInteractionEvent", lambda *_: self._on_camera_interaction()
                )
            except Exception:  # pragma: no cover - interactor without observers
                log.exception("Could not observe camera interaction")
            self.viewer.installEventFilter(self)
            canvas: QWidget = self.viewer
        else:
            canvas = QWidget()
            canvas.setObjectName("canvas")
            canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._canvas = canvas
        center_layout.addWidget(canvas, 1)

        # -- right: monitors, bottom: console ----------------------------------------
        self.monitors = MonitorsPanel()
        self.console = ConsolePanel()
        self._console_handler = console_log.attach(self.console)
        handler = self._console_handler
        self.destroyed.connect(lambda *_: console_log.detach(handler))

        self._inner = _Splitter(Qt.Orientation.Horizontal)
        self._inner.addWidget(self._center)
        self._inner.addWidget(self.monitors)
        self._inner.setStretchFactor(0, 1)
        self._inner.setStretchFactor(1, 0)
        self._right_split = _Splitter(Qt.Orientation.Vertical)
        self._right_split.addWidget(self._inner)
        self._right_split.addWidget(self.console)
        self._right_split.setStretchFactor(0, 1)
        self._right_split.setStretchFactor(1, 0)
        self._outer = _Splitter(Qt.Orientation.Horizontal)
        self._outer.line_edge = "end"  # the line faces the scene
        self._right_split.line_edge = "start"  # the line faces the scene
        self._outer.addWidget(self._left)
        self._outer.addWidget(self._right_split)
        self._outer.setStretchFactor(0, 0)
        self._outer.setStretchFactor(1, 1)
        # Ignored: no widget may drive column or window size through its size hint.
        for w in (self.tree, self._left, self._center, canvas, self.monitors, self.console,
                  tree_section, props_section):
            w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        # -- top bar + central widget ------------------------------------------------
        self.top_bar = TopBar()
        self.top_bar.name_clicked.connect(self._select_root)
        self.top_bar.view_requested.connect(self._view)
        self.top_bar.wireframe_toggled.connect(self._set_wireframe)
        self.top_bar.mesh_clicked.connect(self.generate_mesh)
        self.top_bar.set_viewer_enabled(self.viewer is not None)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.top_bar)
        central_layout.addWidget(self._outer, 1)
        self.setCentralWidget(central)

        self.top_bar.set_active_view(self.current_view)
        self._apply_appearance()
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.set_project(project)
        log.info("VortexCFD started")

    @staticmethod
    def _panel(header: QWidget, *body: QWidget) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        for i, widget in enumerate(body):
            layout.addWidget(widget, 1 if i == len(body) - 1 else 0)
        return panel

    def statusBar(self) -> QStatusBar:  # the status line lives in the left column
        return self._status_bar

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
        if self.mesh_worker.is_running():  # a mesh of the old project is of no use any more
            self.mesh_worker.request_stop()
        self.mesh_report = None
        self.properties.set_mesh_report(None)
        if self.mesh_view is not None:
            self.mesh_view.clear()
            self._set_scene_mode("geometry")
        self.properties.set_project(project)
        self._load_mesh_record(project)
        self._unsubscribe = project.subscribe(self._on_project_changed)
        self._refresh()

    def _on_project_changed(self, project: Project) -> None:
        # The Project swallows observer exceptions; surface them here instead.
        try:
            self._refresh()
        except Exception as exc:
            log.exception("UI refresh failed")
            self.show_message(f"Internal error refreshing the UI: {exc}", "error", log_it=False)

    def show_message(self, text: str, level: str = "info", log_it: bool = True) -> None:
        """Show ``text`` in the status line; level is info, success, warning or error.

        Warnings and errors are also written to the console unless ``log_it`` is False.
        """
        bar = self.statusBar()
        bar.setProperty("level", level)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        bar.showMessage(text, MESSAGE_TIMEOUT_MS)
        if log_it and level in _LOGGED_LEVELS:
            log.log(_LOGGED_LEVELS[level], text)

    # -- appearance ----------------------------------------------------------

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def point_size(self) -> int:
        return self._point_size

    def set_point_size(self, size: int) -> None:
        self._point_size = clamp_point_size(size)
        save_appearance(self._theme, self._point_size)
        self._apply_appearance()

    def _apply_appearance(self) -> None:
        apply_theme(self._theme, self._point_size)
        m = metrics()
        t = self._theme
        self.top_bar.configure(m, t, self.devicePixelRatioF())
        self.setWindowIcon(logo_icon(t, WINDOW_ICON_SIZES, self.devicePixelRatioF()))
        self.tree_header.configure(m)
        self.props_header.configure(m)
        self.props_name.setFont(mono_font(QApplication.font(), 0.9))
        self.search.configure(m, t)
        self._search_layout.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
        self.properties.apply_metrics(m, t)
        self.monitors.configure(m, t)
        self.console.configure(m, t)
        self.node_badge.configure(m, t)
        self._delegate.configure(
            m, t,
            make_glyph("eye", QColor(t.muted_text), m.u, self.devicePixelRatioF()),
            make_glyph("eye_off", QColor(t.muted_text), m.u, self.devicePixelRatioF()),
        )
        self.tree.setIndentation(m.u)
        self.tree.setIconSize(QSize(m.u, m.u))
        self.tree.setFont(QApplication.font())
        self._tab_bar.setFixedHeight(m.tab_bar)
        for tab in (self.scene_tab, self.mesh_tab):
            tab.setFixedHeight(m.tab_bar - m.line)
        self._section_row.setContentsMargins(m.s3, 0, m.s3, 0)
        self.section_controls.setFixedHeight(m.tab_bar)
        self._section_row.setSpacing(m.s2)
        small = mono_font(QApplication.font(), 0.85)
        control_h = m.tab_bar - 2 * m.s1
        for button in (self.section_toggle, self.boundary_toggle, *self.axis_buttons.values()):
            button.setFont(small)
            button.setFixedHeight(control_h)
        self.section_toggle.configure(m, t)
        self.boundary_toggle.configure(m, t)
        self.section_slider.setFixedWidth(10 * m.u)
        self.menuBar().setFixedHeight(m.menubar)
        self._status_bar.setFixedHeight(m.status)
        self._selection_label.setFont(mono_font(QApplication.font(), 0.85))
        self._selection_label.setContentsMargins(m.s3, 0, m.s3, 0)
        for splitter in (self._outer, self._inner, self._right_split, self._left_split):
            splitter.setHandleWidth(m.hit)
        self._apply_limits(m)
        if self.viewer is not None:
            self._style_viewer()
        if self._unsubscribe is not None:
            self._refresh()  # rebuild icons for the new size
        if not self._first_show:
            self._apply_initial_sizes()

    def _apply_limits(self, m: Metrics) -> None:
        def width(widget: QWidget, key: str) -> None:
            lo, hi = LIMITS_U[key]
            widget.setMinimumWidth(lo * m.u)
            widget.setMaximumWidth(hi * m.u if hi is not None else 16777215)

        width(self._left, "left")
        width(self.monitors, "monitors")
        width(self._center, "center")
        self.console.setMinimumHeight(LIMITS_U["console"][0] * m.u)
        self._left_split.widget(0).setMinimumHeight(LIMITS_U["tree"][0] * m.u)
        self._left_split.widget(1).setMinimumHeight(LIMITS_U["properties"][0] * m.u)

    def _style_viewer(self) -> None:
        t = self._theme
        m = metrics()
        dpr = self.devicePixelRatioF()
        self.viewer.set_background(t.canvas)
        self._style_axes()
        self._empty_message.configure(t, m, dpr)
        self.telemetry.configure(t, m, dpr)
        self._update_telemetry()
        self.viewer.render()

    def _style_axes(self) -> None:
        t = self._theme
        m = metrics()
        self.viewer.hide_axes()
        # pyvista add_axes: color = label text color; x/y/z_color = axis colors; label_size is
        # forwarded to the marker. The widget occupies ~7u square, so labels scale with the font.
        side = max(1, min(self.viewer.width(), self.viewer.height()))
        frac = min(0.5, 7 * m.u / side)
        self.viewer.add_axes(
            color=t.text, x_color=t.axis_x, y_color=t.axis_y, z_color=t.axis_z,
            line_width=max(2, round(m.u / 9)), viewport=(0, 0, frac, frac),
            label_size=(0.4, 0.16),
        )

    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewer and event.type() == QEvent.Type.Resize and self.telemetry is not None:
            self._style_axes()
            self._layout_telemetry()
            self.viewer.render()  # auto-update is off: every visible change renders explicitly
        return super().eventFilter(obj, event)

    def _layout_telemetry(self) -> None:
        height = round(self.viewer.height() * self.devicePixelRatioF())
        self.telemetry.layout(height)

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
        """Region sizes from the fractions measured on the mockup (using the real size)."""
        width, height = self.width(), self.height()
        u = metrics().u
        lo, hi = LIMITS_U["left"]
        left = min(max(LEFT_INITIAL_U * u, lo * u), hi * u)
        monitors = round(LAYOUT.monitors * width)
        console = round(LAYOUT.console * height)
        self._outer.setSizes([left, max(0, width - left)])
        right_w = max(0, width - left)
        self._inner.setSizes([max(0, right_w - monitors), monitors])
        right_h = self._right_split.height()
        self._right_split.setSizes([max(0, right_h - console), console])
        column_h = self._left.height()
        tree = round(self._saved_tree_fraction() * column_h)
        self._left_split.setSizes([tree, max(0, self._left_split.height() - tree)])

    LEFT_SPLIT_KEY = "layout/left_tree_fraction"

    def _saved_tree_fraction(self) -> float:
        """Tree share of the left column: the user's last split, else the default (40 %)."""
        try:
            value = float(settings().value(self.LEFT_SPLIT_KEY, LAYOUT.tree_split))
        except (TypeError, ValueError):
            return LAYOUT.tree_split
        return value if 0.05 < value < 0.95 else LAYOUT.tree_split

    def _save_left_split(self, *_args) -> None:
        """Remember the tree/properties split after the user drags the handle."""
        column_h = self._left.height()
        if column_h > 0:
            tree_h = self._left_split.sizes()[0]
            s = settings()
            s.setValue(self.LEFT_SPLIT_KEY, tree_h / column_h)
            s.sync()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            self._apply_initial_sizes()  # needs the real size
            if self.viewer is not None:
                self._style_viewer()  # axes viewport depends on the real viewer size

    # -- refresh -------------------------------------------------------------

    def _refresh(self) -> None:
        sim = self._project.sim
        self._domain_box = domain_box_for(self._project)
        self._rebuild_tree(sim.name, list(sim.geometry.parts))
        self.properties.show_node(*(self._selection or ("root", None)))
        self._sync_scene()
        self._update_selection_views()
        self._update_actions()
        self._update_title(sim.name)
        self._update_mesh_stale()
        self._update_mesh_button()

    def _node_icon(self, glyph: str, token: str) -> QIcon:
        color = QColor(getattr(self._theme, token))
        return make_glyph(glyph, color, self.tree.iconSize().height(), self.devicePixelRatioF())

    def _rebuild_tree(self, name: str, parts: list[Part]) -> None:
        wanted = self._selection
        t = self._theme
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            items: dict[Selection, QTreeWidgetItem] = {}

            def add(parent, kind: str, index: int | None, text: str, glyph: str, token: str,
                    eye: bool | None = None, muted: bool = False) -> QTreeWidgetItem:
                item = QTreeWidgetItem(parent, [text])
                item.setData(0, ROLE_NODE, (kind, index))
                item.setData(0, ROLE_EYE, eye)
                item.setIcon(0, self._node_icon(glyph, token))
                if muted:
                    item.setForeground(0, QColor(t.muted_text))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                items[(kind, index)] = item
                return item

            root = add(self.tree, "root", None, name, "dot", "text")
            geometry = add(root, "geometry", None, "Geometry", "folder", "text")
            parts_item = add(geometry, "parts", None, "Parts", "folder", "text")
            for i, part in enumerate(parts):
                status = part_status(self._project, part)
                broken = status == MISSING or (status != "none" and not self._loadable(part))
                item = add(parts_item, "part", i, part.name, "dot",
                           "warning" if broken else "accent_secondary",
                           eye=self.part_visibility.get(part.name, True))
                if broken:
                    item.setToolTip(0, "File not found" if status == MISSING else "Cannot load file")
            continua = add(root, "continua", None, "Continua", "folder", "text")
            add(continua, "mesh", None, "Mesh", "dot", "accent_secondary")
            physics_item = add(continua, "physics", None, "Physics", "dot", "accent")
            add(physics_item, "inflow", None, "Inflow", "dot", "accent")
            regions = add(root, "regions", None, "Regions", "folder", "text")
            fluid = add(regions, "fluid_domain", None, "Fluid Domain", "folder", "text")
            domain = self._project.sim.domain
            if domain.enabled:
                for bname in BOUNDARY_NAMES:
                    if bname == "symmetry" and domain.symmetry != "y_min":
                        continue
                    add(fluid, f"boundary_{bname}", None, bname, "dot", "accent")
            for i, part in enumerate(parts):  # one wall patch per part
                add(fluid, "wall", i, f"{part.name} (wall)", "dot", "accent")
            add(root, "solvers", None, "Solvers", "folder", "text")
            add(root, "reports", None, "Reports & Monitors", "folder", "text")
            self.tree.expandAll()
            self._root_item = root
            self.tree.setRootIndex(self.tree.indexFromItem(root))  # hide the root row
            self._items = items
            if wanted not in items:
                wanted = ("root", None)
            self._selection = wanted
            self.tree.setCurrentItem(items[wanted])
        finally:
            self.tree.blockSignals(False)
        self.node_badge.setText(f"{self.node_count()} Nodes")
        self._apply_filter()

    def _loadable(self, part: Part) -> bool:
        return report_for_part(self._project, part) is not None

    def node_count(self) -> int:
        """Real tree nodes shown (the hidden root row is not counted)."""
        return len(self._items) - 1

    def _on_eye_clicked(self, item: QTreeWidgetItem) -> None:
        kind, index = item.data(0, ROLE_NODE)
        if kind != "part" or index is None:
            return
        name = self._project.sim.geometry.parts[index].name
        visible = not self.part_visibility.get(name, True)
        self.part_visibility[name] = visible
        item.setData(0, ROLE_EYE, visible)
        self.tree.viewport().update()
        self._sync_scene()

    def _select_root(self) -> None:
        if self._root_item is not None:
            self.tree.setCurrentItem(self._root_item)

    def _selected_name(self) -> str:
        kind, index = self._selection or ("root", None)
        if kind == "root":
            return self._project.sim.name
        item = self._items.get((kind, index))
        return item.text(0) if item is not None else EMPTY

    def _on_viewer_pick(self, index: int) -> None:
        """A part was clicked in the viewer: select it in the tree."""
        item = self._items.get(("part", index))
        if item is not None:
            self.tree.setCurrentItem(item)

    def _selected_part(self) -> Part | None:
        index = self._selected_part_index()
        parts = self._project.sim.geometry.parts
        return parts[index] if index is not None and index < len(parts) else None

    def _sync_scene(self) -> None:
        """Bring the viewer's part actors in line with the project (add, remove, edit, undo)."""
        if self.scene is None:
            return
        changed = self.scene.sync(self._project, self.part_visibility, self._selected_part_index())
        self._apply_representation()
        if changed or self._framed_visibility != self.scene.has_visible():
            self._frame_parts()
        self._framed_visibility = self.scene.has_visible()
        self._update_empty_state()
        self.viewer.render()

    def _frame_parts(self) -> None:
        bounds = self.scene.visible_bounds()
        if bounds is not None:
            self.viewer.reset_camera(render=False, bounds=bounds)

    def _update_empty_state(self) -> None:
        """Hide the empty-scene grid and message when any part (or extra actor) is visible."""
        if self._scene_mode == "mesh":
            has_content = self.mesh_view is not None and self.mesh_view.has_mesh
        else:
            has_content = (self.scene is not None and self.scene.has_visible()) or bool(self.scene_actors)
        for actor in self._grid_actors:
            actor.SetVisibility(not has_content)
        if self._empty_message is not None:
            self._empty_message.set_text("No mesh yet" if self._scene_mode == "mesh" else EMPTY_MESSAGE)
            self._empty_message.set_visible(not has_content)

    def _selected_boundary(self) -> str | None:
        kind = (self._selection or ("root", None))[0]
        return kind.removeprefix("boundary_") if kind.startswith("boundary_") else None

    def _sync_domain(self) -> None:
        """Draw the domain box (if enabled and toggled on) and highlight the selected boundary."""
        if self.domain_view is None:
            return
        visible = (self.act_toggle_domain.isChecked() and self._project.sim.domain.enabled
                   and self._scene_mode == "geometry")
        self.domain_view.update(self._domain_box, visible, self._selected_boundary())
        self.viewer.render()

    def _update_selection_views(self) -> None:
        self._sync_domain()
        if self.scene is not None:
            self.scene.set_selected(self._selected_part_index())
            self.viewer.render()
        name = self._selected_name()
        self.props_name.setText(name)
        self._selection_label.setText(f"Active selection: {name}")
        self._update_telemetry()

    def _update_telemetry(self) -> None:
        """Real values only; the card is drawn inside the viewport by VTK."""
        values = {
            "parts": str(len(self._project.sim.geometry.parts)),
            "selected": self._selected_name(),
            "triangles": self._selected_triangles(),
            "cells": str(self.mesh_report.cells) if self.mesh_report and self.mesh_report.cells else EMPTY,
            "domain": self._domain_text(),
            "view": self.current_view,
        }
        self.telemetry_rows = [
            (label, values[key])
            for key, label in TELEMETRY_FIELDS
            if self._telemetry_show and self._telemetry_fields.get(key, False)
        ]
        if self.telemetry is not None:
            self.telemetry.set_rows(self.telemetry_rows)
            self._layout_telemetry()
            self.viewer.render()

    def _domain_text(self) -> str:
        box = self._domain_box
        if box is None or box.bounds is None or not self._project.sim.domain.enabled:
            return EMPTY
        return " \u00d7 ".join(f"{v:.3g}" for v in box.size) + " m"

    # -- meshing ---------------------------------------------------------------------

    def _update_mesh_button(self) -> None:
        running = self.mesh_worker.is_running()
        self.top_bar.set_mesh_state(None if running else readiness(self._project), running)

    def generate_mesh(self) -> None:
        """Generate Mesh / Stop: write the meshing case and run it in the background."""
        if self.mesh_worker.is_running():
            self.show_message("Stopping meshing...", "warning", log_it=False)
            log.warning("Stopping meshing at the user's request")
            self.mesh_worker.request_stop()
            return
        self._flush_edits()
        try:
            job = prepare_job(self._project)
        except (MeshingNotReady, CaseDirectoryNotOursError) as exc:
            self.show_message(str(exc), "error")
            return
        except OSError as exc:
            self.show_message(f"Could not prepare the meshing case: {exc}", "error")
            return
        self._mesh_patches = job.inputs.parts
        self._run_hash = inputs_hash(self._project)
        self.mesh_report = None
        self._mesh_hash = None
        self.properties.set_mesh_report(None)
        self.top_bar.set_run_state("Meshing")
        est = estimate_mesh(job.inputs.domain_bounds, job.inputs.reference_length, job.inputs.mesh)
        log.info("Meshing %s: background %d cells (base size %.4g m), surface levels %d-%d "
                 "(surface cells %.4g m)", job.case_dir, est.total_cells, est.base_size,
                 est.level_min, est.level_max, est.surface_size)
        self.mesh_worker.start(job.case_dir)
        self._update_mesh_stale()
        self._update_mesh_button()
        self._update_telemetry()

    def _load_mesh_record(self, project: Project) -> None:
        """Show the last saved mesh of ``project`` (case/vortexcfd_mesh.json), if there is one."""
        self.mesh_stale = False
        self._mesh_hash = None
        case_dir = case_dir_for(project)
        record = read_mesh_record(case_dir) if case_dir is not None else None
        if record is None:
            return
        self.mesh_report = record.report
        self._mesh_hash = record.inputs_hash
        self._mesh_patches = record.patches
        self.properties.set_mesh_report(record.report)
        log.info("Loaded the last mesh: %s", record.report.summary())
        if self.mesh_view is not None:
            try:
                self.mesh_view.load(case_dir, record.patches, self._symmetric())
                self.mesh_view.set_visible(self._scene_mode == "mesh")
            except Exception:
                log.exception("Could not load the saved mesh into the viewer")

    def _update_mesh_stale(self) -> None:
        """A shown mesh is out of date when the meshing inputs no longer match its hash."""
        stale = (
            self.mesh_report is not None and self._mesh_hash is not None
            and not self.mesh_worker.is_running() and inputs_hash(self._project) != self._mesh_hash
        )
        if stale == self.mesh_stale and self.properties._mesh_stale == stale:
            return
        self.mesh_stale = stale
        self.top_bar.set_mesh_stale(stale)
        self.properties.set_mesh_stale(stale)
        if self.mesh_view is not None:
            self.mesh_view.set_stale(stale, max(7, round(self._point_size * 0.75)))
            self.viewer.render()

    def _on_mesh_line(self, text: str) -> None:
        self.console.append_output(text)  # runs in the GUI thread (queued signal)

    def _on_mesh_step(self, name: str) -> None:
        log.info("Running %s", name)

    def _on_mesh_done(self, result) -> None:
        self.top_bar.set_run_state(None)
        if result.stopped:
            log.warning("Meshing stopped")
            self.show_message("Meshing stopped", "warning", log_it=False)
        elif not result.success:
            step = result.failed_step or "meshing"
            log.error("Meshing failed in %s (exit codes: %s)", step, result.exit_codes)
            self.show_message(f"Meshing failed in {step}; see the console", "error", log_it=False)
        else:
            report = result.report
            self.mesh_report = report
            self._mesh_hash = self._run_hash
            self.properties.set_mesh_report(report)
            log.info("Mesh: %s", report.summary())
            if report.layers:
                low = [c for c in report.layers if c.below_threshold]
                (log.warning if low else log.info)("Layers: %s", report.layer_summary())
            try:
                write_mesh_record(case_dir_for(self._project), MeshRecord(
                    report, self._run_hash or "", self._mesh_patches))
            except OSError as exc:
                log.warning("Could not save the mesh record: %s", exc)
            level = "success" if report.mesh_ok else "warning"
            self.show_message(f"Mesh generated: {report.summary()}", level, log_it=False)
            self._load_mesh_view()
        self._update_mesh_stale()
        self._update_mesh_button()
        self._update_telemetry()

    def _load_mesh_view(self) -> None:
        if self.mesh_view is None:
            return
        try:
            shown = self.mesh_view.load(case_dir_for(self._project), self._mesh_patches,
                                        self._symmetric())
        except Exception:  # VTK reader errors: the report is still valid
            log.exception("Could not load the mesh into the viewer")
            return
        if shown:
            self._set_scene_mode("mesh")

    def _set_scene_mode(self, mode: str) -> None:
        """Switch between the geometry scene and the mesh scene (tab bar)."""
        self._scene_mode = mode
        self.scene_tab.setChecked(mode == "geometry")
        self.mesh_tab.setChecked(mode == "mesh")
        if self.scene is not None:
            self.scene.enabled = mode == "geometry"
            self.scene.apply_visibility(self.part_visibility)
            self.mesh_view.set_visible(mode == "mesh")
            self._update_empty_state()
            self._sync_domain()
            bounds = self.mesh_view.bounds() if mode == "mesh" else self.scene.visible_bounds()
            if mode == "mesh":
                self._aim_at_section()
            elif bounds is not None:
                self.viewer.reset_camera(render=False, bounds=bounds)
            self._sync_section_controls()
            self.viewer.render()

    # -- mesh section plane -------------------------------------------------------------

    def _symmetric(self) -> bool:
        return self._project.sim.domain.symmetry == "y_min"

    def _aim_at_section(self) -> None:
        """Look at the section plane from its negative side and frame it (no render)."""
        view = self.mesh_view
        camera = view.camera_for_section() if view.section_enabled and view.section_actor else None
        if camera is not None:
            self.viewer.camera_position = camera
        bounds = view.focus_bounds()
        if bounds is not None:
            self.viewer.reset_camera(render=False, bounds=bounds)

    def _sync_section_controls(self) -> None:
        """Show the controls in the mesh scene and set the slider to the plane's offset."""
        view = self.mesh_view
        visible = self._scene_mode == "mesh" and view is not None and view.has_volume
        self.section_controls.setVisible(visible)
        if not visible or view.section_position is None:
            return
        lo, hi = view.volume_bounds()[2 * view.section_axis: 2 * view.section_axis + 2]
        fraction = (view.section_position - lo) / (hi - lo) if hi > lo else 0.0
        self.section_slider.blockSignals(True)
        self.section_slider.setValue(round(fraction * SECTION_SLIDER_STEPS))
        self.section_slider.blockSignals(False)

    def _on_section_toggled(self, on: bool) -> None:
        if self.mesh_view is None:
            return
        self.mesh_view.set_section(enabled=on)
        self._aim_at_section()
        self.viewer.render()

    def _on_section_axis(self, axis: int) -> None:
        if self.mesh_view is None:
            return
        self.mesh_view.set_section(axis=axis)
        self._aim_at_section()
        self._sync_section_controls()
        self.viewer.render()

    def _on_section_slider(self, value: int) -> None:
        """While the handle is dragged the plane is re-sliced at most every 150 ms (a preview);
        keyboard and programmatic changes slice at once; releasing the handle slices for good."""
        if not self.section_slider.isSliderDown():
            self._slice_at(value)
            return
        self._pending_slice = value
        if not self._slice_timer.isActive():
            self._flush_slice_preview()

    def _flush_slice_preview(self) -> None:
        if self._pending_slice is None:
            return
        value, self._pending_slice = self._pending_slice, None
        self._slice_at(value)
        self._slice_timer.start()  # no new preview before another 150 ms

    def _on_section_slider_released(self) -> None:
        self._slice_timer.stop()
        self._pending_slice = None
        self._slice_at(self.section_slider.value())  # the final, full re-slice

    def _slice_at(self, value: int) -> None:
        view = self.mesh_view
        if view is None or not view.has_volume:
            return
        lo, hi = view.volume_bounds()[2 * view.section_axis: 2 * view.section_axis + 2]
        view.set_section(position=lo + value / SECTION_SLIDER_STEPS * (hi - lo))
        self.viewer.render()

    def _on_boundaries_toggled(self, on: bool) -> None:
        if self.mesh_view is not None:
            self.mesh_view.set_boundaries(on)
            self.viewer.render()

    def _selected_triangles(self) -> str:
        part = self._selected_part()
        report = report_for_part(self._project, part) if part is not None else None
        return str(report.n_triangles) if report is not None else EMPTY

    def _set_telemetry(self, show: bool | None = None, field: str | None = None,
                       checked: bool = True) -> None:
        if show is not None:
            self._telemetry_show = show
        if field is not None:
            self._telemetry_fields[field] = checked
        save_telemetry_settings(self._telemetry_show, self._telemetry_fields)
        self._update_telemetry()

    def _set_current_view(self, name: str) -> None:
        self.current_view = name
        self.top_bar.set_active_view(name)
        self._update_telemetry()

    def _on_camera_interaction(self) -> None:
        self._set_current_view("Custom")

    def _view(self, method: str) -> None:
        if self.viewer is None:
            return
        getattr(self.viewer, method)()
        self.viewer.render()
        label = next((text for text, m, _ in VIEW_BUTTONS if m == method), None)
        if method == FIT_METHOD:  # Fit is momentary: the active view stays as it was
            self.top_bar.set_active_view(self.current_view)
        elif label is not None:
            self._set_current_view(label)

    def add_scene_actor(self, actor) -> None:
        """Register a geometry actor so the wireframe toggle applies to it."""
        self.scene_actors.append(actor)
        self._apply_representation()
        self._update_empty_state()

    def _apply_representation(self) -> None:
        parts = self.scene.actors if self.scene is not None else []
        for actor in (*parts, *self.scene_actors):
            actor.prop.style = "wireframe" if self.wireframe else "surface"
            actor.prop.show_edges = self.wireframe  # edges are off unless wireframe is on
        if self.viewer is not None:
            self.viewer.render()

    def _set_wireframe(self, on: bool) -> None:
        self.wireframe = on
        self._apply_representation()

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

    # -- region toggles ------------------------------------------------------

    def _toggle_region(self, key: str, widgets: list[QWidget], splitters: list[QSplitter]) -> None:
        """Hide/show regions, restoring the previous sizes of ``splitters`` when shown."""
        if widgets[0].isVisibleTo(self):  # currently visible -> hide
            self._saved_sizes[key] = [s for sp in splitters for s in sp.sizes()]
            for w in widgets:
                w.hide()
        else:
            for w in widgets:
                w.show()
            saved = self._saved_sizes.get(key)
            if saved:
                pos = 0
                for sp in splitters:
                    n = sp.count()
                    sp.setSizes(saved[pos:pos + n])
                    pos += n

    def _toggle_sidebars(self) -> None:
        """Hide/show the left column and the monitors panel together."""
        self._toggle_region("sidebars", [self._left, self.monitors], [self._outer, self._inner])
        self.act_toggle_monitors.setChecked(self.monitors.isVisibleTo(self))

    def _toggle_monitors(self) -> None:
        self._toggle_region("monitors", [self.monitors], [self._inner])
        self.act_toggle_monitors.setChecked(self.monitors.isVisibleTo(self))

    def _toggle_console(self) -> None:
        self._toggle_region("console", [self.console], [self._right_split])
        self.act_toggle_console.setChecked(self.console.isVisibleTo(self))

    def _on_current_item_changed(self, current, _previous) -> None:
        if current is None:
            return
        self._selection = current.data(0, ROLE_NODE)
        self.properties.show_node(*self._selection)
        self._update_selection_views()
        self._update_actions()

    def _update_title(self, name: str) -> None:
        path = self._project.path
        file_name = path.name if path else "Untitled"
        self.setWindowTitle(f"{name}[*] - {file_name} - VortexCFD")
        self.setWindowModified(self._project.dirty)
        self.top_bar.set_project(file_name, self._project.dirty)

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
        self.act_import = action("&Import Surface...", self.import_surface, "Ctrl+I")
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
        self.act_toggle_monitors = action("&Monitors Panel", self._toggle_monitors)
        self.act_toggle_console = action("&Console", self._toggle_console)
        for act in (self.act_toggle_monitors, self.act_toggle_console):
            act.setCheckable(True)
            act.setChecked(True)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.act_new, self.act_open, self.act_import])
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
        view_menu.addActions([self.act_toggle_monitors, self.act_toggle_console])
        self.act_toggle_domain = action("Domain &Box", lambda checked=False: self._sync_domain())
        self.act_toggle_domain.setCheckable(True)
        self.act_toggle_domain.setChecked(True)
        view_menu.addAction(self.act_toggle_domain)
        view_menu.addSeparator()
        tel_menu = view_menu.addMenu("Viewport &Telemetry")
        self.act_tel_show = action("Show telemetry", lambda checked=False: self._set_telemetry(show=checked))
        self.act_tel_show.setCheckable(True)
        self.act_tel_show.setChecked(self._telemetry_show)
        tel_menu.addAction(self.act_tel_show)
        tel_menu.addSeparator()
        self.act_tel_fields: dict[str, QAction] = {}
        for key, label in TELEMETRY_FIELDS:
            act = action(
                label, lambda checked=False, k=key: self._set_telemetry(field=k, checked=checked)
            )
            act.setCheckable(True)
            act.setChecked(self._telemetry_fields[key])
            self.act_tel_fields[key] = act
            tel_menu.addAction(act)

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
        log.info("Saved %s", self._project.path)
        self.show_message(f"Saved {self._project.path}", "success")
        return True

    def import_surface(self) -> None:
        """File > Import Surface: copy a surface file into <project>/geometry/ and add a Part."""
        self._flush_edits()
        if self._project.path is None and not self.save_as():  # the copy needs a project folder
            return
        source = self.dialogs.ask_import_path()
        if source is None:
            return
        units = self.dialogs.ask_units()
        if units is None:
            return
        project_dir = self._project.path.parent
        folder = project_dir / "geometry"
        dest = None
        try:
            folder.mkdir(exist_ok=True)
            dest = self._unique_path(folder, source.name)
            shutil.copy2(source, dest)
            report = surface_report(dest, units)
        except (OSError, SurfaceLoadError) as exc:
            if dest is not None:
                dest.unlink(missing_ok=True)
            self.show_message(f"Could not import {source.name}: {exc}", "error")
            return
        taken = {p.name for p in self._project.sim.geometry.parts}
        name = self._unique_name(source.stem, taken)
        relative = Path(os.path.relpath(dest, project_dir)).as_posix()
        previous = self._selection
        self._selection = ("part", len(taken))  # the observer refresh selects the new part
        try:
            self._project.add_part(Part(name=name, source_file=relative, units=units))
        except (ValueError, TypeError) as exc:
            self._selection = previous
            dest.unlink(missing_ok=True)
            self.show_message(f"Could not import {source.name}: {exc}", "error")
            return
        log.info("Imported %s as part '%s' (units: %s)", source.name, name, units)
        log.info("Checks for '%s': %s", name, report.summary())
        self.show_message(f"Imported {source.name} as '{name}'", "success", log_it=False)

    @staticmethod
    def _unique_path(folder: Path, file_name: str) -> Path:
        candidate = folder / file_name
        stem, suffix, n = candidate.stem, candidate.suffix, 1
        while candidate.exists():
            n += 1
            candidate = folder / f"{stem}_{n}{suffix}"
        return candidate

    @staticmethod
    def _unique_name(base: str, taken: set[str]) -> str:
        name, n = base, 1
        while name in taken:
            n += 1
            name = f"{base}_{n}"
        return name

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
            self.show_message(f"Could not open {path}: {exc}", "error", log_it=False)
            return
        self.set_project(project)
        log.info("Opened %s", path)
        self.show_message(f"Opened {path}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        if self.mesh_worker.is_running():
            self.mesh_worker.request_stop()
        if self.viewer is not None:
            self.viewer.close()  # release VTK interactor resources
        console_log.detach(self._console_handler)
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
