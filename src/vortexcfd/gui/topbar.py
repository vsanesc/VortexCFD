"""Top bar: brand, project file + state, view buttons, wireframe toggle, run buttons."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from vortexcfd.gui.theme import Metrics, Theme, mono_font
from vortexcfd.gui.widgets import Badge, glyph_pixmap

# (label, plotter method) for the camera buttons; Fit is the plotter's reset_camera.
VIEW_BUTTONS = (
    ("ISO", "view_isometric", "Isometric view"),
    ("XY", "view_xy", "View the XY plane (top)"),
    ("XZ", "view_xz", "View the XZ plane (front)"),
    ("YZ", "view_yz", "View the YZ plane (right)"),
    ("Fit", "reset_camera", "Fit the model in the view"),
)
DISABLED_OPACITY = 0.55


class TopBar(QWidget):
    name_clicked = Signal()
    view_requested = Signal(str)  # plotter method name
    wireframe_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._logo = QLabel()
        self.brand = QLabel("VortexCFD")
        self.name_button = QPushButton("Untitled")
        self.name_button.setObjectName("nameBtn")
        self.name_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.name_button.setToolTip("Select the simulation (edit its name in Properties)")
        self.name_button.clicked.connect(self.name_clicked)
        self.dirty_dot = QLabel("●")
        self.dirty_dot.setObjectName("dirtyDot")
        self.dirty_dot.hide()
        self.state_badge = Badge("Saved")

        self._pad = 0
        self.view_buttons: dict[str, QPushButton] = {}
        row = QHBoxLayout(self)
        self._row = row
        row.addWidget(self._logo)
        row.addWidget(self.brand)
        row.addWidget(self._separator())
        row.addWidget(self.name_button)
        row.addWidget(self.dirty_dot)
        row.addWidget(self.state_badge)
        row.addWidget(self._separator())
        for text, method, tip in VIEW_BUTTONS:
            button = QPushButton(text)
            button.setObjectName("tbBtn")
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _=False, name=method: self.view_requested.emit(name))
            self.view_buttons[method] = button
            row.addWidget(button)
        self.wireframe_button = QPushButton("Wireframe")
        self.wireframe_button.setObjectName("tbBtn")
        self.wireframe_button.setCheckable(True)
        self.wireframe_button.setToolTip("Toggle wireframe representation")
        self.wireframe_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.wireframe_button.toggled.connect(self.wireframe_toggled)
        row.addWidget(self.wireframe_button)
        row.addStretch(1)
        self.mesh_button = self._future_button("Generate Mesh", "meshBtn", "Available in Phase 5")
        self.run_button = self._future_button("Run Solver", "runBtn", "Available in Phase 4")
        row.addWidget(self.mesh_button)
        row.addWidget(self.run_button)

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
        effect = QGraphicsOpacityEffect(button)
        effect.setOpacity(DISABLED_OPACITY)
        button.setGraphicsEffect(effect)
        return button

    def set_project(self, file_name: str, dirty: bool) -> None:
        self.name_button.setText(file_name)
        self._fit_name()
        self.dirty_dot.setHidden(not dirty)
        self.state_badge.setText("Modified" if dirty else "Saved")
        self.state_badge.set_state("warning" if dirty else "success")

    def set_viewer_enabled(self, enabled: bool) -> None:
        for button in (*self.view_buttons.values(), self.wireframe_button):
            button.setEnabled(enabled)

    def configure(self, m: Metrics, t: Theme) -> None:
        self.setFixedHeight(m.top_bar)
        self._row.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
        self._row.setSpacing(m.s2)
        self._logo.setPixmap(glyph_pixmap(self, "logo", t.accent_secondary, m.u))
        brand = QApplication.font()
        brand.setBold(True)
        self.brand.setFont(brand)
        self.name_button.setFont(mono_font(QApplication.font(), 0.9))
        self.state_badge.configure()
        small = mono_font(QApplication.font(), 0.85)
        for button in (*self.view_buttons.values(), self.wireframe_button):
            button.setFont(small)
            button.setFixedHeight(m.button)
        bold = QApplication.font()
        bold.setBold(True)
        for button in (self.mesh_button, self.run_button):
            button.setFont(bold)
            button.setFixedHeight(m.button)
        self.name_button.setFixedHeight(m.button)
        for sep in self.findChildren(QFrame, "vsep"):
            sep.setFixedSize(m.line, m.button)
        self._pad = 2 * m.s3
        self._fit_name()

    def _fit_name(self) -> None:
        # Explicit minimum so the name is never clipped by a stale size hint.
        width = self.name_button.fontMetrics().horizontalAdvance(self.name_button.text())
        self.name_button.setMinimumWidth(width + self._pad)


