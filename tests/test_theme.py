"""Tests for the Tungsten & Amber theme, zoom, icons, layout and the no-literals rule."""

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.project import Project
from vortexcfd.gui.main_window import MainWindow
from vortexcfd.gui.theme import DARK, DIM_ALPHA, blend, MAX_POINT_SIZE, MIN_POINT_SIZE, metrics

GUI_DIR = Path(__file__).resolve().parent.parent / "src" / "vortexcfd" / "gui"


def _lum(color: str) -> float:
    def ch(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    c = QColor(color)
    return 0.2126 * ch(c.redF()) + 0.7152 * ch(c.greenF()) + 0.0722 * ch(c.blueF())


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_owner_values_are_exact() -> None:
    """Fixed by the owner: change only on his request."""
    t = DARK
    assert (t.canvas, t.base, t.elevated) == ("#0A0D12", "#12161F", "#1A202C")
    assert (t.floating, t.border, t.border_active) == ("#232B3A", "#2A3446", "#3B4963")
    assert (t.accent_secondary, t.accent_secondary_hover) == ("#00B4A2", "#14C8B6")
    assert (t.accent, t.accent_hover) == ("#FF8800", "#FFA033")
    assert (t.text, t.muted_text, t.disabled_text, t.accent_text) == (
        "#F1F5F9", "#94A3B8", "#526077", "#0A0D12",
    )
    assert (t.success, t.warning, t.error) == ("#10B981", "#FACC15", "#F43F5E")
    assert (t.part_surface, t.part_edge) == ("#7F8DA3", "#2A3446")
    assert t.part_selected == t.accent_secondary == "#00B4A2"
    # Mesh section: edges in the owner's disabled_text colour, faces in elevated.
    assert t.mesh_edge == t.disabled_text == "#526077"
    assert t.mesh_surface == t.elevated == "#1A202C"
    # The dim tokens are the accents at alpha 0.15 over base; the selection row uses the teal one.
    assert t.accent_secondary_dim == blend("#00B4A2", t.base, 0.15)
    assert t.accent_dim == blend("#FF8800", t.base, 0.15)
    assert DIM_ALPHA == 0.15
    assert t.selection == t.accent_secondary_dim


def test_contrast() -> None:
    """disabled_text is exempt (disabled controls and placeholders only); all else >= 4.5."""
    t = DARK
    pairs = [(t.text, s) for s in (t.base, t.elevated, t.floating)]
    pairs += [(t.muted_text, s) for s in (t.base, t.elevated, t.floating)]
    pairs += [(t.accent_text, t.accent), (t.accent_text, t.accent_hover)]
    pairs += [(c, t.base) for c in (t.success, t.warning, t.error, t.accent, t.accent_hover,
                                    t.accent_secondary, t.accent_secondary_hover)]
    pairs += [(t.text, t.selection)]
    failures = [(a, b, round(contrast(a, b), 2)) for a, b in pairs if contrast(a, b) < 4.5]
    assert not failures, failures


def test_no_color_literals_outside_theme() -> None:
    hex_re = re.compile(r"#[0-9a-fA-F]{6}")
    qcolor_re = re.compile(r"""QColor\(\s*["']""")
    offenders = []
    for path in GUI_DIR.glob("*.py"):
        if path.name == "theme.py":
            continue
        text = path.read_text()
        if hex_re.search(text) or qcolor_re.search(text):
            offenders.append(path.name)
    assert not offenders, offenders


@pytest.fixture
def make_window(qtbot: QtBot):
    made: list[MainWindow] = []

    def make(with_viewer: bool = False) -> MainWindow:
        w = MainWindow(Project.new("Demo"), FakeDialogs(), with_viewer=with_viewer)
        qtbot.addWidget(w)
        made.append(w)
        return w

    yield make
    for w in made:
        assert not w.project.observer_errors
        w.project.save = lambda *a, **k: None  # closing must not prompt or write
        w.close()


def test_zoom_actions_and_persistence(make_window) -> None:
    window = make_window()
    app = QApplication.instance()
    assert app.font().pointSize() == 11
    window.act_zoom_in.trigger()
    assert app.font().pointSize() == 12
    window.set_point_size(MAX_POINT_SIZE - 1)
    for _ in range(3):  # one step reaches the maximum, the rest must be ignored
        window.act_zoom_in.trigger()
    assert app.font().pointSize() == MAX_POINT_SIZE
    window.set_point_size(MIN_POINT_SIZE + 1)
    for _ in range(3):  # one step reaches the minimum
        window.act_zoom_out.trigger()
    assert app.font().pointSize() == MIN_POINT_SIZE
    window.act_zoom_in.trigger()
    assert int(QSettings("VortexCFD", "VortexCFD").value("appearance/point_size")) == 9
    window.act_zoom_reset.trigger()
    assert app.font().pointSize() == 11


def test_point_size_restored_by_new_window(make_window) -> None:
    make_window().set_point_size(15)
    assert make_window().point_size == 15


def test_settings_use_temp_path(isolated_settings) -> None:
    assert str(isolated_settings) in QSettings("VortexCFD", "VortexCFD").fileName()


def test_no_theme_menu(make_window) -> None:
    window = make_window()
    assert [a.text() for a in window.menuBar().actions()] == ["&File", "&Edit", "&View"]
    view = window.menuBar().actions()[2].menu()
    assert [a.text() for a in view.actions() if a.menu() is not None] == ["Viewport &Telemetry"]  # no Theme menu


def test_icons_exist_and_scale_with_font(make_window) -> None:
    window = make_window()
    window.show()
    items = list(window._items.values())
    assert all(not it.icon(0).isNull() for it in items)
    window.set_point_size(10)
    small = window.tree.iconSize().height()
    small_px = window._items[("geometry", None)].icon(0).availableSizes()[0].width()
    window.set_point_size(20)
    assert window.tree.iconSize().height() > small
    assert window._items[("geometry", None)].icon(0).availableSizes()[0].width() > small_px


def test_status_level_property(make_window) -> None:
    window = make_window()
    window.show_message("bad", "error")
    assert window.statusBar().property("level") == "error"


def test_source_field_is_read_only(make_window) -> None:
    assert make_window().properties.source_label.isReadOnly()


def test_axes_label_color_matches_text_token(make_window) -> None:
    window = make_window(with_viewer=True)
    axes = window.viewer.renderer.axes_actor
    rgb = axes.GetXAxisCaptionActor2D().GetCaptionTextProperty().GetColor()
    got = QColor.fromRgbF(*rgb)
    assert got == QColor(DARK.text)
