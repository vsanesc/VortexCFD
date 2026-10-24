"""Design tokens and application of the look (Fusion style + palette + stylesheet).

Every color lives in a ``Theme`` token and every size derives from the font height
(``Metrics``): change a value here and nothing else. The "Zinc & Teal" values marked as owner
values are fixed by the owner (D-144) and change only on his request.
"""

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QWidget

from vortexcfd.gui.settings_store import settings


# View > Interface size (D-148): the application font's point size; every size derives from it (Metrics). The
# zoom actions still step the point size between MIN and MAX.
INTERFACE_SIZES = {"Small": 9, "Medium": 10, "Large": 12}
DEFAULT_POINT_SIZE = INTERFACE_SIZES["Small"]  # owner decision: compact by default
MIN_POINT_SIZE = 8
MAX_POINT_SIZE = 24

# Application font family stack: the first installed family wins.
FONT_FAMILIES: tuple[str, ...] = ("Inter", "Segoe UI", "Noto Sans", "DejaVu Sans")
# Monospace stack for numbers, badges, the console and viewport text.
MONO_FAMILIES: tuple[str, ...] = ("JetBrains Mono", "Cascadia Mono", "DejaVu Sans Mono")


def blend(fg: str, bg: str, alpha: float) -> str:
    """Hex color of ``fg`` at ``alpha`` opacity over ``bg``."""
    a, b = QColor(fg), QColor(bg)
    mix = [round(x * alpha + y * (1 - alpha)) for x, y in ((a.red(), b.red()), (a.green(), b.green()), (a.blue(), b.blue()))]
    return QColor(*mix).name().upper()


@dataclass(frozen=True)
class Theme:
    """Named colors (hex strings)."""

    name: str
    canvas: str  # the background: viewer background, the gaps between panels
    base: str  # panels: window chrome, tree, properties, monitors, console, status line, dialogs
    elevated: str  # inputs (inset, darker than the panel), section headers, tree row hover
    floating: str  # menus, popups, tooltips (lighter than the panel)
    border: str
    border_active: str
    text: str
    muted_text: str
    disabled_text: str  # disabled controls and input placeholders ONLY
    accent: str  # teal: selection, primary actions (Generate Mesh, Run Solver), focus, active tabs
    accent_hover: str
    accent_dim: str  # accent at 15% over base
    accent_text: str  # text on accent (dark)
    accent_secondary: str  # amber: highlights and warnings, never selection
    accent_secondary_hover: str
    accent_secondary_dim: str  # accent_secondary at 15% over base
    selection: str  # selected tree row: accent_dim over base
    part_surface: str  # imported part faces in the viewer
    part_edge: str  # imported part edges
    part_selected: str  # selected part (= accent)
    mesh_edge: str  # cell edges of the mesh section (= disabled_text)
    mesh_surface: str  # cell faces of the mesh section (= elevated)
    success: str
    warning: str
    error: str
    axis_x: str
    axis_y: str
    axis_z: str


DIM_ALPHA = 0.15  # accent_dim / accent_secondary_dim: the accent at this alpha over base
_CANVAS = "#18181B"  # owner: background
_BASE = "#27272A"  # owner: panel
_ACCENT = "#2DD4BF"  # owner: accent (teal)
_ACCENT_SECONDARY = "#F59E0B"  # owner: secondary (amber)

# Zinc & Teal, the owner's palette (D-144; replaces Tungsten & Amber). The owner fixed the background, panel,
# accent, secondary and primary text; the other values are zinc steps and the accents' lighter steps chosen for
# WCAG AA on the background and the panel (tests/test_theme.py).
DARK = Theme(
    name="dark",
    canvas=_CANVAS,
    base=_BASE,
    elevated="#1C1C20",
    floating="#303036",
    border="#3F3F46",
    border_active="#52525B",
    text="#FAFAFA",
    muted_text="#A1A1AA",
    disabled_text="#71717A",
    accent=_ACCENT,
    accent_hover="#5EEAD4",
    accent_dim=blend(_ACCENT, _BASE, DIM_ALPHA),
    accent_text=_CANVAS,
    accent_secondary=_ACCENT_SECONDARY,
    accent_secondary_hover="#FBBF24",
    accent_secondary_dim=blend(_ACCENT_SECONDARY, _BASE, DIM_ALPHA),
    selection=blend(_ACCENT, _BASE, DIM_ALPHA),
    part_surface="#9F9FA9",
    part_edge="#3F3F46",
    part_selected=_ACCENT,
    mesh_edge="#71717A",
    mesh_surface="#1C1C20",
    success="#22C55E",
    warning=_ACCENT_SECONDARY,
    error="#FB7185",
    axis_x="#FF4D4D",
    axis_y="#2ECC71",
    axis_z="#38BDF8",
)

