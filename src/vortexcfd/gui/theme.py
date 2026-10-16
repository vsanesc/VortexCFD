"""Design tokens and application of the look (Fusion style + palette + stylesheet).

Every color lives in a ``Theme`` token and every size derives from the font height
(``Metrics``): change a value here and nothing else. The "Tungsten & Amber" values marked
as owner values are fixed by the owner and change only on his request.
"""

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import QApplication

ORGANIZATION = "VortexCFD"
APPLICATION = "VortexCFD"

DEFAULT_POINT_SIZE = 11
MIN_POINT_SIZE = 8
MAX_POINT_SIZE = 24

# Application font family stack: the first installed family wins.
FONT_FAMILIES: tuple[str, ...] = ("Inter", "Segoe UI", "Noto Sans", "DejaVu Sans")


@dataclass(frozen=True)
class Theme:
    """Named colors (hex strings)."""

    name: str
    canvas: str  # viewer background
    base: str  # window, menu bar, side panels, tree, status bar
    elevated: str  # inputs, section headers, tree row hover
    floating: str  # menus, popups, tooltips, dialogs
    border: str
    border_active: str
    text: str
    muted_text: str
    accent: str
    accent_text: str
    selection: str  # selected tree row
    success: str
    warning: str
    error: str
    axis_x: str
    axis_y: str
    axis_z: str


# Tungsten & Amber. The first six colors are the owner's table.
DARK = Theme(
    name="dark",
    canvas="#0A0D12",
    base="#12161F",
    elevated="#1A202C",
    floating="#232B3A",
    border="#2A3446",
    border_active="#3B4963",
    text="#E6EAF2",  # PROVISIONAL: not in owner table
    muted_text="#94A0B5",  # PROVISIONAL: not in owner table
    accent="#F5A524",  # PROVISIONAL: not in owner table
    accent_text="#1A1205",  # PROVISIONAL: not in owner table
    selection="#3F3320",  # PROVISIONAL: not in owner table
    success="#4CC38A",  # PROVISIONAL: not in owner table
    warning="#E5B94E",  # PROVISIONAL: not in owner table
    error="#F2555A",  # PROVISIONAL: not in owner table
    axis_x="#F2555A",  # PROVISIONAL: not in owner table
    axis_y="#4CC38A",  # PROVISIONAL: not in owner table
    axis_z="#5B9CF5",  # PROVISIONAL: not in owner table
)

THEMES: dict[str, Theme] = {DARK.name: DARK}


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
    row: int  # tree row height (1.8u)
    field: int  # input height (2u)
    radius_s: int  # 0.25u
    radius_m: int  # 0.5u
    menubar: int  # menu bar height (2u)
    status: int  # status bar height (2u)
    strip: int  # top/bottom pill strip height (3.4u)
    sidebar_header: int  # project header height (3u)
    pill_h: int  # pill height (2.4u); pill radius is half of it
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
        header=k(2), row=k(1.8), field=k(2), radius_s=k(0.25), radius_m=k(0.5), hit=k(0.5),
        menubar=k(2), status=k(2), strip=k(3.4), sidebar_header=k(3), pill_h=k(2.4),
    )


def clamp_point_size(size: int) -> int:
    return max(MIN_POINT_SIZE, min(MAX_POINT_SIZE, int(size)))


def section_title_font(base: QFont) -> QFont:
    """Bold, 0.85 of the base size, letter-spaced (use with an upper-case title)."""
    font = QFont(base)
    font.setPointSizeF(base.pointSizeF() * 0.85)
    font.setBold(True)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
    return font


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
        QPalette.ColorRole.PlaceholderText: t.muted_text,
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
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.muted_text))
    return p


