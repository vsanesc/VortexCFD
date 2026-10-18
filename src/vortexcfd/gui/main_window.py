"""Main window bound to a Project, laid out after docs/design/mockup-v1.png."""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

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
    QComboBox,
    QDoubleSpinBox,
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

from vortexcfd.core.model import Part, StoppingCriteria
from vortexcfd.core.reports import available_reports
from vortexcfd.foam import convergence
from vortexcfd.foam.physics_case import flow_direction
from vortexcfd.core.project import Project
from vortexcfd.gui import console as console_log
from vortexcfd.gui.console import ConsolePanel
from vortexcfd.gui.dialogs import Dialogs
from vortexcfd.gui.icons import logo_icon, make_glyph
from vortexcfd.gui.monitors import MonitorsPanel
from vortexcfd.geometry.checks import basic_report, cached_report
from vortexcfd.geometry.cad import BREP_EXTENSIONS, CAD_EXTENSIONS, CadImportError, read_cad
from vortexcfd.geometry.loader import stl_solid_names
from vortexcfd.geometry.regions import RegionError
from vortexcfd.gui import part_ops
from vortexcfd.geometry.loader import SurfaceLoadError
from vortexcfd.gui.properties_panel import PropertiesPanel
from vortexcfd.geometry.domain import BOUNDARY_NAMES
from vortexcfd.foam.mesh_case import (
    CaseDirectoryNotOursError,
    force_report_keys,
    part_patch_names,
    remove_results,
)
from vortexcfd.foam.mesh_estimate import estimate_mesh
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.gui.geometry_worker import GeometryWorker, IntersectionChecker, snapshot
from vortexcfd.gui.mesh_worker import MeshWorker
from vortexcfd.foam.logparse import parse_log_text
from vortexcfd.foam.run_record import RunRecord, read_run_record, write_run_record
from vortexcfd.foam.solver_run import CRITERIA_MET
from vortexcfd.gui import solving
from vortexcfd.gui.solver_worker import SolverWorker
from vortexcfd.gui.study_control import StudyControlMixin
from vortexcfd.foam.results import latest_result_time
from vortexcfd.gui import paraview
from vortexcfd.gui.colormaps import COLORMAPS, DEFAULT_COLORMAP
from vortexcfd.gui.results_scene import DISPLAY_MODES, RANGE_MODES, ResultsLoader, ResultsView
from vortexcfd.gui.section_tool import SectionTool
from vortexcfd.foam.mesh_record import MeshRecord, read_mesh_record, write_mesh_record
from vortexcfd.gui.meshing import (
    MeshingNotReady,
    case_dir_for,
    inputs_hash,
    layer_warning,
    prepare_job,
    readiness,
    thin_part_warnings,
)
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
from vortexcfd.gui.widgets import DotButton, FlowLayout, SearchField, SectionHeader

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