THEMES: dict[str, Theme] = {DARK.name: DARK}


@dataclass(frozen=True)
class LayoutFractions:
    """Region proportions measured on the owner's local design mockup (1833 x 1210, D-041)."""

    top_bar: float = 0.040  # top bar height / window height (48 px)
    left: float = 0.181  # left column width / window width (331 px)
    tree_split: float = 0.40  # tree section height / left column height (owner: 40 % tree, 60 % properties)
    tab_bar: float = 0.0265  # scene tab bar height / window height (32 px)
    monitors: float = 0.25  # monitors column width / window width (mockup: 0.347; narrower so the viewer keeps >= 50 % next to the 18u sidebar)
    console: float = 0.131  # bottom console height / window height (158 px)


LAYOUT = LayoutFractions()

# Region limits in units of u (font height): (minimum, maximum or None).
LEFT_INITIAL_U = 18  # default width of the left column, in u

LIMITS_U: dict[str, tuple[int, int | None]] = {
    "left": (14, 28),
    "monitors": (16, 40),
    "center": (20, None),
    "console": (4, None),
    "tree": (8, None),
    "properties": (6, None),
}
# The main window's minimum size (width, height) in u: the regions' minimum widths side by side, and the left column
# (menu, top bar, tree, properties, status bar) at its minimum heights.
MIN_WINDOW_U = (66, 36)


# Derived-color alphas and drawing constants (the only place for these numbers).
DISABLED_ALPHA = 0.5  # muted text/borders of disabled actions, blended over `base`
WINDOW_ICON_SIZES = (16, 24, 32, 48, 64, 128)  # px
TELEMETRY_OPACITY = 0.92  # telemetry card background opacity
TELEMETRY_OFFSET_U = 1  # card offset from the viewport's top-left corner, in u
TELEMETRY_FONT_U = 0.85  # card body font size in px per u (VTK Courier)
TELEMETRY_LINE_SPACING = 1.35  # VTK line spacing of the card text
TELEMETRY_TITLE_SCALE = 0.8  # card title size relative to the body
TELEMETRY_GAP_CHARS = 2  # characters between the label and value columns
BOUNDARY_FACE_OPACITY = 0.25  # translucent domain boundary patches in the mesh scene
SECTION_PREVIEW_MS = 150  # while dragging the section slider, re-slice at most this often
SECTION_SLIDER_STEPS = 1000  # resolution of the section offset slider
SECTION_EPS_FRACTION = 0.002  # nudge of a section plane off a boundary face (fraction of the extent)
DOMAIN_OPACITY = 0.6  # translucent domain wireframe
HIGHLIGHT_OPACITY = 0.35  # highlighted boundary face
PICK_MOVE_TOLERANCE_PX = 4  # a press/release closer than this is a click, not a camera drag
GRID_HALF_LINES = 10  # ground grid: lines on each side of the origin
GRID_SPACING = 1.0  # ground grid spacing (scene units)
GRID_MAJOR_EVERY = 5  # every Nth grid line is brighter
EMPTY_SCENE_POINT_FRACTION = 1.0  # "No geometry yet" size in px per u

# Residual chart palette (D-049), derived only from owner tokens: each token blended over `canvas`
# at the largest weight that brings it inside the dark lightness band of the dataviz validator
# (OKLCH L <= 0.66). Three hues; the fields of one family differ by line style (legend + dashes).
# field -> (token, weight over canvas, Qt pen style name)
RESIDUAL_STYLES = {
    "p": ("accent_secondary", 0.78, "SolidLine"),  # amber: the teal accent is too close to k's green (D-144)
    "Ux": ("axis_z", 0.80, "SolidLine"),
    "Uy": ("axis_z", 0.80, "DashLine"),
    "Uz": ("axis_z", 0.80, "DotLine"),
    "k": ("axis_y", 0.82, "SolidLine"),
    "omega": ("axis_y", 0.82, "DashLine"),
}
RESIDUAL_FALLBACK = ("muted_text", 1.0, "DashDotLine")  # any other field (not plotted by simpleFoam here)


