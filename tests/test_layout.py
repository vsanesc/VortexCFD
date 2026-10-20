"""Tests for the mockup layout: regions, toggles, tree structure, panels, console, buttons."""

import logging

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.gui.main_window import ROLE_EYE, MainWindow
from vortexcfd.gui.theme import LAYOUT, LEFT_INITIAL_U, LIMITS_U, metrics


@pytest.fixture
def make_window(qtbot: QtBot):
    made: list[MainWindow] = []

    def make(with_viewer: bool = False, parts: int = 2, size=(1400, 850)) -> MainWindow:
        project = Project.new("Demo")
        for i in range(parts):
            project.add_part(Part(name=f"Part {i + 1}", source_file=f"p{i}.stl", units="m"))
        w = MainWindow(project, FakeDialogs(), with_viewer=with_viewer)
        qtbot.addWidget(w)
        w.resize(*size)
        w.show()
        qtbot.waitUntil(w.isVisible)
        qtbot.wait(30)
        made.append(w)
        return w

    yield make
    for w in made:
        assert not w.project.observer_errors
        w.project.save = lambda *a, **k: None
        w.close()


@pytest.mark.parametrize("with_viewer", [False, True])
def test_region_proportions_at_1400x850(make_window, with_viewer: bool) -> None:
    w = make_window(with_viewer)
    W, H = w.width(), w.height()
    assert (W, H) == (1400, 850)
    tol = 0.03
    u = metrics().u
    assert abs(w._left.width() - LEFT_INITIAL_U * u) <= 0.5 * u  # the left column starts at 18u
    assert LIMITS_U["left"] == (14, 28)
    measured = {
        "monitors": w.monitors.width() / W,
        "console": w.console.height() / H,
        "top_bar": w.top_bar.height() / H,
        "tab_bar": w._tab_bar.height() / H,
        "tree_split": w._left_split.widget(0).height() / w._left.height(),
    }
    print({k: round(v, 3) for k, v in measured.items()})
    for key, value in measured.items():
        assert abs(value - getattr(LAYOUT, key)) <= tol, (key, value, getattr(LAYOUT, key))


@pytest.mark.parametrize("font", [11, 14, 18])
@pytest.mark.parametrize("with_viewer", [False, True])
def test_center_keeps_half_of_the_window_at_78u(make_window, font: int, with_viewer: bool, qtbot: QtBot) -> None:
    w = make_window(with_viewer)
    w.set_point_size(font)
    u = metrics().u
    width, height = 78 * u, 47 * u
    w.resize(width, height)
    w._apply_initial_sizes()  # the default layout for this window size
    qtbot.wait(60)
    left, right = w._left.width(), w.monitors.width()
    center = w._center.width()
    print(f"font {font} u={u}: left={left} center={center} monitors={right} of {w.width()}")
    lo, hi = LIMITS_U["left"]
    assert lo * u <= left <= hi * u
    assert abs(left - LEFT_INITIAL_U * u) <= 0.5 * u
    assert center >= 0.5 * w.width()
    assert w.width() <= width and w.height() <= height


def test_toggles_hide_and_restore_regions(make_window, qtbot: QtBot) -> None:
    w = make_window()
    before = (w._outer.sizes(), w._inner.sizes(), w._right_split.sizes())
    w.act_toggle_sidebars.trigger()
    assert w._left.isHidden() and w.monitors.isHidden()
    w.act_toggle_sidebars.trigger()
    qtbot.wait(30)
    assert (w._outer.sizes(), w._inner.sizes()) == before[:2]
    assert w.act_toggle_sidebars.shortcut().toString() == "Ctrl+B"
    w.act_toggle_monitors.trigger()
    assert w.monitors.isHidden() and not w.act_toggle_monitors.isChecked()
    w.act_toggle_monitors.trigger()
    qtbot.wait(30)
    assert w._inner.sizes() == before[1] and w.act_toggle_monitors.isChecked()
    w.act_toggle_console.trigger()
    assert w.console.isHidden()
    w.act_toggle_console.trigger()
    qtbot.wait(30)
    assert w._right_split.sizes() == before[2]


