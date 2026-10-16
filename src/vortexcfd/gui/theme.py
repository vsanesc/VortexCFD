"""Design tokens and application of the look (Fusion style + palette + stylesheet).

Every color lives in a ``Theme`` token; change a token here and nothing else.
"""

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QFontMetrics, QPalette
from PySide6.QtWidgets import QApplication

ORGANIZATION = "VortexCFD"
APPLICATION = "VortexCFD"

DEFAULT_POINT_SIZE = 11
MIN_POINT_SIZE = 8
MAX_POINT_SIZE = 24


@dataclass(frozen=True)
class Theme:
    """Named colors (hex strings). Text tokens meet WCAG AA on the surfaces they sit on."""

    name: str
    window: str
    panel: str
    base: str
    text: str
    muted_text: str
    accent: str
    accent_text: str
    border: str
    success: str
    warning: str
    error: str
    viewer_top: str
    viewer_bottom: str


DARK = Theme(
    name="dark",
    window="#1e2227",
    panel="#262b32",
    base="#1a1d22",
    text="#e6e9ee",
    muted_text="#a3adba",
    accent="#2f6fb5",
    accent_text="#ffffff",
    border="#3b424c",
    success="#5fd38d",
    warning="#f0b429",
    error="#ff7b72",
    viewer_top="#2e3640",
    viewer_bottom="#14171b",
)

LIGHT = Theme(
    name="light",
    window="#eef0f3",
    panel="#e3e7ec",
    base="#ffffff",
    text="#1b1f24",
    muted_text="#4d5866",
    accent="#1f62a8",
    accent_text="#ffffff",
    border="#b9c1cc",
    success="#16692e",
    warning="#8a5a00",
    error="#b3261e",
    viewer_top="#eaeff5",
    viewer_bottom="#b4bfcc",
)

THEMES: dict[str, Theme] = {DARK.name: DARK, LIGHT.name: LIGHT}


def clamp_point_size(size: int) -> int:
    return max(MIN_POINT_SIZE, min(MAX_POINT_SIZE, int(size)))


def build_palette(t: Theme) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.window,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.base,
        QPalette.ColorRole.AlternateBase: t.panel,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.panel,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.accent_text,
        QPalette.ColorRole.ToolTipBase: t.panel,
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


def build_stylesheet(t: Theme, unit: int) -> str:
    """Stylesheet for what the palette cannot express. ``unit`` is the font height in px."""
    s = max(2, round(unit * 0.25))  # small gap
    return f"""
QToolTip {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.border}; padding: {s}px; }}
QSplitter::handle {{ background: {t.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QWidget#pane {{ background: {t.panel}; }}
QLabel#muted {{ color: {t.muted_text}; }}
QLabel#sectionTitle {{ color: {t.muted_text}; font-weight: 600; }}
QTreeView {{ background: {t.base}; border: 1px solid {t.border}; outline: 0; }}
QTreeView::item {{ padding: {s}px; }}
QTreeView::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
QLineEdit, QComboBox {{
    background: {t.base}; color: {t.text}; border: 1px solid {t.border};
    border-radius: {s}px; padding: {s}px {2 * s}px;
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {t.accent}; }}
QLineEdit[readOnly="true"] {{ background: {t.panel}; color: {t.muted_text}; }}
QComboBox QAbstractItemView {{
    background: {t.base}; color: {t.text}; selection-background-color: {t.accent};
    selection-color: {t.accent_text}; border: 1px solid {t.border};
}}
QStatusBar {{ background: {t.panel}; color: {t.text}; border-top: 1px solid {t.border}; }}
QStatusBar[level="success"] {{ color: {t.success}; }}
QStatusBar[level="warning"] {{ color: {t.warning}; }}
QStatusBar[level="error"] {{ color: {t.error}; }}
QMenuBar {{ background: {t.window}; }}
QMenu {{ background: {t.panel}; border: 1px solid {t.border}; }}
QMenu::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
"""


def apply_theme(theme: Theme, point_size: int) -> None:
    """Apply style, palette, font and stylesheet to the whole application."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        raise RuntimeError("apply_theme needs a QApplication")
    app.setStyle("Fusion")
    font = app.font()
    font.setPointSize(clamp_point_size(point_size))
    app.setFont(font)
    app.setPalette(build_palette(theme))
    app.setStyleSheet(build_stylesheet(theme, QFontMetrics(app.font()).height()))


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
