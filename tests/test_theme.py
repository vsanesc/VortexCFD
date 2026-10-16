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
from vortexcfd.gui.theme import DARK, MAX_POINT_SIZE, MIN_POINT_SIZE, metrics

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
    assert DARK.canvas == "#0A0D12"
    assert DARK.base == "#12161F"
    assert DARK.elevated == "#1A202C"
    assert DARK.floating == "#232B3A"
    assert DARK.border == "#2A3446"
    assert DARK.border_active == "#3B4963"


def test_contrast() -> None:
    t = DARK
    pairs = [(t.text, s) for s in (t.base, t.elevated, t.floating)]
    pairs += [(t.muted_text, s) for s in (t.base, t.elevated, t.floating)]
    pairs += [(t.accent_text, t.accent)]
    pairs += [(c, t.base) for c in (t.success, t.warning, t.error, t.accent)]
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
    for _ in range(30):
        window.act_zoom_in.trigger()
    assert app.font().pointSize() == MAX_POINT_SIZE
    for _ in range(30):
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
    assert all(a.menu() is None for a in view.actions())


def test_icons_exist_and_scale_with_font(make_window) -> None:
    window = make_window()
    window.show()
    root = window.tree.topLevelItem(0)
    items = [root] + [root.child(i) for i in range(root.childCount())]
    assert all(not it.icon(0).isNull() for it in items)
    window.set_point_size(10)
    small = window.tree.iconSize().height()
    small_px = window.tree.topLevelItem(0).icon(0).availableSizes()[0].width()
    window.set_point_size(20)
    assert window.tree.iconSize().height() > small
    assert window.tree.topLevelItem(0).icon(0).availableSizes()[0].width() > small_px


def test_status_level_property(make_window) -> None:
    window = make_window()
    window.show_message("bad", "error")
    assert window.statusBar().property("level") == "error"


def test_source_field_is_read_only(make_window) -> None:
    assert make_window().properties.source_label.isReadOnly()


@pytest.mark.parametrize("with_viewer", [False, True])
@pytest.mark.parametrize("font", [11, 14, 18])
def test_layout_proportions(make_window, qtbot: QtBot, font: int, with_viewer: bool) -> None:
    window = make_window(with_viewer)
    window.set_point_size(font)
    u = metrics().u
    width, height = 78 * u, 47 * u
    window.resize(width, height)
    window.show()
    qtbot.waitUntil(window.isVisible)
    qtbot.wait(50)
    left, center, right = window._splitter.sizes()
    print(f"font {font} viewer {with_viewer}: u={u} left={left} center={center} right={right}")
    assert 11 * u <= left <= 22 * u
    assert 14 * u <= right <= 28 * u
    assert window.width() <= width and window.height() <= height
    assert center >= 0.5 * window.width()


def test_axes_label_color_matches_text_token(make_window) -> None:
    window = make_window(with_viewer=True)
    axes = window.viewer.renderer.axes_actor
    rgb = axes.GetXAxisCaptionActor2D().GetCaptionTextProperty().GetColor()
    got = QColor.fromRgbF(*rgb)
    assert got == QColor(DARK.text)
