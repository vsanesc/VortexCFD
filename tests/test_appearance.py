"""Tests for theme tokens, zoom, theme switching and icons."""

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.project import Project
from vortexcfd.gui.main_window import MainWindow
from vortexcfd.gui.theme import DARK, LIGHT, MAX_POINT_SIZE, MIN_POINT_SIZE, THEMES


def _lum(color: str) -> float:
    def ch(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    c = QColor(color)
    return 0.2126 * ch(c.redF()) + 0.7152 * ch(c.greenF()) + 0.0722 * ch(c.blueF())


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", [DARK, LIGHT], ids=lambda t: t.name)
def test_theme_contrast(theme) -> None:
    assert contrast(theme.text, theme.base) >= 4.5
    assert contrast(theme.text, theme.panel) >= 4.5
    assert contrast(theme.accent_text, theme.accent) >= 4.5
    assert contrast(theme.muted_text, theme.panel) >= 4.5
    assert contrast(theme.muted_text, theme.base) >= 4.5
    for token in (theme.success, theme.warning, theme.error):
        assert contrast(token, theme.panel) >= 4.5


@pytest.fixture
def window(qtbot: QtBot):
    w = MainWindow(Project.new("Demo"), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    yield w
    assert not w.project.observer_errors
    w.project.save = lambda *a, **k: None  # closing must not prompt or write
    w.close()


def test_zoom_actions_and_persistence(window: MainWindow) -> None:
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


def test_settings_are_restored_by_a_new_window(window: MainWindow, qtbot: QtBot) -> None:
    window.set_point_size(15)
    window.set_theme("light")
    other = MainWindow(Project.new("B"), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(other)
    assert other.point_size == 15 and other.theme is LIGHT
    assert other.act_light.isChecked() and not other.act_dark.isChecked()


def test_settings_use_temp_path(isolated_settings) -> None:
    s = QSettings("VortexCFD", "VortexCFD")
    assert str(isolated_settings) in s.fileName()


def test_theme_switch_updates_palette_and_stylesheet(window: MainWindow) -> None:
    app = QApplication.instance()
    assert app.palette().color(QPalette.ColorRole.Window) == QColor(DARK.window)
    assert DARK.accent in app.styleSheet()
    window.act_light.trigger()
    assert window.theme is LIGHT
    assert app.palette().color(QPalette.ColorRole.Window) == QColor(LIGHT.window)
    assert LIGHT.accent in app.styleSheet() and DARK.accent not in app.styleSheet()
    assert window.palette().color(QPalette.ColorRole.Base) == QColor(LIGHT.base)
    assert window.properties.palette().color(QPalette.ColorRole.Base) == QColor(LIGHT.base)
    assert window.act_light.isChecked()
    assert THEMES["dark"] is DARK


def test_icons_exist_and_scale_with_font(window: MainWindow) -> None:
    root = window.tree.topLevelItem(0)
    items = [root] + [root.child(i) for i in range(root.childCount())]
    assert all(not it.icon(0).isNull() for it in items)
    window.set_point_size(10)
    small = window.tree.iconSize().height()
    small_px = window.tree.topLevelItem(0).icon(0).availableSizes()[0].width()
    window.set_point_size(20)
    assert window.tree.iconSize().height() > small
    assert window.tree.topLevelItem(0).icon(0).availableSizes()[0].width() > small_px


def test_status_level_property(window: MainWindow) -> None:
    window.show_message("bad", "error")
    assert window.statusBar().property("level") == "error"
    window.show_message("ok", "success")
    assert window.statusBar().property("level") == "success"


def test_source_field_is_read_only(window: MainWindow) -> None:
    assert window.properties.source_label.isReadOnly()