class MainWindow(StudyControlMixin, QMainWindow):
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
        # Geometry jobs and self-intersection checks off the GUI thread (D-073).
        self.geometry_worker = GeometryWorker(self)
        self.geometry_worker.finished.connect(self._on_geometry_finished)
        self.geometry_worker.failed.connect(self._on_geometry_failed)
        self._geometry_jobs: dict[int, tuple] = {}
        self.geometry_busy = False
        self.intersections = IntersectionChecker(self)
        self.intersections.checked.connect(self._on_intersections_checked)
        self._announce_checks: dict[tuple[str, str], str] = {}
        self.mesh_worker = MeshWorker(self)
        self.mesh_worker.line.connect(self._on_mesh_line)
        self.mesh_worker.step.connect(self._on_mesh_step)
        self.mesh_worker.finished.connect(self._on_mesh_done)
        self.run_record: RunRecord | None = None
        self.results_stale = False
        self._solve_hash: str | None = None  # results hash at the start of the running solver
        self._solve_stopping: StoppingCriteria | None = None  # the running solver's stopping criteria
        self.solver_worker = SolverWorker(self)
        self.solver_timeout_s: float | None = None  # wall-clock limit of a solver run (tests set one)
        self.solver_worker.line.connect(self._on_solver_line)
        self.solver_worker.step.connect(self._on_solver_step)
        self.solver_worker.finished.connect(self._on_solver_done)
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
        self.properties.regions_selected.connect(self._on_regions_selected)
        self.properties.retessellate_requested.connect(self._retessellate)
        self.properties.request_intersections = self.intersections.request
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
        # Permanent (right): QStatusBar keeps temporary messages (left) off permanent widgets, so the
        # two never overlap (docs/QUESTIONS.md item 58).
        self._selection_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._status_bar.addPermanentWidget(self._selection_label)
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
        self.results_tab = QPushButton("Results Scene")
        self._tab_group = QButtonGroup(self)
        for button, mode in ((self.scene_tab, "geometry"), (self.mesh_tab, "mesh"),
                             (self.results_tab, "results")):
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
        self._build_results_controls()
        center_layout.addWidget(self.results_controls)
        self.viewer = None
        self.results_view: ResultsView | None = None
        self.results_loader = ResultsLoader(self)
        self.results_loader.loaded.connect(self._on_results_loaded)
        self.results_loader.failed.connect(self._on_results_failed)
        self._results_shown_time: str | None = None  # time of the data in results_view
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
            self.scene.on_cell_pick = self._on_triangle_pick
            self.domain_view = DomainView(self.viewer, self._theme)
            self.mesh_view = MeshView(self.viewer, self._theme)
            self.results_view = ResultsView(self.viewer, self._theme)
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
        self.monitors.slot_assigned.connect(self._assign_report)
        self.monitors.updated.connect(
            lambda: self.properties.set_report_monitor(self.monitors.reports, self.monitors.case_dir))
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
        self.top_bar.run_clicked.connect(self.run_solver)
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
        self._init_studies()  # mesh study and polar sweep workers (gui/study_control.py)
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
        if self.solver_worker.is_running():
            self.solver_worker.request_stop()
        for worker in (self.study_worker, self.sweep_worker):
            if worker.is_running():
                worker.request_stop()
        self.mesh_report = None
        self.properties.set_mesh_report(None)
        if self.mesh_view is not None:
            self.mesh_view.clear()
            self._set_scene_mode("geometry")
        self.properties.set_project(project)
        self._load_mesh_record(project)
        self._load_run_record(project)
        self._load_study_records()
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
        for tab in (self.scene_tab, self.mesh_tab, self.results_tab):
            tab.setFixedHeight(m.tab_bar - m.line)
        self._results_row.setContentsMargins(m.s3, m.s1, m.s3, m.s1)
        self._results_row.set_spacing(m.s2, m.s1)
        for w in self._results_widgets():
            w.setFont(mono_font(QApplication.font(), 0.85))
            w.setFixedHeight(m.tab_bar - 2 * m.s1)
        pad = 4 * m.s3
        self.paraview_button.setMinimumWidth(
            self.paraview_button.fontMetrics().horizontalAdvance(self.paraview_button.text()) + pad)
        if self.results_view is not None:
            self.results_view.font_size = self._point_size
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
        self._update_results_stale()
        self._update_run_button()
        self.monitors.kpis.set_options(available_reports(
            force_report_keys(sim.geometry.parts), [p.name for p in sim.reports.probes]))
        self.monitors.set_assignments(list(sim.reports.slots))
        if not self.solver_worker.is_running():  # a running solver keeps the criteria it started with
            self.monitors.set_stopping(sim.solvers.stopping)
        self._update_results_tab()

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
            labels = [label for part, patches in zip(parts, part_patch_names(parts))
                      for label in (patches if part.regions else (part.name,))]
            for i, label in enumerate(labels):  # one wall per patch (D-071); a plain part shows its name
                add(fluid, "wall", i, f"{label} (wall)", "dot", "accent")
            solvers_item = add(root, "solvers", None, "Solvers", "folder", "text")
            add(solvers_item, "stopping", None, "Stopping Criteria", "dot", "accent")
            reports = add(root, "reports", None, "Reports & Monitors", "folder", "text")
            add(reports, "reference_values", None, "Reference Values", "dot", "accent")
            add(reports, "probes", None, "Probes", "dot", "accent")
            add(reports, "mesh_study", None, "Mesh Study", "dot", "accent")
            add(reports, "polar_sweep", None, "Polar Sweep", "dot", "accent")
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

    def _on_triangle_pick(self, index: int, triangle: int) -> None:
        """A triangle of a part was clicked: select its region in the part's Regions list (D-071)."""
        if self._selected_part_index() != index:
            return
        try:
            name = part_ops.region_of_triangle(self._project, index, triangle)
        except (OSError, SurfaceLoadError, RegionError, ValueError):
            return
        if name is not None:
            self.properties.select_regions([name])

    def _on_regions_selected(self, index: int, names: list) -> None:
        """Highlight the selected regions' triangles in the viewer."""
        if self.scene is None:
            return
        triangles = []
        if names and index == self._selected_part_index():
            try:
                part = self._project.sim.geometry.parts[index]
                ids = part_ops.part_base_ids(self._project, part)
                members = [m for r in part_ops.effective_regions(part, ids) if r.name in names for m in r.members]
                triangles = np.flatnonzero(np.isin(ids, members)).tolist()
            except (OSError, SurfaceLoadError, RegionError, ValueError, IndexError):
                triangles = []
        self.scene.show_regions(index if triangles else None, triangles)
        self.viewer.render()

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
        elif self._scene_mode == "results":
            has_content = self.results_view is not None and self.results_view.has_results
        else:
            has_content = (self.scene is not None and self.scene.has_visible()) or bool(self.scene_actors)
        for actor in self._grid_actors:
            actor.SetVisibility(not has_content)
        if self._empty_message is not None:
            self._empty_message.set_text({"mesh": "No mesh yet", "results": "Loading results"}.get(
                self._scene_mode, EMPTY_MESSAGE))
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
            if self._selected_part_index() is None:
                self.scene.show_regions(None, [])
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
            "field_range": self._field_range_text(),
        }
        self.telemetry_rows = [
            (label, values[key])
            for key, label in TELEMETRY_FIELDS
            if self._telemetry_show and self._telemetry_fields.get(key, False)
            and (key != "field_range" or self._scene_mode == "results")  # a results-only row
        ]
        if self.telemetry is not None:
            self.telemetry.set_rows(self.telemetry_rows)
            self._layout_telemetry()
            self.viewer.render()

    def _field_range_text(self) -> str:
        view = self.results_view
        if self._scene_mode != "results" or view is None or view.field() is None:
            return EMPTY
        rng = view.field_range()
        if rng is None:
            return EMPTY
        units = f" {view.field().units}" if view.field().units else ""
        return f"{rng[0]:.4g} \u2013 {rng[1]:.4g}{units}"

    def _domain_text(self) -> str:
        box = self._domain_box
        if box is None or box.bounds is None or not self._project.sim.domain.enabled:
            return EMPTY
        return " \u00d7 ".join(f"{v:.3g}" for v in box.size) + " m"

    # -- meshing ---------------------------------------------------------------------

    def _update_mesh_button(self) -> None:
        running = self.mesh_worker.is_running()
        reason = None if running else readiness(self._project)
        if not running and self.solver_worker.is_running():
            reason = "The solver is running: stop it first."
        if not running and self.study_running():
            reason = self.study_running()
        if not running and self.geometry_busy:
            reason = f"{self.geometry_worker.label} is running."
        warning = None
        if not running and reason is None:
            warnings = [w for w in (layer_warning(self._project), *thin_part_warnings(self._project)) if w]
            warning = "\n".join(warnings) or None
        self.top_bar.set_mesh_state(reason, running, warning)

    def generate_mesh(self) -> None:
        """Generate Mesh / Stop: write the meshing case and run it in the background."""
        if self.geometry_busy and not self.mesh_worker.is_running():
            self.show_message(f"{self.geometry_worker.label} is running.", "error")
            return
        if self.solver_worker.is_running():
            self.show_message("The solver is running: stop it first.", "error")
            return
        if self.study_running() and not self.mesh_worker.is_running():
            self.show_message(self.study_running(), "error")
            return
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
        self._mesh_patches = job.inputs.patches
        self._run_hash = inputs_hash(self._project)
        self.mesh_report = None
        self._mesh_hash = None
        self.properties.set_mesh_report(None)
        self.top_bar.set_run_state("Meshing")
        est = estimate_mesh(job.inputs.domain_bounds, job.inputs.reference_length, job.inputs.mesh)
        log.info("Meshing %s: background %d cells (base size %.4g m), surface levels %d-%d "
                 "(surface cells %.4g m)", job.case_dir, est.total_cells, est.base_size,
                 est.level_min, est.level_max, est.surface_size)
        for text in thin_part_warnings(self._project):
            log.warning(text)
        self.mesh_worker.start(job.case_dir, job.inputs.patches)
        self._update_mesh_stale()
        self._update_mesh_button()
        self._update_run_button()
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
        report = self.mesh_report
        lost = report.lost_parts if report is not None else ()
        self.top_bar.set_mesh_error(f"Mesh invalid: Part {lost[0]} lost" if lost else None)
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
            self._clear_results_after_meshing()
            for text in report.lost_messages():
                log.error(text)
            if report.lost_parts:
                self.show_message(f"Mesh invalid: {report.lost_messages()[0]}", "error", log_it=False)
            else:
                level = "success" if report.mesh_ok else "warning"
                self.show_message(f"Mesh generated: {report.summary()}", level, log_it=False)
            self._load_mesh_view()
        self._update_mesh_stale()
        self._update_mesh_button()
        self._update_run_button()
        self._update_telemetry()

    # -- solving ---------------------------------------------------------------------

    def solve_readiness(self) -> str | None:
        """Why Run Solver is disabled (None: it can run)."""
        busy = self.study_running()
        if busy is not None:
            return busy
        return solving.readiness(
            self._project, has_mesh=self.mesh_report is not None, mesh_stale=self.mesh_stale,
            meshing=self.mesh_worker.is_running(),
            lost_parts=self.mesh_report.lost_parts if self.mesh_report is not None else (),
        )

    def _update_run_button(self) -> None:
        running = self.solver_worker.is_running()
        self.top_bar.set_solver_state(None if running else self.solve_readiness(), running)
        self._update_study_state()

    def run_solver(self) -> None:
        """Run Solver / Stop: write the solver files into the meshed case and run simpleFoam."""
        if self.solver_worker.is_running():
            self.show_message("Stopping the solver...", "warning", log_it=False)
            log.warning("Stopping the solver at the user's request")
            self.solver_worker.request_stop()
            return
        self._flush_edits()
        reason = self.solve_readiness()
        if reason is not None:
            self.show_message(reason, "error")
            return
        try:
            case_dir = solving.prepare_solver_case(self._project)
        except (solving.SolvingNotReady, MeshingNotReady) as exc:
            self.show_message(str(exc), "error")
            return
        except OSError as exc:
            self.show_message(f"Could not write the solver case: {exc}", "error")
            return
        self._solve_hash = solving.results_hash(self._project)
        self._solve_stopping = self._project.sim.solvers.stopping.model_copy(deep=True)
        self.run_record = None
        self.properties.set_run_record(None)
        self.monitors.start_run(case_dir, self._solve_stopping)
        self.top_bar.set_run_state("Solving")
        log.info("Running simpleFoam in %s", case_dir)
        cores = self._project.sim.solvers.cores
        if cores > 1:
            log.info("Running simpleFoam on %d cores (decomposePar, mpirun, reconstructPar)", cores)
        self.solver_worker.start(case_dir, timeout_s=self.solver_timeout_s, stopping=self._solve_stopping,
                                 cores=cores)
        self._update_results_stale()
        self._update_run_button()
        self._update_mesh_button()

    def _load_run_record(self, project: Project) -> None:
        """Show the last saved run of ``project`` (case/vortexcfd_run.json), if there is one."""
        case_dir = case_dir_for(project)
        self.run_record = read_run_record(case_dir) if case_dir is not None else None
        self.results_stale = False
        self.top_bar.set_results_stale(False)
        self.properties.set_run_record(self.run_record)
        self.monitors.clear()
        if self.run_record is None:
            return
        log.info("Loaded the last solver run: %s after %d iterations",
                 self.run_record.label, self.run_record.iterations)
        try:
            text = (case_dir / "log.simpleFoam").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        record = self.run_record
        self.monitors.set_stopping(project.sim.solvers.stopping)
        self.monitors.load_run(case_dir, parse_log_text(text),
                               (record.state, record.stopped_by, record.met_iteration or record.iterations))

    def _assign_report(self, slot: int, report_id) -> None:
        """A report slot's menu: store the assignment in the project (undoable)."""
        slots = list(self._project.sim.reports.slots)
        slots[slot] = report_id
        self._run_edit(lambda: self._project.update_reports(slots=slots))

    def _update_results_stale(self, force: bool = False) -> None:
        """Saved results are out of date when the solver inputs no longer match their hash."""
        record = self.run_record
        stale = (
            record is not None and not self.solver_worker.is_running()
            and solving.results_hash(self._project) != record.inputs_hash
        )
        if not force and stale == self.results_stale and self.properties._results_stale == stale:
            return
        self.results_stale = stale
        self.top_bar.set_results_stale(stale)
        self.results_stale_label.setVisible(stale and self._scene_mode == "results")
        self.properties.set_run_record(record, stale)

    def _on_solver_line(self, text: str) -> None:
        self.console.append_output(text)  # runs in the GUI thread (queued signal)

    def _on_solver_step(self, step) -> None:
        self.monitors.add_step(step)

    def _on_solver_done(self, result) -> None:
        self.top_bar.set_run_state(None)
        stopping = self._solve_stopping or StoppingCriteria(criteria=[])
        criteria, stopped_by = convergence.criteria_outcome(stopping, result.criteria_met)
        labels = convergence.met_labels(stopping, result.criteria_met)
        met_at = result.met_iteration or result.iterations
        self.monitors.set_outcome(result.state, stopped_by, met_at)
        self.monitors.end_run()
        if result.crash:
            self.console.append_error(result.crash)
        record = RunRecord(result.state, result.iterations, result.final_residuals,
                           self._solve_hash or "", result.exit_code, criteria, stopped_by, labels,
                           result.met_iteration, round(result.duration_s, 1), result.cores)
        self.run_record = record
        try:
            write_run_record(case_dir_for(self._project), record)
        except (OSError, TypeError) as exc:
            log.warning("Could not save the run record: %s", exc)
        residuals = ", ".join(f"{k} {v:.3g}" for k, v in result.final_residuals.items()) or "none"
        text = f"Solver: {record.label} after {result.iterations} iterations"
        if stopped_by:
            at = (f" at iteration {result.met_iteration}"
                  if result.met_iteration is not None and result.met_iteration != result.iterations else "")
            text += f" ({'; '.join(stopped_by)}{at})"
        elif result.state == "iteration_limit" and criteria:
            text += " without meeting the stopping criteria"
        if result.state == CRITERIA_MET:
            log.info("%s (final residuals: %s)", text, residuals)
            self.show_message(text, "success", log_it=False)
        elif result.state == "crashed":
            log.error("%s (exit code %s)", text, result.exit_code)
            self.show_message(f"{text}; see the console", "error", log_it=False)
        else:
            log.warning("%s (final residuals: %s)", text, residuals)
            self.show_message(text, "warning", log_it=False)
        self._update_results_stale(force=True)
        self._update_run_button()
        self._update_mesh_button()
        self._results_shown_time = None  # new results on disk
        self._update_results_tab()

    def _clear_results_after_meshing(self) -> None:
        """A new mesh makes the previous solver results meaningless: delete them (D-051)."""
        try:
            removed = remove_results(case_dir_for(self._project))
        except (OSError, CaseDirectoryNotOursError) as exc:
            log.warning("Could not remove the previous results: %s", exc)
            return
        if removed:
            log.info("Removed the previous results for the new mesh: %s", ", ".join(removed))
        self.run_record = None
        self.properties.set_run_record(None)
        self.monitors.clear()
        self._update_results_stale(force=True)
        self._update_results_tab()

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
        """Switch between the geometry, mesh and results scenes (tab bar)."""
        self._scene_mode = mode
        self.scene_tab.setChecked(mode == "geometry")
        self.mesh_tab.setChecked(mode == "mesh")
        self.results_tab.setChecked(mode == "results")
        self.results_controls.setVisible(mode == "results")
        if mode == "results":
            self.results_stale_label.setVisible(self.results_stale)
            self._update_paraview_button()
        if self.scene is not None:
            self.scene.enabled = mode == "geometry"
            self.scene.apply_visibility(self.part_visibility)
            self.mesh_view.set_visible(mode == "mesh")
            self.results_view.set_visible(mode == "results")
            if mode == "results" and self._results_shown_time != self.results_time():
                self._load_results()
            self._update_empty_state()
            self._sync_domain()
            if mode == "mesh":
                bounds = self.mesh_view.bounds()
            elif mode == "results":
                bounds = self.results_view.bounds()
            else:
                bounds = self.scene.visible_bounds()
            if mode == "mesh":
                self._aim_at_section()
            elif mode == "results" and bounds is not None:
                self._view_from_upstream(bounds)
            elif bounds is not None:
                self.viewer.reset_camera(render=False, bounds=bounds)
            self._sync_section_controls()
            self._update_telemetry()
            self.viewer.render()

    # -- results scene ---------------------------------------------------------------------

    def _build_results_controls(self) -> None:
        """Field, colormap, range, display mode, the stale strip and Open in ParaView (results only)."""
        self.results_controls = QWidget()
        self.results_controls.setObjectName("tabBar")
        self.results_controls.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # A flow layout: the controls wrap onto a second row when they do not fit, so the trailing
        # Open in ParaView button is never clipped (docs/QUESTIONS.md item 57).
        row = FlowLayout(self.results_controls, stretch_last=True)
        self._results_row = row
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.results_controls.setSizePolicy(policy)
        self.field_combo = QComboBox()
        self.field_combo.setToolTip("Field shown on the walls and the section")
        self.colormap_combo = QComboBox()
        self.colormap_combo.addItems(list(COLORMAPS))
        self.colormap_combo.setCurrentText(DEFAULT_COLORMAP)
        self.colormap_combo.setToolTip("Colormap")
        self.range_combo = QComboBox()
        self.range_combo.addItems(list(RANGE_MODES))
        self.range_combo.setToolTip("Colour range: auto (data), fixed (min/max) or symmetric about zero")
        self.range_min = QDoubleSpinBox()
        self.range_max = QDoubleSpinBox()
        for spin, tip in ((self.range_min, "Fixed range minimum"), (self.range_max, "Fixed range maximum")):
            spin.setRange(-1e12, 1e12)
            spin.setDecimals(6)
            spin.setToolTip(tip)
            spin.setVisible(False)
        self.display_combo = QComboBox()
        self.display_combo.addItems(list(DISPLAY_MODES))
        self.display_combo.setToolTip("Show the field on the walls, on the section plane, or both")
        for combo in (self.field_combo, self.colormap_combo, self.range_combo, self.display_combo):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.separation_toggle = DotButton("Separation")
        self.separation_toggle.setCheckable(True)
        self.separation_toggle.setToolTip("Highlight the wall faces where Cf_x < 0 (near-wall flow running "
                                          "upstream: separated or recirculating) in the error colour")
        self.separation_toggle.toggled.connect(lambda _on: self._apply_results_controls())
        self.sections_button = QPushButton("Sections")
        self.sections_button.setObjectName("tbBtn")
        self.sections_button.setToolTip("Cp against x/c on cuts of the walls by planes normal to y (spanwise) or z")
        self.sections_button.clicked.connect(self.open_sections)
        self.section_tool: SectionTool | None = None
        self.results_stale_label = QLabel("Results out of date: run the solver again")
        self.results_stale_label.setObjectName("statusWarn")
        self.results_stale_label.setVisible(False)
        self.paraview_button = QPushButton("Open in ParaView")
        self.paraview_button.setObjectName("tbBtn")
        self.paraview_button.clicked.connect(self.open_in_paraview)
        for widget in (self.field_combo, self.colormap_combo, self.range_combo, self.range_min,
                       self.range_max, self.display_combo, self.separation_toggle, self.sections_button):
            row.addWidget(widget)
        row.addWidget(self.results_stale_label)
        row.addWidget(self.paraview_button)
        for combo in (self.field_combo, self.colormap_combo, self.range_combo, self.display_combo):
            combo.currentTextChanged.connect(lambda _t: self._apply_results_controls())
        for spin in (self.range_min, self.range_max):
            spin.editingFinished.connect(self._apply_results_controls)
        self.results_controls.hide()

    def _results_widgets(self) -> list[QWidget]:
        return [self.field_combo, self.colormap_combo, self.range_combo, self.range_min, self.range_max,
                self.display_combo, self.separation_toggle, self.sections_button, self.paraview_button]

    def results_time(self) -> str | None:
        """The latest time directory with results in the project's case, or None."""
        case_dir = case_dir_for(self._project)
        return latest_result_time(case_dir) if case_dir is not None else None

    def _update_results_tab(self) -> None:
        """Show the Results Scene tab only when the case has results; refresh its controls."""
        time = self.results_time()
        self.results_tab.setVisible(time is not None)
        if time is None:
            self._results_shown_time = None
            if self.results_view is not None:
                self.results_view.clear()
            if self._scene_mode == "results":
                self._set_scene_mode("geometry")
            return
        self._fill_field_combo(time)
        self.results_stale_label.setVisible(self.results_stale)
        self._update_paraview_button()
        if self._scene_mode == "results" and time != self._results_shown_time:
            self._load_results()

    def _fill_field_combo(self, time: str) -> None:
        from vortexcfd.foam.results import available_fields

        fields = available_fields(case_dir_for(self._project), time)
        labels = [f.label for f in fields]
        self._field_keys = {f.label: f.key for f in fields}
        if [self.field_combo.itemText(i) for i in range(self.field_combo.count())] == labels:
            return
        current = self.field_combo.currentText()
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        self.field_combo.addItems(labels)
        if current in labels:
            self.field_combo.setCurrentText(current)
        elif "Cp" in labels:
            self.field_combo.setCurrentText("Cp")
        self.field_combo.blockSignals(False)

    def field_list(self) -> list[str]:
        return [self.field_combo.itemText(i) for i in range(self.field_combo.count())]

    def _load_results(self) -> None:
        """Read the latest results on a worker thread (the view is filled when they arrive)."""
        time = self.results_time()
        if time is None or self.results_view is None or self.results_loader.is_running():
            return
        self.show_message(f"Loading results (time {time})...", log_it=False)
        self._results_loading_time = time
        self.results_loader.start(case_dir_for(self._project), time, self._mesh_patches)

    def _on_results_loaded(self, data) -> None:
        if self.results_view is None:
            return
        self._results_shown_time = data.time
        self._apply_results_controls(data)
        log.info("Results loaded: time %s, fields %s", data.time, ", ".join(f.label for f in data.fields))
        self.show_message(f"Results at time {data.time}", "success", log_it=False)
        if self._scene_mode == "results":
            self._set_scene_mode("results")

    def _on_results_failed(self, message: str) -> None:
        log.error("Could not load the results: %s", message)
        self.show_message("Could not load the results; see the console", "error", log_it=False)

    def _apply_results_controls(self, data=None) -> None:
        """Push the strip's choices into the view and redraw."""
        fixed = self.range_combo.currentText() == "fixed"
        self.range_min.setVisible(fixed)
        self.range_max.setVisible(fixed)
        view = self.results_view
        if view is None:
            return
        state = dict(
            field_key=getattr(self, "_field_keys", {}).get(self.field_combo.currentText()),
            colormap=self.colormap_combo.currentText(),
            range_mode=self.range_combo.currentText(),
            fixed_range=(self.range_min.value(), self.range_max.value()) if fixed else None,
            display=self.display_combo.currentText(),
            u_ref=self._project.sim.inflow.speed,
            flow_direction=flow_direction(self._project.sim.inflow.alpha_deg),
            highlight_separation=self.separation_toggle.isChecked(),
            font_size=self._point_size,
        )
        if data is not None:
            view.data = None
            for key, value in state.items():
                setattr(view, key, value)
            view.set_data(data)
        else:
            view.configure(**state)
        if fixed is False and view.has_results:  # seed the fixed limits with the current range
            rng = view.field_range()
            if rng is not None:
                for spin, value in zip((self.range_min, self.range_max), rng):
                    spin.blockSignals(True)
                    spin.setValue(value)
                    spin.blockSignals(False)
        self.separation_toggle.setEnabled(view.can_show_separation)
        self.sections_button.setEnabled(view.has_results)
        if self.section_tool is not None and data is not None:
            self._feed_section_tool()
        frac = view.separated_fraction() if view.can_show_separation else None
        self.separation_toggle.setToolTip(
            "Highlight the wall faces where Cf_x < 0 (near-wall flow running upstream: separated or "
            "recirculating) in the error colour" + (f". Now: {100 * frac:.1f} % of the wall faces" if frac is not None
                                                     else ". Needs the wallShearStress field"))
        self._sync_section_controls()
        self._update_telemetry()
        if self.viewer is not None:
            self.viewer.render()

    # Results Scene camera (docs/QUESTIONS.md item 59): an ISO view from upstream and above, so the
    # windward side of an external-flow body faces the user. Direction from the target to the camera.
    UPSTREAM_ISO = (-1.0, -1.0, 1.0)
    UPSTREAM_VIEW = "Upstream ISO"

    def _view_from_upstream(self, bounds) -> None:
        """Camera on the -x, +z side (and -y, for an ISO look), aimed at the centre of ``bounds``,
        +z up, framing them (no render)."""
        centre = [(bounds[2 * i] + bounds[2 * i + 1]) / 2 for i in range(3)]
        size = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4], 1e-9)
        position = [c + 3.0 * size * d for c, d in zip(centre, self.UPSTREAM_ISO)]
        self.viewer.camera_position = [tuple(position), tuple(centre), (0.0, 0.0, 1.0)]
        self.viewer.reset_camera(render=False, bounds=bounds)
        self.current_view = self.UPSTREAM_VIEW
        self.top_bar.set_active_view(None)

    def _update_paraview_button(self) -> None:
        exe = paraview.executable()
        has = self.results_time() is not None
        self.paraview_button.setEnabled(exe is not None and has)
        self.paraview_button.setToolTip(
            paraview.NOT_FOUND_TIP if exe is None else f"Open the case in ParaView ({exe})")

    def open_in_paraview(self) -> None:
        """Write case.foam and launch the Windows ParaView on it, detached."""
        exe = paraview.executable()
        case_dir = case_dir_for(self._project)
        if exe is None or case_dir is None:
            self.show_message(paraview.NOT_FOUND_TIP, "warning")
            return
        try:
            paraview.launch(exe, case_dir)
        except (OSError, subprocess.SubprocessError) as exc:
            self.show_message(f"Could not start ParaView: {exc}", "error")
            return
        log.info("Opened %s in ParaView (%s)", case_dir / "case.foam", exe)

    def _feed_section_tool(self) -> None:
        view = self.results_view
        self.section_tool.set_results(view.data.patches, self._project.sim.inflow.speed, view.parts_bounds())

    def open_sections(self) -> None:
        """The Sections tool (D-062): Cp against x/c on wall sections of the shown results."""
        view = self.results_view
        if view is None or not view.has_results:
            self.show_message("No results to cut: run the solver first.", "warning")
            return
        if self.section_tool is None:
            self.section_tool = SectionTool(self)
            self.section_tool.export_requested.connect(self.export_sections)
        self.section_tool.configure(self._theme)
        self._feed_section_tool()
        self.section_tool.show()
        self.section_tool.raise_()

    def export_sections(self) -> None:
        tool = self.section_tool
        if tool is None or not tool.sections:
            return
        case_dir = case_dir_for(self._project)
        path = self.dialogs.ask_csv_path(case_dir.parent / "sections.csv" if case_dir is not None else None)
        if path is None:
            return
        try:
            rows = tool.write_csv(path)
        except OSError as exc:
            self.show_message(f"Could not write {path}: {exc}", "error")
            return
        self.show_message(f"Exported {rows} section points to {path}", "success")

    def edit_preferences(self) -> None:
        """Edit > Preferences: the ParaView executable (empty = detect)."""
        path = self.dialogs.ask_paraview_path(paraview.configured(), paraview.detect())
        if path is None:
            return
        paraview.set_configured(path.strip())
        self._update_paraview_button()
        log.info("ParaView executable: %s", path.strip() or "detect automatically")

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

    def _section_view(self):
        """The view the section controls drive: the mesh view, or the results view in that scene."""
        return self.results_view if self._scene_mode == "results" else self.mesh_view

    def _sync_section_controls(self) -> None:
        """Show the controls in the mesh scene (and in the results scene when a section is shown)
        and set the slider to the plane's offset."""
        view = self._section_view()
        if self._scene_mode == "results":
            visible = (view is not None and view.volume_bounds() is not None
                       and view.display in ("Section", "Both"))
        else:
            visible = self._scene_mode == "mesh" and view is not None and view.has_volume
        self.section_controls.setVisible(visible)
        self.section_toggle.setVisible(self._scene_mode == "mesh")
        self.boundary_toggle.setVisible(self._scene_mode == "mesh")
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
        if self._scene_mode == "results":
            self.results_view.set_section(axis=axis)
            self._sync_section_controls()
            self._update_telemetry()
            self.viewer.render()
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
        view = self._section_view()
        if view is None or view.volume_bounds() is None:
            return
        lo, hi = view.volume_bounds()[2 * view.section_axis: 2 * view.section_axis + 2]
        view.set_section(position=lo + value / SECTION_SLIDER_STEPS * (hi - lo))
        if view is self.results_view:
            self._update_telemetry()
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
        self._update_study_state()
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
        self.act_import = action("&Import Geometry...", self.import_surface, "Ctrl+I")
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
        self.act_repair_part = action("Re&pair part", self.repair_selected_part)

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
        edit_menu.addActions([self.act_add_part, self.act_remove_part, self.act_repair_part])
        edit_menu.addSeparator()
        self.act_preferences = action("&Preferences...", self.edit_preferences)
        edit_menu.addAction(self.act_preferences)
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
        self.act_repair_part.setEnabled(self._selected_part_file() is not None and not self.geometry_busy)
        self.act_import.setEnabled(not self.geometry_busy)

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

    def _selected_part_file(self) -> Path | None:
        index = self._selected_part_index()
        if index is None or self._project.path is None:
            return None
        parts = self._project.sim.geometry.parts
        if not 0 <= index < len(parts) or not parts[index].source_file:
            return None
        path = self._project.resolve_part_path(parts[index])
        return path if path.is_file() else None

    def repair_selected_part(self) -> None:
        """Edit > Repair part (Task 3.3, D-072): repair into a new file on the geometry worker, then
        point the part to it as one undoable step and show the before / after report (D-073)."""
        self._flush_edits()
        index = self._selected_part_index()
        if index is None or self._selected_part_file() is None:
            return
        snap = snapshot(self._project)
        part = snap.sim.geometry.parts[index]
        self._start_geometry_job(f"Repairing '{part.name}'", lambda: part_ops.repair_part(snap, index),
                                 lambda out: self._repair_done(index, part, out))

    def _repair_done(self, index: int, part: Part, out) -> None:
        fields, result = out
        name = part.name
        if fields and not self._apply_part_fields(index, part, fields, "repair"):
            return
        remaining = result.remaining
        summary = (f"Repaired '{name}' ({result.method})" if result.method != "none"
                   else f"'{name}' needs no repair")
        if remaining:
            summary += "; still: " + ", ".join(remaining)
        log.info("%s: %s -> %s", summary, result.before.summary(), result.after.summary())
        if result.fidelity is not None:
            log.info("Repair of '%s': %s", name, result.fidelity.text())
        for note in result.notes:
            log.info("Repair of '%s': %s", name, note)
        self.dialogs.show_repair_report(name, result.method, part_ops.repair_rows(result), result.notes)
        self.show_message(summary, "warning" if remaining else "success", log_it=False)

    def _apply_part_fields(self, index: int, before: Part, fields: dict, what: str) -> bool:
        """Apply a worker's Part fields as one undoable step if the part is unchanged since the job
        started (an undo meanwhile, for example); otherwise discard them with a message."""
        parts = self._project.sim.geometry.parts
        if not 0 <= index < len(parts) or parts[index] != before:
            self.show_message(f"Part '{before.name}' changed during the {what}: the result was discarded", "warning")
            return False
        self._run_edit(lambda: self._project.update_part(index, **fields))
        return True

    # -- background geometry jobs (D-073) ------------------------------------------------------

    def _start_geometry_job(self, label: str, function, on_done, on_error=None) -> bool:
        """Run ``function`` on the geometry worker; ``on_done(result)`` / ``on_error(exc)`` run on the
        GUI thread. The geometry actions are disabled meanwhile."""
        if self.geometry_worker.is_running():
            self.show_message(f"{self.geometry_worker.label} is still running", "warning")
            return False
        job = self.geometry_worker.start(label, function)
        self._geometry_jobs[job] = (label, on_done, on_error)
        log.info("%s...", label)
        self.show_message(f"{label}...", "info", log_it=False)
        self._set_geometry_busy(True)
        return True

    def _on_geometry_finished(self, job: int, result) -> None:
        label, on_done, _ = self._geometry_jobs.pop(job, ("", None, None))
        self._set_geometry_busy(False)
        if on_done is not None:
            on_done(result)

    def _on_geometry_failed(self, job: int, exc) -> None:
        label, _, on_error = self._geometry_jobs.pop(job, ("", None, None))
        self._set_geometry_busy(False)
        if on_error is not None:
            on_error(exc)
        else:
            self.show_message(f"{label} failed: {exc}", "error")

    def _set_geometry_busy(self, busy: bool) -> None:
        self.geometry_busy = busy
        self.properties.set_geometry_busy(busy)
        self._update_actions()
        self._update_mesh_button()

    def _retessellate(self, index: int, linear: float | None, angular: float | None) -> None:
        """A CAD part's deflection was edited: re-tessellate on the worker, apply as one undo step."""
        snap = snapshot(self._project)
        part = snap.sim.geometry.parts[index]

        def done(fields: dict) -> None:
            if self._apply_part_fields(index, part, fields, "tessellation"):
                log.info("Re-tessellated '%s' (%g m, %g deg)", part.name, fields["cad"]["linear_deflection"],
                         fields["cad"]["angular_deflection"])
                self.show_message(f"Re-tessellated '{part.name}'", "success", log_it=False)

        def failed(exc) -> None:
            self.show_message(f"Could not re-tessellate '{part.name}': {exc}", "error")
            self.properties.refresh()

        self._start_geometry_job(f"Tessellating '{part.name}'",
                                 lambda: part_ops.retessellate(snap, index, linear, angular), done, failed)

    def _on_intersections_checked(self, path: str, units: str) -> None:
        """A background self-intersection check finished: refresh the Checks rows and the highlight,
        and warn about a part imported in this session that has some."""
        name = self._announce_checks.pop((path, units), None)
        report = cached_report(Path(path), units)
        if name is not None and report is not None and report.self_intersections:
            log.warning("Part '%s': %d self-intersecting triangles (highlighted when the part is selected)",
                        name, report.self_intersections)
        self.properties.refresh()
        self._update_selection_views()

    def _request_checks(self, parts) -> None:
        """Queue the self-intersection check of newly imported parts (announced when done)."""
        for part in parts:
            path = (self._project.path.parent / part.source_file).resolve()
            self._announce_checks[(str(path), part.units)] = part.name
            self.intersections.request(path, part.units)

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
        """File > Import Geometry: copy a surface or CAD file into <project>/geometry/ and add Parts."""
        self._flush_edits()
        if self._project.path is None and not self.save_as():  # the copy needs a project folder
            return
        source = self.dialogs.ask_import_path()
        if source is None:
            return
        if source.suffix.lower() in CAD_EXTENSIONS:
            self._import_cad(source)
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
            report = basic_report(dest, units)  # self-intersections: background check (D-073)
        except (OSError, SurfaceLoadError) as exc:
            if dest is not None:
                dest.unlink(missing_ok=True)
            self.show_message(f"Could not import {source.name}: {exc}", "error")
            return
        taken = {p.name for p in self._project.sim.geometry.parts}
        name = self._unique_name(source.stem, taken)
        relative = Path(os.path.relpath(dest, project_dir)).as_posix()
        solids = stl_solid_names(dest) if dest.suffix.lower() == ".stl" else []
        parts = [Part(name=name, source_file=relative, units=units)]
        if len(solids) > 1:  # Task 3.1: regions (default) or one part per solid
            mode = self.dialogs.ask_solids_mode(source.name, solids)
            if mode is None:
                dest.unlink(missing_ok=True)
                return
            try:
                if mode == "parts":
                    parts = part_ops.parts_per_solid(project_dir, dest, units, solids, taken)
                else:
                    parts = [part_ops.part_with_solid_regions(project_dir, name, dest, units, solids)]
            except (OSError, SurfaceLoadError, ValueError) as exc:
                dest.unlink(missing_ok=True)
                self.show_message(f"Could not import {source.name}: {exc}", "error")
                return
            if mode == "parts":
                dest.unlink(missing_ok=True)
        previous = self._selection
        self._selection = ("part", len(taken))  # the observer refresh selects the new part
        try:
            if len(parts) == 1:
                self._project.add_part(parts[0])
            else:
                self._project.add_parts(parts, f"Import {source.name} ({len(parts)} parts)")
        except (ValueError, TypeError) as exc:
            self._selection = previous
            dest.unlink(missing_ok=True)
            self.show_message(f"Could not import {source.name}: {exc}", "error")
            return
        names = ", ".join(f"'{p.name}'" for p in parts)
        log.info("Imported %s as part%s %s (units: %s)", source.name, "s" if len(parts) > 1 else "", names, units)
        if len(parts) == 1 and parts[0].regions:
            log.info("Part '%s' has %d regions: %s", name, len(parts[0].regions),
                     ", ".join(r.name for r in parts[0].regions))
        log.info("Checks for '%s': %s", name, report.summary())
        if report.normals_inward:
            log.warning("Part '%s': normals point inward (closed surface with negative signed volume); "
                        "the file was not changed", name)
        self._request_checks(parts)
        self.show_message(f"Imported {source.name} as {names}", "success", log_it=False)

    def _import_cad(self, source: Path) -> None:
        """STEP / IGES (millimetres) or BREP (units asked): one Part, or one Part per body, with a
        region per named face group (Task 3.2, D-070). Reading and tessellation run on the geometry
        worker (D-073); the parts are added on the GUI thread as one undoable step."""
        units = None
        if source.suffix.lower() in BREP_EXTENSIONS:
            units = self.dialogs.ask_units()
            if units is None:
                return
        project_dir = self._project.path.parent
        folder = project_dir / "geometry"
        try:
            folder.mkdir(exist_ok=True)
            dest = self._unique_path(folder, source.name)
            shutil.copy2(source, dest)
        except OSError as exc:
            self.show_message(f"Could not import {source.name}: {exc}", "error")
            return

        def failed(exc) -> None:
            dest.unlink(missing_ok=True)
            self.show_message(f"Could not import {source.name}: {exc}", "error")

        def tessellate(model) -> None:
            mode = "regions"
            if len(model.bodies) > 1:
                mode = self.dialogs.ask_solids_mode(source.name, [b.name for b in model.bodies])
                if mode is None:
                    dest.unlink(missing_ok=True)
                    return
            taken = {p.name for p in self._project.sim.geometry.parts}
            self._start_geometry_job(
                f"Tessellating {source.name}",
                lambda: part_ops.cad_parts(project_dir, dest, units, mode, taken, model=model),
                lambda parts: self._add_cad_parts(source, model, parts), failed)

        self._start_geometry_job(f"Reading {source.name}", lambda: read_cad(dest), tessellate, failed)

    def _add_cad_parts(self, source: Path, model, parts: list[Part]) -> None:
        project_dir = self._project.path.parent
        taken = {p.name for p in self._project.sim.geometry.parts}
        previous = self._selection
        self._selection = ("part", len(taken))
        try:
            if len(parts) == 1:
                self._project.add_part(parts[0])
            else:
                self._project.add_parts(parts, f"Import {source.name} ({len(parts)} parts)")
        except (ValueError, TypeError) as exc:
            self._selection = previous
            self.show_message(f"Could not import {source.name}: {exc}", "error")
            return
        for part in parts:
            report = basic_report(project_dir / part.source_file, part.units)
            log.info("Imported %s as part '%s' (units: %s; %d bodies, %d faces; tessellation %g m, %g deg): %s",
                     source.name, part.name, part.units, len(part.cad.bodies or model.bodies),
                     sum(len(r.members) for r in part.regions) or len(model.faces),
                     part.cad.linear_deflection, part.cad.angular_deflection, report.summary())
            if part.regions:
                log.info("Part '%s' has %d regions: %s", part.name, len(part.regions),
                         ", ".join(r.name for r in part.regions))
        self._request_checks(parts)
        names = ", ".join(f"'{p.name}'" for p in parts)
        self.show_message(f"Imported {source.name} as {names}", "success", log_it=False)

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
        if self.solver_worker.is_running():
            self.solver_worker.request_stop()
        for worker in (self.study_worker, self.sweep_worker):
            if worker.is_running():
                worker.request_stop()
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
