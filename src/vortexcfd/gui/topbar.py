"""Top bar: brand, project file + state, view segmented control, wireframe, run buttons."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from vortexcfd.gui.icons import logo_pixmap
from vortexcfd.gui.theme import Metrics, Theme, metrics, set_text_role
from vortexcfd.gui.widgets import Badge, DotButton

# (label, plotter method, tooltip). Fit is momentary: it does not change the active view.
VIEW_BUTTONS = (
    ("ISO", "view_isometric", "Isometric view"),
    ("XY", "view_xy", "View the XY plane (top)"),
    ("XZ", "view_xz", "View the XZ plane (front)"),
    ("YZ", "view_yz", "View the YZ plane (right)"),
    ("Fit", "reset_camera", "Fit the model in the view"),
)
FIT_METHOD = "reset_camera"


PARAVIEW_TEXT = "Open in ParaView"
PARAVIEW_SHORT = "ParaView"
COMPACT_LEVELS = 5  # full, short badge texts, dot-only badges, short ParaView button, no brand text
MIN_NAME_U = 4  # the project name's narrowest (elided) width
NAME_TOOLTIP = "Select the simulation (edit its name in Properties)"


class TopBar(QWidget):
    name_clicked = Signal()
    view_requested = Signal(str)  # plotter method name
    wireframe_toggled = Signal(bool)
    mesh_clicked = Signal()
    run_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._logo = QLabel()
        self.brand = QLabel("VortexCFD")
        self.name_button = QPushButton("Untitled")
        self.name_button.setObjectName("nameBtn")
        self.name_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.name_button.setToolTip(NAME_TOOLTIP)
        self._name = "Untitled"
        self.name_button.clicked.connect(self.name_clicked)
        self.state_badge = Badge("Saved", with_dot=True)
        self.mesh_badge = Badge("Mesh out of date", with_dot=True)
        self.mesh_badge.set_state("warning")
        self.mesh_badge.hide()
        self._mesh_stale = False
        self._mesh_error: str | None = None
        self._mesh_warning: str | None = None
        self.results_badge = Badge(with_dot=True)
        self.results_badge.setText("Results out of date", "Results")
        self.results_badge.set_state("warning")
        self.results_badge.hide()
        self._pad = 0
        self._compact = 0

        row = QHBoxLayout(self)
        self._row = row
        row.addWidget(self._logo)
        row.addWidget(self.brand)
        row.addWidget(self._separator())
        row.addWidget(self.name_button)
        row.addWidget(self.state_badge)
        row.addWidget(self.mesh_badge)
        row.addWidget(self.results_badge)
        row.addWidget(self._separator())

        # One segmented control: elevated pill, 1px border, 1px separators between segments.
        self.segmented = QFrame()
        self.segmented.setObjectName("segmented")
        seg_row = QHBoxLayout(self.segmented)
        self._seg_row = seg_row
        self.view_buttons: dict[str, QPushButton] = {}
        for i, (text, method, tip) in enumerate(VIEW_BUTTONS):
            if i:
                sep = QFrame()
                sep.setObjectName("segSep")
                sep.setFrameShape(QFrame.Shape.NoFrame)
                seg_row.addWidget(sep)
            button = QPushButton(text)
            button.setObjectName("segBtn")
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCheckable(method != FIT_METHOD)
            button.clicked.connect(lambda _=False, name=method: self.view_requested.emit(name))
            self.view_buttons[method] = button
            seg_row.addWidget(button)
        row.addWidget(self.segmented)

        self.wireframe_button = DotButton("Wireframe")
        self.wireframe_button.setCheckable(True)
        self.wireframe_button.setToolTip("Toggle wireframe representation")
        self.wireframe_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.wireframe_button.toggled.connect(self.wireframe_toggled)
        row.addWidget(self.wireframe_button)
        self.paraview_button = QPushButton(PARAVIEW_TEXT)  # next to the scene controls (D-151)
        self.paraview_button.setObjectName("tbBtn")
        self.paraview_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row.addWidget(self.paraview_button)
        row.addStretch(1)
        self.mesh_button = self._future_button("Generate Mesh", "meshBtn", "Save the project first.")
        self.mesh_button.clicked.connect(self.mesh_clicked)
        self._run_state: str | None = None
        self._dirty = False
        self.run_button = self._future_button("Run Solver", "runBtn", "Save the project first.")
        self.run_button.clicked.connect(self.run_clicked)
        row.addWidget(self.mesh_button)
        row.addWidget(self.run_button)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_width()

    def compact_level(self) -> int:
        return self._compact

    def _fit_width(self) -> None:
        """The least compact form that fits the bar's width (D-155): the out-of-date badges with their short texts,
        then as dots only (their text in the tooltip), then "ParaView" for "Open in ParaView"."""
        self._fit_name()
        for level in range(COMPACT_LEVELS):
            self._apply_compact(level)
            excess = self._row.sizeHint().width() - self.width()
            if excess <= 0:
                return
        self._fit_name(max(MIN_NAME_U * metrics().u, self.name_button.minimumWidth() - excess))  # the name gives way last

    def _apply_compact(self, level: int) -> None:
        self._compact = level
        for badge in (self.mesh_badge, self.results_badge):
            badge.set_compact(min(level, 2))
        self.paraview_button.setText(PARAVIEW_SHORT if level >= 3 else PARAVIEW_TEXT)
        self.brand.setVisible(level < 4)  # the logo stays
        self._row.invalidate()

    def _separator(self) -> QFrame:
        sep = QFrame()
        sep.setObjectName("vsep")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        return sep

    def _future_button(self, text: str, name: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.setEnabled(False)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.ForbiddenCursor)
        return button

    def set_project(self, file_name: str, dirty: bool) -> None:
        self._name = file_name
        self.name_button.setText(file_name)
        self._fit_name()
        self._dirty = dirty
        self._update_badge()

    def set_mesh_stale(self, stale: bool) -> None:
        """Show the "Mesh out of date" badge (the saved mesh no longer matches the inputs)."""
        self._mesh_stale = stale
        self._update_mesh_badge()

    def set_mesh_warning(self, text: str | None) -> None:
        """A usable mesh with checkMesh quality warnings (D-100): the badge shows ``text`` in the warning
        colour unless an error or "Mesh out of date" takes precedence."""
        self._mesh_warning = text
        self._update_mesh_badge()

    def set_mesh_error(self, text: str | None) -> None:
        """An invalid mesh (e.g. a part was lost, D-052): the mesh badge shows ``text`` in the error
        colour; it takes precedence over "Mesh out of date"."""
        self._mesh_error = text
        self._update_mesh_badge()

    def _update_mesh_badge(self) -> None:
        error = self._mesh_error
        if error:
            self.mesh_badge.setText(error, "Mesh invalid")
            self.mesh_badge.set_state("error")
        elif self._mesh_stale or not self._mesh_warning:
            self.mesh_badge.setText("Mesh out of date", "Mesh")
            self.mesh_badge.set_state("warning")
        else:
            self.mesh_badge.setText(self._mesh_warning, "Mesh")
            self.mesh_badge.set_state("warning")
        self.mesh_badge.setHidden(not (error or self._mesh_stale or self._mesh_warning))
        self._fit_width()

    def set_results_stale(self, stale: bool) -> None:
        """Show the "Results out of date" badge (the saved results no longer match the inputs)."""
        self.results_badge.setHidden(not stale)
        self._fit_width()

    def set_solver_state(self, reason: str | None, running: bool, warning: str | None = None,
                         first_cell: str | None = None, compressibility: str | None = None,
                         continue_tip: str | None = None) -> None:
        """Run Solver: "Stop" while running, enabled when ``reason`` is None, else disabled with
        the reason as tooltip; ``warning`` (checkMesh quality warnings, D-100), ``first_cell`` (the y+
        drift of collapsed layers, D-109) and ``compressibility`` (a Mach number above 0.3, D-168) are warnings, not
        blocks, added to the tooltip of an enabled button."""
        button = self.run_button
        if running:
            button.setText("Stop")
            button.setEnabled(True)
            button.setToolTip("Stop the solver (writes the current iteration)")
        else:  # ``continue_tip``: the solution can be continued (D-171): "Continue Solver" and what it does
            button.setText("Continue Solver" if continue_tip is not None else "Run Solver")
            button.setEnabled(reason is None)
            button.setToolTip(reason if reason is not None else (continue_tip or "Run simpleFoam on the mesh")
                              + (f"\nThe mesh has warnings ({warning}); the solver can run." if warning else "")
                              + (f"\nWarning: {first_cell}" if first_cell else "")
                              + (f"\nWarning: {compressibility}" if compressibility else ""))
        button.setCursor(Qt.CursorShape.PointingHandCursor if running or reason is None
                         else Qt.CursorShape.ForbiddenCursor)

    def set_run_state(self, text: str | None) -> None:
        """Show a run state (e.g. "Meshing") in the badge instead of Saved/Modified."""
        self._run_state = text
        self._update_badge()

    def _update_badge(self) -> None:
        if self._run_state:
            self.state_badge.setText(self._run_state)
            self.state_badge.set_state("")
        else:
            self.state_badge.setText("Modified" if self._dirty else "Saved")
            self.state_badge.set_state("warning" if self._dirty else "success")

    def set_mesh_state(self, reason: str | None, running: bool, warning: str | None = None) -> None:
        """Generate Mesh: "Stop" while running, enabled when ``reason`` is None, else disabled
        with the reason as tooltip."""
        button = self.mesh_button
        if running:
            button.setText("Stop")
            button.setEnabled(True)
            button.setToolTip("Stop meshing")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            button.setText("Generate Mesh")
            button.setEnabled(reason is None)
            tip = "Generate the mesh with snappyHexMesh"
            if warning:
                tip += f"\nWarning: {warning}"
            button.setToolTip(tip if reason is None else reason)
            button.setCursor(
                Qt.CursorShape.PointingHandCursor if reason is None else Qt.CursorShape.ForbiddenCursor
            )

    def set_active_view(self, name: str | None) -> None:
        """Mark the segment called ``name`` active (None or "Custom": none is active)."""
        for text, method, _ in VIEW_BUTTONS:
            button = self.view_buttons[method]
            if button.isCheckable():
                button.setChecked(text == name)

    def active_view(self) -> str | None:
        for text, method, _ in VIEW_BUTTONS:
            if self.view_buttons[method].isChecked():
                return text
        return None

    def set_viewer_enabled(self, enabled: bool) -> None:
        for button in (*self.view_buttons.values(), self.wireframe_button):
            button.setEnabled(enabled)

    def configure(self, m: Metrics, t: Theme, dpr: float) -> None:
        self.setFixedHeight(m.top_bar)
        self._row.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
        self._row.setSpacing(m.s2)
        self._logo.setPixmap(logo_pixmap(t, m.logo, dpr))
        self._logo.setFixedSize(m.logo, m.logo)
        set_text_role(self.brand, "strong")
        set_text_role(self.name_button, "value")
        self.state_badge.configure(m, t)
        self.mesh_badge.configure(m, t)
        self.results_badge.configure(m, t)
        self.wireframe_button.configure(m, t)
        self._seg_row.setContentsMargins(m.line, m.line, m.line, m.line)
        self._seg_row.setSpacing(0)
        inner = m.button - 2 * m.line
        for button in self.view_buttons.values():
            set_text_role(button, "control")
            button.setFixedHeight(inner - 2 * m.line)
        self.segmented.setFixedHeight(m.button)
        set_text_role(self.wireframe_button, "control")
        self.wireframe_button.setFixedHeight(m.button)
        set_text_role(self.paraview_button, "control")
        self.paraview_button.setFixedHeight(m.button)
        for button in (self.mesh_button, self.run_button):
            set_text_role(button, "strong")
            button.setFixedHeight(m.button)
        self.name_button.setFixedHeight(m.button)
        for sep in self.findChildren(QFrame, "vsep"):
            sep.setFixedSize(m.line, m.button)
        for sep in self.segmented.findChildren(QFrame, "segSep"):
            sep.setFixedSize(m.line, inner - 2 * m.line)
        self._pad = 2 * m.s3
        self._fit_name()
        self._fit_width()

    def _fit_name(self, width: int | None = None) -> None:
        """The project name in full, or elided in the middle to ``width`` pixels (the full name then in the
        tooltip). An explicit width, so the name is never clipped by a stale size hint."""
        fm = self.name_button.fontMetrics()
        full = fm.horizontalAdvance(self._name)
        if width is None or width >= full + self._pad:
            text, width = self._name, full + self._pad
        else:
            text = fm.elidedText(self._name, Qt.TextElideMode.ElideMiddle, max(width - self._pad, 0))
        self.name_button.setText(text)
        self.name_button.setFixedWidth(width)
        self.name_button.setToolTip(NAME_TOOLTIP + (f"\n{self._name}" if text != self._name else ""))
