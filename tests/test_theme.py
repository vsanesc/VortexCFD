"""Tests for the Zinc & Teal theme (D-144), zoom, icons, layout and the no-literals rule."""

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
from vortexcfd.gui.theme import (DARK, DEFAULT_POINT_SIZE, DIM_ALPHA, INTERFACE_SIZES, MAX_POINT_SIZE, MIN_POINT_SIZE,
                                 blend, metrics)

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
    """Fixed by the owner (D-144, replacing Tungsten & Amber): change only on his request."""
    t = DARK
    assert (t.canvas, t.base) == ("#18181B", "#27272A")  # background, panel
    assert (t.accent, t.accent_secondary) == ("#2DD4BF", "#F59E0B")  # teal accent, amber secondary
    assert t.text == "#FAFAFA"
    # chosen for AA on the background and the panel (the zinc scale and the accents' lighter steps)
    assert (t.elevated, t.floating, t.border, t.border_active) == ("#1C1C20", "#303036", "#3F3F46", "#52525B")
    assert (t.muted_text, t.disabled_text, t.accent_text) == ("#A1A1AA", "#71717A", "#18181B")
    assert (t.accent_hover, t.accent_secondary_hover) == ("#5EEAD4", "#FBBF24")
    assert (t.success, t.warning, t.error) == ("#22C55E", "#F59E0B", "#FB7185")
    assert t.warning == t.accent_secondary  # the secondary colour is for highlights and warnings
    assert t.part_selected == t.accent  # selection is the accent, never the secondary
    assert t.mesh_edge == t.disabled_text and t.mesh_surface == t.elevated
    # the dim tokens are the accents at alpha 0.15 over the panel; the selected row uses the teal one
    assert t.accent_dim == blend("#2DD4BF", t.base, 0.15)
    assert t.accent_secondary_dim == blend("#F59E0B", t.base, 0.15)
    assert DIM_ALPHA == 0.15
    assert t.selection == t.accent_dim


# Every text / background pair the GUI draws, with the minimum ratio (WCAG AA: 4.5 for text).
def contrast_pairs() -> list[tuple[str, str, str, str]]:
    t = DARK
    pairs = [(f"text on {n}", t.text, bg) for n, bg in (("canvas", t.canvas), ("base", t.base),
                                                         ("elevated", t.elevated), ("floating", t.floating),
                                                         ("selection", t.selection), ("accent_dim", t.accent_dim))]
    pairs += [(f"muted_text on {n}", t.muted_text, bg) for n, bg in (("canvas", t.canvas), ("base", t.base),
                                                                     ("elevated", t.elevated), ("floating", t.floating))]
    pairs += [("accent_text on accent", t.accent_text, t.accent), ("accent_text on accent_hover", t.accent_text,
                                                                     t.accent_hover)]
    pairs += [(f"{n} on base", c, t.base) for n, c in (
        ("success", t.success), ("warning", t.warning), ("error", t.error), ("accent", t.accent),
        ("accent_hover", t.accent_hover), ("accent_secondary", t.accent_secondary),
        ("accent_secondary_hover", t.accent_secondary_hover))]
    pairs += [(f"{n} on canvas", c, t.canvas) for n, c in (
        ("success", t.success), ("warning", t.warning), ("error", t.error), ("accent", t.accent),
        ("accent_secondary", t.accent_secondary))]
    pairs += [("accent on selection", t.accent, t.selection), ("accent on accent_dim", t.accent, t.accent_dim),
              ("accent on elevated", t.accent, t.elevated), ("error on elevated", t.error, t.elevated)]
    return [(name, a, b, "") for name, a, b in pairs]


def test_contrast() -> None:
    """disabled_text is exempt (disabled controls and placeholders only); every other pair >= 4.5 (AA)."""
    failures = [(name, round(contrast(a, b), 2)) for name, a, b, _ in contrast_pairs() if contrast(a, b) < 4.5]
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
    assert app.font().pointSize() == DEFAULT_POINT_SIZE == INTERFACE_SIZES["Small"] == 9  # compact default (D-148)
    window.act_zoom_in.trigger()
    assert app.font().pointSize() == 10
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
    assert app.font().pointSize() == DEFAULT_POINT_SIZE


def test_interface_size_menu_applies_and_is_remembered(make_window) -> None:
    window = make_window()
    assert window.interface_size() == "Small" and window.act_interface_sizes["Small"].isChecked()
    small_row = metrics().row
    window.act_interface_sizes["Large"].trigger()
    assert QApplication.instance().font().pointSize() == INTERFACE_SIZES["Large"]
    assert metrics().row > small_row and window.tree.iconSize().height() >= metrics().u
    assert window.act_interface_sizes["Large"].isChecked() and not window.act_interface_sizes["Small"].isChecked()
    assert make_window().interface_size() == "Large"  # remembered
    window.act_zoom_in.trigger()  # a zoom step between the sizes: none checked
    assert window.interface_size() is None
    assert not any(a.isChecked() for a in window.act_interface_sizes.values())
    window.set_interface_size("Medium")
    assert window.interface_size() == "Medium"


def test_point_size_restored_by_new_window(make_window) -> None:
    make_window().set_point_size(15)
    assert make_window().point_size == 15


def test_settings_use_temp_path(isolated_settings) -> None:
    assert str(isolated_settings) in QSettings("VortexCFD", "VortexCFD").fileName()


def test_no_theme_menu(make_window) -> None:
    window = make_window()
    assert [a.text() for a in window.menuBar().actions()] == ["&File", "&Edit", "&View", "&Solution", "&Help"]
    view = window.menuBar().actions()[2].menu()
    assert [a.text() for a in view.actions() if a.menu() is not None] == ["Interface &size", "Viewport &Telemetry"]


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