def test_tree_structure_and_node_count(make_window) -> None:
    w = make_window(parts=3)
    model = w.tree.model()
    root = w.tree.rootIndex()
    names = [model.data(model.index(r, 0, root)) for r in range(model.rowCount(root))]
    assert names == ["Geometry", "Surface Preparation (not run)", "Continua", "Regions", "Solvers", "Reports & Monitors"]
    geometry = w._items[("geometry", None)]
    assert [geometry.child(i).text(0) for i in range(geometry.childCount())] == ["Parts"]
    parts = w._items[("parts", None)]
    assert [parts.child(i).text(0) for i in range(parts.childCount())] == ["Part 1", "Part 2", "Part 3"]
    continua = w._items[("continua", None)]
    assert [continua.child(i).text(0) for i in range(continua.childCount())] == ["Mesh", "Physics"]
    fluid = w._items[("fluid_domain", None)]
    assert fluid.text(0) == "Fluid Domain" and fluid.parent() is w._items[("regions", None)]
    assert [fluid.child(i).text(0) for i in range(fluid.childCount())] == [
        "inlet", "outlet", "sides", "top", "bottom", "Part 1 (wall)", "Part 2 (wall)", "Part 3 (wall)",
    ]
    # Geometry, Parts, 3 parts, Continua, Mesh, Physics, Regions, Fluid Domain, 5 boundaries,
    # 3 walls, Inflow, Solvers, Reports = 21
    # + Stopping Criteria, Probes, Mesh Study, Polar Sweep, Fluid Region (D-078)
    # + Surface Preparation and its "Prepare surfaces..." entry (D-093) + Refinement volumes (D-103)
    assert w.node_count() == 30 and w.node_badge.text() == "30 Nodes"
    region = w._items[("fluid_region", None)]
    assert region.text(0) == "Fluid Region (domain minus parts)" and region.parent() is w._items[("regions", None)]
    reports = w._items[("reports", None)]
    assert [reports.child(i).text(0) for i in range(reports.childCount())] == [
        "Reference Values", "Probes", "Mesh Study", "Polar Sweep"]
    stopping = w._items[("stopping", None)]
    assert stopping.text(0) == "Stopping Criteria" and stopping.parent() is w._items[("solvers", None)]
    w.act_add_part.trigger()
    assert w.node_badge.text() == "32 Nodes"  # a part and its wall


def test_header_name_selects_root(make_window) -> None:
    w = make_window()
    w.tree.setCurrentItem(w._items[("part", 1)])
    assert w.props_name.text() == "Part 2"
    w.top_bar.name_button.click()
    assert w._selection == ("root", None)
    assert w.properties.name_edit.text() == "Demo" and w.props_name.text() == "Demo"
    assert w._selection_label.text() == "Active selection: Demo"


def test_search_filters_and_restores(make_window) -> None:
    w = make_window()
    w.tree.setCurrentItem(w._items[("part", 0)])
    w.search.setText("part 2")
    assert w._items[("part", 0)].isHidden() and not w._items[("part", 1)].isHidden()
    assert not w._items[("geometry", None)].isHidden()
    assert w._items[("mesh", None)].isHidden()
    assert w._selection == ("part", 0)
    w.search.setText("")
    assert all(not i.isHidden() for i in w._items.values())


