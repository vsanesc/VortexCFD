"""Small composite widgets of the main window (sidebar header, pills, cards)."""

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.gui.icons import make_glyph
from vortexcfd.gui.theme import Metrics, Theme


def _glyph(widget: QWidget, name: str, color: str, size: int):
    return make_glyph(name, QColor(color), size, widget.devicePixelRatioF())


class ProjectHeader(QWidget):
    """Logo, project name (+ modified dot), chevron menu and a collapse-sidebar button."""

    name_clicked = Signal()
    collapse_clicked = Signal()

    def __init__(self, menu_actions: list[QAction | None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebarHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._logo = QLabel()
        self.name_button = QPushButton()
        self.name_button.setObjectName("headerName")
        self.name_button.setFlat(True)
        self.name_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.name_button.clicked.connect(self.name_clicked)
        self.dirty_dot = QLabel("●")
        self.dirty_dot.setObjectName("dirtyDot")
        self.dirty_dot.hide()
        self.menu = QMenu(self)
        for act in menu_actions:
            if act is None:
                self.menu.addSeparator()
            else:
                self.menu.addAction(act)
        self.menu_button = QToolButton()
        self.menu_button.setMenu(self.menu)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_button.setToolTip("Project menu")
        self.collapse_button = QToolButton()
        self.collapse_button.setToolTip("Collapse sidebars (Ctrl+B)")
        self.collapse_button.clicked.connect(self.collapse_clicked)

        row = QHBoxLayout(self)
        row.addWidget(self._logo)
        row.addWidget(self.name_button)
        row.addWidget(self.dirty_dot)
        row.addWidget(self.menu_button)
        row.addStretch(1)
        row.addWidget(self.collapse_button)
        self._row = row
        self._pad = 0

    def set_name(self, name: str, dirty: bool) -> None:
        self.name_button.setText(name)
        self.dirty_dot.setHidden(not dirty)
        self._fit_name()

    def _fit_name(self) -> None:
        # Explicit minimum so the bold name is never clipped by a stale size hint.
        text_w = QFontMetrics(self.name_button.font()).horizontalAdvance(self.name_button.text())
        self.name_button.setMinimumWidth(text_w + 2 * self._pad)

    def configure(self, m: Metrics, t: Theme) -> None:
        self.setFixedHeight(m.sidebar_header)
        bold = QFont(QApplication.font())
        bold.setBold(True)
        self.name_button.setFont(bold)  # real bold font so the size hint fits the text
        self._pad = m.s3 + m.s1
        self._fit_name()
        self._row.setContentsMargins(m.s3, 0, m.s3, 0)
        self._row.setSpacing(m.s2)
        icon = QSize(m.u, m.u)
        self._logo.setPixmap(_glyph(self, "logo", t.accent, m.u).pixmap(icon))
        self.menu_button.setIcon(_glyph(self, "chevron_down", t.muted_text, m.u))
        self.menu_button.setIconSize(icon)
        self.collapse_button.setIcon(_glyph(self, "sidebar", t.muted_text, m.u))
        self.collapse_button.setIconSize(icon)


class SearchField(QLineEdit):
    """Search box with a drawn magnifier."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Search...")
        self._action = QAction(self)
        self.addAction(self._action, QLineEdit.ActionPosition.LeadingPosition)

    def configure(self, m: Metrics, t: Theme) -> None:
        self._action.setIcon(_glyph(self, "search", t.muted_text, m.u))


class _Pill(QFrame):
    """Rounded container for a row of buttons; radius is half its height."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pill")
        self._row = QHBoxLayout(self)
        self.buttons: list[QPushButton] = []

    def _add_button(self, text: str, name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._row.addWidget(button)
        self.buttons.append(button)
        return button

    def configure(self, m: Metrics) -> None:
        self.setFixedHeight(m.pill_h)
        self._row.setContentsMargins(m.s1, m.s1, m.s1, m.s1)
        self._row.setSpacing(m.s1)
        for button in self.buttons:
            button.setFixedHeight(m.pill_h - 2 * (m.s1 + m.line))


class StagePill(_Pill):
    """Exclusive segmented control: Geometry, Mesh, Physics, Solve, Results."""

    stage_clicked = Signal(str)  # section kind

    STAGES = (
        ("Geometry", "geometry"),
        ("Mesh", "mesh"),
        ("Physics", "physics"),
        ("Solve", "solvers"),
        ("Results", "reports"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._by_kind: dict[str, QPushButton] = {}
        for text, kind in self.STAGES:
            button = self._add_button(text, "segBtn")
            button.setCheckable(True)
            self._group.addButton(button)
            self._by_kind[kind] = button
            button.clicked.connect(lambda _=False, k=kind: self.stage_clicked.emit(k))
        self.set_stage("geometry")

    def stage(self) -> str:
        return next(k for k, b in self._by_kind.items() if b.isChecked())

    def set_stage(self, kind: str) -> None:
        self._by_kind[kind].setChecked(True)  # programmatic: does not emit stage_clicked


class ViewPill(_Pill):
    """Camera shortcuts: Fit, Iso, Front, Top, Right (pyvista plotter view methods)."""

    VIEWS = (
        ("Fit", "Fit the model in the view", "reset_camera"),
        ("Iso", "Isometric view", "view_isometric"),
        ("Front", "Front view (XZ plane)", "view_xz"),
        ("Top", "Top view (XY plane)", "view_xy"),
        ("Right", "Right view (YZ plane)", "view_yz"),
    )

    def __init__(self, get_plotter: Callable[[], object | None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._get_plotter = get_plotter
        for text, tip, method in self.VIEWS:
            button = self._add_button(text, "viewBtn")
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, name=method: self._call(name))

    def _call(self, method: str) -> None:
        plotter = self._get_plotter()
        if plotter is None:
            return
        getattr(plotter, method)()
        plotter.render()


def make_strip(pill: QWidget, object_name: str) -> QWidget:
    """A full-width strip with the pill centered."""
    strip = QWidget()
    strip.setObjectName(object_name)
    strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    row = QHBoxLayout(strip)
    row.setContentsMargins(0, 0, 0, 0)
    row.addStretch(1)
    row.addWidget(pill)
    row.addStretch(1)
    return strip


class _CardHeader(QFrame):
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class Card(QWidget):
    """Collapsible card: header row with a +/- toggle and a form body."""

    toggled = Signal(str, bool)  # title, collapsed

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self._collapsed = False
        self.header = _CardHeader()
        self.header.setObjectName("cardHeader")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.clicked.connect(self.toggle)
        self._title_label = QLabel(title)
        self._title_label.setObjectName("cardTitle")
        self._toggle = QLabel()
        self._toggle.setObjectName("cardToggle")
        header_row = QHBoxLayout(self.header)
        header_row.addWidget(self._title_label)
        header_row.addStretch(1)
        header_row.addWidget(self._toggle)
        self._header_row = header_row

        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.body)
        self._theme: Theme | None = None
        self._metrics: Metrics | None = None

    def add_row(self, label: str, field: QWidget) -> None:
        text = QLabel(label)
        text.setObjectName("muted")
        self.form.addRow(text, field)

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.body.setHidden(collapsed)
        self._update_toggle()

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)
        self.toggled.emit(self.title, self._collapsed)

    def configure(self, m: Metrics, t: Theme) -> None:
        self._theme, self._metrics = t, m
        self.header.setFixedHeight(m.header)
        self._header_row.setContentsMargins(m.s3, 0, m.s3, 0)
        self.form.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
        self.form.setHorizontalSpacing(m.s3)
        self.form.setVerticalSpacing(m.s2)
        self._update_toggle()

    def _update_toggle(self) -> None:
        if self._theme is None or self._metrics is None:
            return
        name = "plus" if self._collapsed else "minus"
        size = self._metrics.u
        self._toggle.setPixmap(
            _glyph(self, name, self._theme.muted_text, size).pixmap(QSize(size, size))
        )