def residual_style(t: "Theme", field: str) -> tuple[str, str]:
    """(hex colour, pen style name) of a residual series."""
    token, weight, style = RESIDUAL_STYLES.get(field, RESIDUAL_FALLBACK)
    return blend(getattr(t, token), t.canvas, weight), style


@dataclass(frozen=True)
class Metrics:
    """Sizes in px derived from the font height ``u``."""

    u: int
    s1: int
    s2: int
    s3: int
    s4: int
    s5: int
    s6: int
    header: int  # section header height (2u)
    row: int  # tree row height (1.6u; compact, D-148)
    field: int  # input height (1.6u; compact, D-148)
    radius_s: int  # 0.25u
    radius_m: int  # 0.5u
    menubar: int  # menu bar height (2u)
    status: int  # status line height (2u)
    top_bar: int  # top bar height (2.4u; the measured 1.9u is too tight for its buttons)
    tab_bar: int  # scene tab bar height (1.6u)
    button: int  # top bar button height (1.7u)
    dot: int  # status/toggle dot diameter (0.4u)
    logo: int  # logo placeholder side (1.6u)
    hit: int  # splitter hit area (0.5u)
    line: int = 1  # divider / border width
    bar: int = 2  # accent bar on the selected row


def metrics(u: int | None = None) -> Metrics:
    """Metrics for the current application font (or an explicit font height ``u``)."""
    if u is None:
        u = QFontMetrics(QApplication.font()).height()

    def k(f: float) -> int:
        return max(1, round(u * f))

    return Metrics(
        u=u, s1=k(0.25), s2=k(0.5), s3=k(0.75), s4=k(1), s5=k(1.5), s6=k(2),
        header=k(2), row=k(1.6), field=k(1.6), radius_s=k(0.25), radius_m=k(0.5),
        menubar=k(2), status=k(2), top_bar=k(2.4), tab_bar=k(1.6), button=k(1.7), dot=k(0.4), logo=k(1.6),
        hit=k(0.5),
    )


def clamp_point_size(size: int) -> int:
    return max(MIN_POINT_SIZE, min(MAX_POINT_SIZE, int(size)))


@dataclass(frozen=True)
class TextRole:
    """A text style: ``scale`` x the interface point size, the weight, monospace or not, letter spacing (px)."""

    scale: float
    weight: int = 400
    mono: bool = False
    spacing: float = 0.0


# The only text sizes of the GUI (D-153): every widget and painter takes its font from a role, sized relative to the
# interface size (View > Interface size). tests/test_typography.py fails on any other font size outside this module.
TEXT_ROLES: dict[str, TextRole] = {
    "display": TextRole(2.4, 600),  # the start screen's title
    "page_title": TextRole(1.3, 600),  # a dialog page's title
    "tile_title": TextRole(1.3, 700),  # a start tile's title
    "section_title": TextRole(0.85, 700, spacing=0.5),  # an upper-case panel section header
    "subsection_title": TextRole(0.77, 700, spacing=0.5),  # a collapsible group inside a panel
    "label": TextRole(1.0),  # a field's label
    "body": TextRole(1.0),  # running text, the tree, messages
    "strong": TextRole(1.0, 700),  # the brand, the primary top-bar actions
    "caption": TextRole(0.85),  # a note under a field, a chart's note
    "list_title": TextRole(1.0, 700),  # a list item's first line
    "list_subtitle": TextRole(1.0),  # a list item's second line (folder, date)
    "value": TextRole(0.9, mono=True),  # numbers and names in fields and value labels
    "control": TextRole(0.85, mono=True),  # compact controls: segmented buttons, the console, the search box
    "badge": TextRole(0.8, mono=True),  # status badges
    "data": TextRole(0.8, mono=True),  # report rows, chart axes
    "data_small": TextRole(0.75, mono=True),  # monitor tables, KPI captions, histogram labels
    "metric": TextRole(1.5, 700, mono=True),  # a KPI's big value
    "code": TextRole(1.0, mono=True),  # OpenFOAM file text
}