def test_eye_toggles_gui_side_visibility(make_window) -> None:
    w = make_window()
    item = w._items[("part", 0)]
    assert item.data(0, ROLE_EYE) is True
    rect = w.tree.visualItemRect(item)
    pos = QPoint(w.tree.viewport().width() - 4, rect.center().y())
    QTest.mouseClick(w.tree.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert w._items[("part", 0)].data(0, ROLE_EYE) is False
    assert w.part_visibility == {"Part 1": False}
    assert w._selection == ("root", None)  # the click did not select the row
    assert w._items[("geometry", None)].data(0, ROLE_EYE) is None


def test_chevron_click_toggles_without_selecting(make_window) -> None:
    w = make_window()
    w.tree.setCurrentItem(w._items[("part", 0)])
    item = w._items[("geometry", None)]
    rect = w.tree.visualItemRect(item)
    assert item.isExpanded()
    QTest.mouseClick(w.tree.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(rect.left() + 2, rect.center().y()))
    assert not item.isExpanded()
    assert w._selection == ("part", 0)


def test_properties_header_and_rows(make_window) -> None:
    w = make_window()
    p = w.properties
    w.tree.setCurrentItem(w._items[("part", 0)])
    assert p._rows["name"].isVisible() and p._rows["source"].isVisible() and p._rows["units"].isVisible()
    assert w.props_name.text() == "Part 1"
    w.tree.setCurrentItem(w._items[("geometry", None)])
    assert w.props_name.text() == "Geometry"
    assert not p._rows["name"].isVisible() and p.info_label.isVisible()
    w._select_root()
    assert p._rows["name"].isVisible() and not p._rows["source"].isVisible()


def test_future_actions_are_disabled_with_tooltips(make_window) -> None:
    w = make_window()
    assert not w.top_bar.mesh_button.isEnabled() and not w.top_bar.run_button.isEnabled()
    assert w.top_bar.mesh_button.toolTip()  # says why (readiness is tested in test_mesh_gui)
    assert "Save the project" in w.top_bar.run_button.toolTip()  # readiness: tests/test_solver_gui.py
    assert w.top_bar.mesh_button.text() == "Generate Mesh" and w.top_bar.run_button.text() == "Run Solver"


def test_top_bar_state_follows_dirty(make_window, tmp_path) -> None:
    w = make_window()
    badge = w.top_bar.state_badge
    assert w.top_bar.name_button.text() == "Untitled"
    assert badge.text() == "Modified" and badge.dot_color() == w._theme.warning
    w.project.save(tmp_path / "proj.json")
    assert w.top_bar.name_button.text() == "proj.json"
    assert badge.text() == "Saved" and badge.dot_color() == w._theme.success


def test_report_slots_are_empty_and_unassigned(make_window) -> None:
    from vortexcfd.gui.monitors import REPORT_SLOTS

    w = make_window()
    slots = w.monitors.kpis
    assert REPORT_SLOTS == 3
    assert [t.text() for t in slots.titles.values()] == ["REPORT 1", "REPORT 2", "REPORT 3"]
    assert all(v.text() == "\u2014" for v in slots.values.values())
    assert all(v.text() == "Not assigned" for v in slots.subtitles.values())
    for button in slots.assign_buttons.values():  # assignment: tests/test_monitors_gui.py
        assert button.isEnabled() and button.toolTip() == slots.ASSIGN_TOOLTIP
        assert "force coefficients" in button.toolTip() and "y+ min" in button.toolTip()
    assert w.monitors.chart.EMPTY_MESSAGE == "No solver run yet"
    assert (w.monitors.chart.X_CAPTION, w.monitors.chart.Y_CAPTION) == ("Iteration", "Residual")
    assert w.monitors.chart.axis_labels() == ["1e0", "1e-1", "1e-2", "1e-3", "1e-4", "1e-5", "1e-6"]
    assert w.monitors.header.badge.text() == "Log10 Scale"


def test_no_coefficient_names_in_the_ui(make_window) -> None:
    from PySide6.QtWidgets import QLabel, QPushButton

    w = make_window()
    texts = [x.text() for x in w.findChildren(QLabel)] + [x.text() for x in w.findChildren(QPushButton)]
    texts += [x.toolTip() for x in w.findChildren(QPushButton)]
    import re

    banned = re.compile(r"lift|drag|coeff|max wall y\+|\bcl\b|\bcd\b|converged", re.IGNORECASE)
    offenders = [t for t in texts if banned.search(t)]
    assert not offenders, offenders


def test_console_receives_log_records_and_clears(make_window, tmp_path) -> None:
    w = make_window()
    assert "VortexCFD started" in w.console.text()
    logging.getLogger("vortexcfd.test").warning("something odd")
    assert "something odd" in w.console.text() and "WARNING" in w.console.text()
    w.project.save(tmp_path / "x.json")
    w.save()  # the window logs one INFO line per save
    assert "Saved" in w.console.text() and "x.vcfd" in w.console.text()
    w.console.clear_button.click()
    assert w.console.text() == ""


def test_telemetry_rows_real_values_in_order(make_window) -> None:
    w = make_window(parts=3)
    w.tree.setCurrentItem(w._items[("part", 1)])
    assert w.telemetry_rows == [
        ("Parts", "3"), ("Selected node", "Part 2"), ("Triangles", "\u2014"),
        ("Cells", "\u2014"), ("Domain", "\u2014"), ("View", "ISO"),
    ]


def test_telemetry_follows_checked_fields_and_persists(make_window, qtbot) -> None:
    from PySide6.QtCore import QSettings

    w = make_window(with_viewer=True)
    w.act_tel_fields["selected"].trigger()  # uncheck
    w.act_tel_fields["view"].trigger()
    w.act_tel_fields["triangles"].trigger()
    w.act_tel_fields["domain"].trigger()
    assert [label for label, _ in w.telemetry_rows] == ["Parts", "Cells"]
    assert w.telemetry.visible and "Selected" not in w.telemetry.labels.GetInput()
    for key in ("parts", "cells"):
        w.act_tel_fields[key].trigger()
    assert w.telemetry_rows == [] and not w.telemetry.visible  # no field checked: card hidden
    w.act_tel_fields["parts"].trigger()
    assert w.telemetry.visible
    w.act_tel_show.trigger()  # hide everything
    assert w.telemetry_rows == [] and not w.telemetry.visible
    s = QSettings("VortexCFD", "VortexCFD")
    assert str(s.value("telemetry/show")).lower() == "false"
    assert str(s.value("telemetry/field_selected")).lower() == "false"
    other = make_window(with_viewer=True)  # a new window restores the choices
    assert not other.act_tel_show.isChecked()
    # "field_range" stays checked: it is a Results Scene row only
    assert [k for k, a in other.act_tel_fields.items() if a.isChecked()] == ["parts", "field_range"]


def test_telemetry_card_actors_use_token_colors(make_window) -> None:
    from PySide6.QtGui import QColor

    from vortexcfd.gui.viewport import TITLE

    w = make_window(with_viewer=True)
    t, card = w._theme, w.telemetry

    def rgb(actor):
        return QColor.fromRgbF(*actor.GetTextProperty().GetColor())

    assert card.title.GetInput().strip() == TITLE and TITLE == "VIEWPORT TELEMETRY"
    assert rgb(card.title) == QColor(t.accent_secondary)
    assert rgb(card.labels) == QColor(t.muted_text) and rgb(card.values) == QColor(t.text)
    box = card.box.GetTextProperty()
    assert QColor.fromRgbF(*box.GetBackgroundColor()) == QColor(t.elevated)
    assert 0.9 <= box.GetBackgroundOpacity() <= 0.95
    assert box.GetFrame() and QColor.fromRgbF(*box.GetFrameColor()) == QColor(t.border)
    labels = card.labels.GetInput().splitlines()
    values = card.values.GetInput().splitlines()
    assert any("Parts" in line for line in labels) and any("Cells" in line for line in labels)
    assert any(line.rstrip().endswith("\u2014") for line in values)


def test_default_scene_has_grid_and_no_sphere(make_window) -> None:
    w = make_window(with_viewer=True)
    names = set(w.viewer.renderer.actors)
    assert {"grid_minor", "grid_major"} <= names
    assert w.scene_actors == []
    # Nothing but the grid: the largest actor bounds are the grid extent (no sphere of radius 0.5).
    xmin, xmax, *_ = w.viewer.bounds
    assert xmax - xmin >= 10
    assert w._empty_message.actor.GetInput() == "No geometry yet"
    assert w.current_view == "ISO" and w.top_bar.active_view() == "ISO"


def test_logo_and_window_icon(make_window) -> None:
    from vortexcfd.gui.icons import logo_icon, logo_pixmap
    from vortexcfd.gui.theme import WINDOW_ICON_SIZES

    w = make_window()
    for side in (16, 32, 64):
        pm = logo_pixmap(w._theme, side)
        assert not pm.isNull() and pm.width() == side
    icon = w.windowIcon()
    assert not icon.isNull()
    assert len(icon.availableSizes()) == len(WINDOW_ICON_SIZES)
    assert not logo_icon(w._theme, (24,)).isNull()
    assert not w.top_bar._logo.pixmap().isNull()


def test_view_buttons_disabled_without_viewer(make_window) -> None:
    w = make_window(with_viewer=False)
    assert not any(b.isEnabled() for b in w.top_bar.view_buttons.values())
    assert not w.top_bar.wireframe_button.isEnabled()


def test_segmented_control_active_state_follows_last_view(make_window, monkeypatch) -> None:
    w = make_window(with_viewer=True)
    calls: list[str] = []
    for name in ("reset_camera", "view_isometric", "view_xz", "view_xy", "view_yz"):
        monkeypatch.setattr(w.viewer, name, lambda n=name, **k: calls.append(n))
    monkeypatch.setattr(w.viewer, "render", lambda *a, **k: None)
    bar = w.top_bar
    texts = {b.text(): b for b in bar.view_buttons.values()}
    assert list(texts) == ["ISO", "XY", "XZ", "YZ", "Fit"]
    assert bar.active_view() == "ISO"
    for label in ("XY", "XZ", "YZ"):
        texts[label].click()
        assert bar.active_view() == label and w.current_view == label
        assert dict(w.telemetry_rows)["View"] == label
    texts["Fit"].click()  # momentary: the active view is unchanged
    assert bar.active_view() == "YZ" and not texts["Fit"].isChecked()
    texts["ISO"].click()
    texts["ISO"].click()  # clicking the active segment keeps it active
    assert bar.active_view() == "ISO"
    assert calls == ["view_xy", "view_xz", "view_yz", "reset_camera", "view_isometric", "view_isometric"]
    w._on_camera_interaction()  # the user rotated the camera
    assert bar.active_view() is None and w.current_view == "Custom"
    assert dict(w.telemetry_rows)["View"] == "Custom"


def test_wireframe_toggle_switches_representation(make_window) -> None:
    import pyvista as pv

    w = make_window(with_viewer=True)
    actor = w.viewer.add_mesh(pv.Sphere(), reset_camera=False)
    w.add_scene_actor(actor)
    assert actor.prop.style.lower() == "surface"
    assert not w._empty_message.actor.GetVisibility()
    w.top_bar.wireframe_button.click()
    assert actor.prop.style.lower() == "wireframe" and w.wireframe
    assert w.top_bar.wireframe_button.dot_color() == w._theme.accent_secondary
    w.top_bar.wireframe_button.click()
    assert actor.prop.style.lower() == "surface"
    assert w.top_bar.wireframe_button.dot_color() == w._theme.muted_text


def test_disabled_actions_keep_style_cursor_and_tooltip(make_window) -> None:
    from PySide6.QtWidgets import QApplication

    w = make_window()
    sheet = QApplication.instance().styleSheet()
    t = w._theme
    assert "QPushButton#runBtn:disabled" in sheet and "QPushButton#meshBtn:disabled" in sheet
    assert t.disabled_text in sheet  # reduced-contrast text
    for button, phase in ((w.top_bar.mesh_button, "Save the project"), (w.top_bar.run_button, "Save the project")):
        assert not button.isEnabled()
        assert button.cursor().shape() == Qt.CursorShape.ForbiddenCursor
        assert phase in button.toolTip()
        assert button.graphicsEffect() is None  # drawn by the stylesheet, not by opacity


def test_status_line_shows_selection(make_window) -> None:
    w = make_window()
    w.tree.setCurrentItem(w._items[("part", 0)])
    assert w._selection_label.text() == "Active selection: Part 1"


def test_status_message_and_selection_never_overlap(make_window) -> None:
    """docs/QUESTIONS.md item 58: the selection is a permanent widget on the right; temporary
    messages are drawn on the left, in the space QStatusBar leaves before permanent widgets."""
    from PySide6.QtWidgets import QApplication

    w = make_window()
    bar, label = w.statusBar(), w._selection_label
    w.tree.setCurrentItem(w._items[("part", 0)] if ("part", 0) in w._items else w._items[("geometry", None)])
    w.show_message("Results at time 60 and a rather long temporary message")
    QApplication.processEvents()
    assert label.isVisible() and bar.currentMessage().startswith("Results at time 60")
    assert label.text().startswith("Active selection")
    # permanent widgets are laid out at the right end of the bar
    assert label.geometry().right() >= bar.width() - 2 * bar.layout().contentsMargins().right() - 8
    assert label.geometry().left() > 0
    # Qt removes normal (non-permanent) widgets from view while a message shows; none are left
    from PySide6.QtWidgets import QWidget

    normal = [c for c in bar.findChildren(QWidget) if c.isVisible() and c is not label
              and c.parent() is not None and c.geometry().intersects(label.geometry()) and c.isWidgetType()
              and c.objectName() != "qt_statusbar_sizegrip" and c is not bar]
    assert normal == []