def build_stylesheet(t: Theme, m: Metrics, base_point_size: float) -> str:
    """Stylesheet for what the palette cannot express."""
    ln = m.line
    inner = m.field - 2 * ln
    status_pt = f"{base_point_size * 0.9:.1f}pt"
    return f"""
QToolTip {{ background: {t.floating}; color: {t.text}; border: {ln}px solid {t.border};
    border-radius: {m.radius_s}px; padding: {m.s2}px {m.s3}px; }}
QWidget#pane {{ background: {t.base}; }}
QWidget#canvas {{ background: {t.canvas}; }}
QLabel#muted {{ color: {t.muted_text}; }}
QLabel#sectionTitle {{ background: {t.elevated}; color: {t.muted_text};
    border: none; border-bottom: {ln}px solid {t.border}; padding: 0 {m.s3}px; }}
QTreeView {{ background: {t.base}; border: none; outline: 0; }}
QTreeView::item {{ background: transparent; }}
QWidget#stripTop {{ background: {t.base}; border-bottom: {ln}px solid {t.border}; }}
QWidget#stripBottom {{ background: {t.base}; border-top: {ln}px solid {t.border}; }}
QFrame#pill {{ background: {t.elevated}; border: {ln}px solid {t.border}; border-radius: {m.pill_h // 2}px; }}
QPushButton#segBtn, QPushButton#viewBtn {{
    background: transparent; color: {t.muted_text}; border: {ln}px solid transparent;
    border-radius: {(m.pill_h - 2 * (m.s1 + ln)) // 2}px; padding: 0 {m.s4}px;
}}
QPushButton#segBtn:hover, QPushButton#viewBtn:hover {{ color: {t.text}; }}
QPushButton#viewBtn:hover {{ background: {t.floating}; }}
QPushButton#segBtn:checked {{ background: {t.floating}; color: {t.text}; border: {ln}px solid {t.accent}; }}
QPushButton#viewBtn:disabled {{ color: {t.muted_text}; background: transparent; }}
QWidget#sidebarHeader {{ background: {t.base}; border-bottom: {ln}px solid {t.border}; }}
QPushButton#headerName {{ background: transparent; border: none; color: {t.text};
    text-align: left; padding: {m.s1}px {m.s2}px; border-radius: {m.radius_s}px; }}
QPushButton#headerName:hover {{ background: {t.elevated}; }}
QLabel#dirtyDot {{ color: {t.accent}; background: transparent; }}
QToolButton {{ background: transparent; border: none; border-radius: {m.radius_s}px; padding: {m.s1}px; }}
QToolButton:hover {{ background: {t.elevated}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QFrame#cardHeader {{ background: {t.elevated}; border: none; border-bottom: {ln}px solid {t.border}; }}
QLabel#cardTitle {{ color: {t.muted_text}; font-weight: bold; background: transparent; }}
QLabel#cardToggle {{ background: transparent; }}
QLineEdit, QComboBox {{
    background: {t.elevated}; color: {t.text}; border: {ln}px solid {t.border};
    border-radius: {m.radius_s}px; padding: 0 {m.s2}px; min-height: {inner}px;
    selection-background-color: {t.accent}; selection-color: {t.accent_text};
}}
QLineEdit:hover, QComboBox:hover {{ border-color: {t.border_active}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {t.accent}; }}
QLineEdit[readOnly="true"], QLineEdit[readOnly="true"]:hover {{
    background: {t.base}; color: {t.muted_text}; border-color: transparent;
}}
QComboBox::drop-down {{ border: none; width: {m.s5}px; }}
QComboBox QAbstractItemView {{
    background: {t.floating}; color: {t.text}; border: {ln}px solid {t.border};
    selection-background-color: {t.elevated}; selection-color: {t.text}; outline: 0;
}}
QAbstractButton:checked {{ background: {t.elevated}; border: {ln}px solid {t.accent}; }}
QStatusBar {{ background: {t.base}; color: {t.text}; border-top: {ln}px solid {t.border};
    font-size: {status_pt}; }}
QStatusBar::item {{ border: none; }}
QStatusBar[level="success"] {{ color: {t.success}; }}
QStatusBar[level="warning"] {{ color: {t.warning}; }}
QStatusBar[level="error"] {{ color: {t.error}; }}
QMenuBar {{ background: {t.base}; }}
QMenuBar::item {{ background: transparent; padding: {m.s1}px {m.s3}px; }}
QMenuBar::item:selected {{ background: {t.elevated}; }}
QMenu {{ background: {t.floating}; border: {ln}px solid {t.border};
    border-radius: {m.radius_s}px; padding: {m.s1}px 0; }}
QMenu::item {{ padding: {m.s2}px {m.s4}px; border-left: {m.bar}px solid transparent; }}
QMenu::item:selected {{ background: {t.elevated}; border-left: {m.bar}px solid {t.accent}; }}
QMenu::item:disabled {{ color: {t.muted_text}; }}
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


def settings() -> QSettings:
    """User settings (created on demand so a redirected QSettings path is honored)."""
    return QSettings(ORGANIZATION, APPLICATION)


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