def role_point_size(role: str, base_point_size: float | None = None) -> float:
    """The role's point size at the interface size ``base_point_size`` (default: the application font's)."""
    if base_point_size is None:
        base_point_size = QApplication.font().pointSizeF()
    return base_point_size * TEXT_ROLES[role].scale


def role_font(role: str, base: QFont | None = None) -> QFont:
    """The font of the text role ``role`` (TEXT_ROLES), built on ``base`` (default: the application font)."""
    spec = TEXT_ROLES[role]
    font = QFont(QApplication.font() if base is None else base)
    if spec.mono:
        font.setFamilies(list(MONO_FAMILIES))
        font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(font.pointSizeF() * spec.scale)
    font.setWeight(QFont.Weight(spec.weight))
    if spec.spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spec.spacing)
    return font


def set_text_role(widget: QWidget, role: str) -> None:
    """Give ``widget`` the role's font and remember the role, so refresh_text_roles re-applies it."""
    widget.setProperty("textRole", role)
    widget.setFont(role_font(role))


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property change. Qt's re-polish puts back the font the widget had when
    it was first polished, so the widget's text role is applied again afterwards."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    role = widget.property("textRole")
    if isinstance(role, str) and role in TEXT_ROLES:
        widget.setFont(role_font(role))


def refresh_text_roles(root: QWidget) -> None:
    """After an interface size change: every widget under ``root`` given a role takes the role's new font, and every
    spin box's line edit its spin box's font (Qt does not pass a spin box's font change on to it)."""
    for widget in [root, *root.findChildren(QWidget)]:
        role = widget.property("textRole")
        if isinstance(role, str) and role in TEXT_ROLES:
            widget.setFont(role_font(role))
    for spin in root.findChildren(QAbstractSpinBox):
        edit = spin.findChild(QLineEdit)
        if edit is not None:
            edit.setFont(spin.font())


def glyph_font(pixel_size: int) -> QFont:
    """The logo letter's font: bold monospace sized to a pixmap (not text, so not a role)."""
    font = QFont()
    font.setFamilies(list(MONO_FAMILIES))
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setBold(True)
    font.setPixelSize(max(1, pixel_size))
    return font


def _qss_font(role: str, base_point_size: float) -> str:
    spec = TEXT_ROLES[role]
    return f"font-size: {base_point_size * spec.scale:.1f}pt; font-weight: {spec.weight};"


def build_palette(t: Theme) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.base,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.base,
        QPalette.ColorRole.AlternateBase: t.elevated,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.elevated,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.accent_text,
        QPalette.ColorRole.ToolTipBase: t.floating,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.disabled_text,
        QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.Mid: t.border,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.disabled_text))
    return p


def build_stylesheet(t: Theme, m: Metrics, base_point_size: float) -> str:
    """Stylesheet for what the palette cannot express."""
    ln = m.line
    inner = m.field - 2 * ln
    status_font = _qss_font("caption", base_point_size)
    btr = m.radius_s
    dis_text = t.disabled_text
    dis_border = blend(t.border_active, t.base, DISABLED_ALPHA)
    return f"""
QToolTip {{ background: {t.floating}; color: {t.text}; border: {ln}px solid {t.border};
    border-radius: {m.radius_s}px; padding: {m.s2}px {m.s3}px; }}
QWidget#panel {{ background: {t.base}; }}
QWidget#canvas {{ background: {t.canvas}; }}
QLabel#muted {{ color: {t.muted_text}; }}
QLabel#accent2 {{ color: {t.accent}; background: transparent; }}
QLabel#sectionTitle {{ color: {t.text}; background: transparent; }}
QScrollArea#propScroll {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: {t.base}; width: {m.s3}px; margin: 0; border: none; }}
QScrollBar::handle:vertical {{ background: {t.border_active}; border-radius: {m.s1}px;
    min-height: {m.s6}px; margin: {m.line}px; }}
QScrollBar::handle:vertical:hover {{ background: {t.muted_text}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QSlider::groove:horizontal {{ height: {m.s1}px; background: {t.border}; border-radius: {m.s1 // 2}px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: {m.s1 // 2}px; }}
QSlider::handle:horizontal {{ background: {t.accent}; width: {m.s4}px; margin: -{m.s1}px 0;
    border-radius: {m.s2}px; }}
QSlider::handle:horizontal:hover {{ background: {t.accent_hover}; }}
QLabel#subSection {{ color: {t.muted_text}; background: transparent; }}
QWidget#sectionHeader2 {{ background: {t.base}; border-top: {ln}px solid {t.border}; }}
QWidget#sectionHeader2:hover {{ background: {t.elevated}; }}
QToolButton#chevronBtn {{ color: {t.muted_text}; background: transparent; border: none; padding: 0; }}
QToolButton#chevronBtn:hover {{ color: {t.accent}; }}
QToolButton#helpBtn {{ color: {t.muted_text}; background: transparent; border: {ln}px solid {t.border};
    border-radius: {m.radius_m}px; padding: 0 {m.s1}px; font-weight: 600; }}
QToolButton#helpBtn:hover {{ color: {t.accent}; border-color: {t.accent}; }}
QCheckBox {{ spacing: {m.s1}px; }}
QPushButton#unitBtn {{ background: {t.elevated}; color: {t.accent}; border: {ln}px solid {t.border};
    border-radius: {btr}px; padding: 0 {m.s2}px; font-weight: 600; }}
QPushButton#unitBtn:hover {{ border-color: {t.accent}; }}
QLabel#unitLabel {{ color: {t.muted_text}; background: transparent; }}
QWidget#sectionHeader {{ background: {t.base}; border-bottom: {ln}px solid {t.border}; }}
QLabel#badge {{ background: {t.elevated}; color: {t.accent}; border: {ln}px solid {t.border};
    border-radius: {btr}px; padding: {m.s1}px {m.s2}px; }}
QLabel#badge[state="success"] {{ color: {t.success}; }}
QLabel#badge[state="warning"] {{ color: {t.warning}; }}
QLabel#badge[state="error"] {{ color: {t.error}; }}
QLabel#dirtyDot {{ color: {t.accent_secondary}; background: transparent; }}
QWidget#topBar {{ background: {t.base}; border-bottom: {ln}px solid {t.border}; }}
QFrame#vsep {{ background: {t.border}; border: none; }}
QPushButton#tbBtn, QPushButton#dotBtn {{ background: transparent; color: {t.muted_text};
    border: {ln}px solid transparent; border-radius: {btr}px; padding: 0 {m.s3}px; }}
QPushButton#tbBtn:checked {{ color: {t.accent}; border-color: {t.accent};
    background: {t.accent_dim}; }}
QPushButton#dotBtn {{ padding-left: {2 * m.s3 + m.dot}px; }}
QPushButton#tbBtn:hover, QPushButton#dotBtn:hover {{ color: {t.text}; background: {t.elevated}; }}
QPushButton#dotBtn:checked {{ color: {t.text}; border-color: {t.accent}; background: {t.accent_dim}; }}
QPushButton#dotBtn:checked:hover {{ border-color: {t.accent_hover}; }}
QFrame#segmented {{ background: {t.elevated}; border: {ln}px solid {t.border}; border-radius: {btr}px; }}
QFrame#segSep {{ background: {t.border}; border: none; }}
QPushButton#segBtn {{ background: transparent; color: {t.muted_text}; border: {ln}px solid transparent;
    border-radius: {btr}px; padding: 0 {m.s3}px; }}
QPushButton#segBtn:hover {{ color: {t.text}; }}
QPushButton#segBtn:checked {{ background: {t.accent_dim}; color: {t.accent}; border-color: {t.accent}; }}
QPushButton#segBtn:checked:hover {{ border-color: {t.accent_hover}; }}
QLabel#badge[dot="true"] {{ padding-left: {2 * m.s2 + m.dot}px; }}
QPushButton#nameBtn {{ background: transparent; color: {t.text}; border: none; text-align: left;
    padding: 0 {m.s2}px; border-radius: {btr}px; }}
QPushButton#nameBtn:hover {{ background: {t.elevated}; }}
QPushButton#meshBtn {{ background: {t.accent}; color: {t.accent_text}; border: {ln}px solid {t.accent};
    border-radius: {btr}px; padding: 0 {m.s4}px; font-weight: 600; }}
QPushButton#runBtn {{ background: {t.accent}; color: {t.accent_text}; border: {ln}px solid {t.accent};
    border-radius: {btr}px; padding: 0 {m.s4}px; font-weight: 600; }}
QPushButton#meshBtn:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton#runBtn:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton#meshBtn:disabled {{ background: {t.elevated}; color: {dis_text}; border-color: {t.border}; }}
QPushButton#runBtn:disabled {{ background: {t.elevated}; color: {dis_text}; border-color: {t.border}; }}
QToolButton#chevronBtn:disabled {{ background: transparent; }}
QToolButton {{ background: transparent; border: none; border-radius: {btr}px; padding: {m.s1}px; }}
QLabel#kpiSub {{ color: {t.muted_text}; background: transparent; }}
QPushButton#flatBtn {{ background: transparent; color: {t.muted_text}; border: none;
    border-radius: {btr}px; padding: {m.s1}px {m.s3}px; }}
QPushButton#flatBtn:hover {{ color: {t.text}; background: {t.elevated}; }}
QWidget#tabBar {{ background: {t.base}; border-bottom: {ln}px solid {t.border}; }}
QLabel#sceneTab {{ color: {t.text}; background: {t.elevated}; border: none;
    border-bottom: {m.bar}px solid {t.accent}; padding: 0 {m.s4}px; }}
QPushButton#sceneTabBtn {{ color: {t.muted_text}; background: transparent; border: none;
    border-bottom: {m.bar}px solid transparent; padding: 0 {m.s4}px; border-radius: 0; }}
QPushButton#sceneTabBtn:hover {{ color: {t.text}; }}
QPushButton#sceneTabBtn:checked {{ color: {t.accent}; background: {t.accent_dim};
    border-bottom-color: {t.accent}; }}
QWidget#consoleBar {{ background: {t.base}; border-bottom: {ln}px solid {t.border}; }}
QLabel#consoleTab {{ color: {t.text}; background: transparent; border: none;
    border-bottom: {m.bar}px solid {t.accent}; padding: 0 {m.s3}px; }}
QPlainTextEdit#console {{ background: {t.base}; color: {t.text}; border: none; padding: {m.s2}px; }}
QWidget#kpiRow {{ background: {t.base}; border-top: {ln}px solid {t.border}; }}
QWidget#kpiCell {{ background: {t.base}; border-right: {ln}px solid {t.border}; }}
QWidget#kpiCell[last="true"] {{ border-right: none; }}
QLabel#kpiTitle {{ color: {t.muted_text}; background: transparent; }}
QLabel#checkValue {{ color: {t.text}; background: transparent; }}
QLabel#checkValue[warn="true"] {{ color: {t.warning}; }}
QLabel#checkValue[error="true"] {{ color: {t.error}; }}
QLabel#checkValue[ok="true"] {{ color: {t.success}; }}
QWidget#convergenceBox {{ background: {t.base}; border-top: {ln}px solid {t.border}; }}
QLabel#statusWarn {{ color: {t.warning}; }}
QLabel#statusOk {{ color: {t.success}; }}
QLabel#kpiValue {{ color: {t.text}; background: transparent; }}
QWidget#propRow {{ background: transparent; border-bottom: {ln}px solid {t.border}; }}
QTreeView {{ background: {t.base}; border: none; outline: 0; }}
QTreeView::item {{ background: transparent; }}
QLineEdit, QComboBox, QAbstractSpinBox {{
    background: {t.elevated}; color: {t.text}; border: {ln}px solid {t.border};
    border-radius: {m.radius_s}px; padding: 0 {m.s2}px; min-height: {inner}px;
    selection-background-color: {t.accent}; selection-color: {t.accent_text};
}}
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover {{ border-color: {t.border_active}; }}
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{ border-color: {t.accent}; }}
QLineEdit[invalid="true"], QAbstractSpinBox[invalid="true"], QComboBox[invalid="true"] {{
    border: {2 * ln}px solid {t.error}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; height: 0; border: none; }}
QAbstractSpinBox QLineEdit {{ background: transparent; border: none; padding: 0; min-height: 0;
    border-radius: 0; }}
QLineEdit[readOnly="true"], QLineEdit[readOnly="true"]:hover {{
    background: {t.base}; color: {t.muted_text}; border-color: transparent;
}}
QComboBox::drop-down {{ border: none; width: {m.s5}px; }}
QComboBox QAbstractItemView {{
    background: {t.floating}; color: {t.text}; border: {ln}px solid {t.border};
    selection-background-color: {t.elevated}; selection-color: {t.text}; outline: 0;
}}
QStatusBar {{ background: {t.base}; color: {t.muted_text}; border-top: {ln}px solid {t.border};
    {status_font} }}
QStatusBar::item {{ border: none; }}
QStatusBar[level="success"] {{ color: {t.success}; }}
QStatusBar[level="warning"] {{ color: {t.warning}; }}
QStatusBar[level="error"] {{ color: {t.error}; }}
QLabel#welcomeTitle {{ color: {t.text}; background: transparent; {_qss_font("display", base_point_size)} }}
QLabel#pageTitle {{ color: {t.text}; background: transparent; {_qss_font("page_title", base_point_size)} }}
QPushButton#startTile {{ background: {t.accent}; border: {ln}px solid {t.accent}; border-radius: {m.radius_m}px; }}
QLabel#tileTitle {{ color: {t.accent_text}; background: transparent;
    {_qss_font("tile_title", base_point_size)} }}
QLabel#tileText {{ color: {t.accent_text}; background: transparent; }}
QPushButton#startTile:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton#startTile:focus {{ border: {2 * ln}px solid {t.text}; }}
QPushButton#primaryBtn {{ background: {t.accent}; color: {t.accent_text}; border: {ln}px solid {t.accent};
    border-radius: {btr}px; padding: {m.s2}px {m.s4}px; font-weight: 600; }}
QPushButton#primaryBtn:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton#primaryBtn:disabled {{ background: {t.elevated}; color: {dis_text}; border-color: {t.border}; }}
QLabel#dialogSection {{ color: {t.muted_text}; background: transparent; font-weight: 700;
    border-bottom: {ln}px solid {t.border}; padding-bottom: {m.s1}px; }}
QLabel#descriptionBox {{ color: {t.text}; background: {t.elevated}; border: {ln}px solid {t.border};
    border-radius: {m.radius_s}px; padding: {m.s2}px {m.s3}px; }}
QListWidget#presetList {{ background: {t.elevated}; color: {t.text}; border: {ln}px solid {t.border_active};
    border-radius: {m.radius_s}px; outline: 0; }}
QListWidget#recentList {{ background: {t.elevated}; color: {t.text}; border: {ln}px solid {t.border_active};
    border-radius: {m.radius_s}px; outline: 0; }}
QMenuBar {{ background: {t.base}; }}
QMenuBar::item {{ background: transparent; padding: {m.s1}px {m.s3}px; }}
QMenuBar::item:selected {{ background: {t.elevated}; }}
QMenu {{ background: {t.floating}; border: {ln}px solid {t.border};
    border-radius: {m.radius_s}px; padding: {m.s1}px 0; }}
QMenu::item {{ padding: {m.s2}px {m.s4}px; border-left: {m.bar}px solid transparent; }}
QMenu::item:selected {{ background: {t.accent_dim}; color: {t.text}; border-left: {m.bar}px solid {t.accent}; }}
QMenu::item:disabled {{ color: {t.disabled_text}; }}
QMenu::separator {{ height: {ln}px; background: {t.border}; margin: {m.s1}px 0; }}
"""


def apply_theme(theme: Theme, point_size: int) -> None:
    """Apply style, palette, font and stylesheet to the whole application."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        raise RuntimeError("apply_theme needs a QApplication")
    app.setStyle("Fusion")
    font = app.font()
    font.setFamilies(list(FONT_FAMILIES))
    font.setPointSize(clamp_point_size(point_size))
    app.setFont(font)
    app.setPalette(build_palette(theme))
    app.setStyleSheet(build_stylesheet(theme, metrics(), float(point_size)))


def load_appearance() -> tuple[Theme, int]:
    s = settings()
    theme = THEMES.get(str(s.value("appearance/theme", DARK.name)), DARK)
    try:
        size = int(s.value("appearance/point_size", DEFAULT_POINT_SIZE))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        size = DEFAULT_POINT_SIZE
    return theme, clamp_point_size(size)


def save_appearance(theme: Theme, point_size: int) -> None:
    s = settings()
    s.setValue("appearance/theme", theme.name)
    s.setValue("appearance/point_size", clamp_point_size(point_size))
    s.sync()
