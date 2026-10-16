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
from vortexcfd.gui.theme import LAYOUT, metrics


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
    measured = {
        "left": w._left.width() / W,
        "monitors": w.monitors.width() / W,
        "console": w.console.height() / H,
        "top_bar": w.top_bar.height() / H,
        "tab_bar": w._tab_bar.height() / H,
        "tree_split": w._left_split.widget(0).height() / w._left.height(),
    }
    print({k: round(v, 3) for k, v in measured.items()})
    for key, value in measured.items():
        assert abs(value - getattr(LAYOUT, key)) <= tol, (key, value, getattr(LAYOUT, key))


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
    assert names == ["Geometry", "Continua", "Regions", "Solvers", "Reports & Monitors"]
    geometry = w._items[("geometry", None)]
    assert [geometry.child(i).text(0) for i in range(geometry.childCount())] == ["Parts"]
    parts = w._items[("parts", None)]
    assert [parts.child(i).text(0) for i in range(parts.childCount())] == ["Part 1", "Part 2", "Part 3"]
    continua = w._items[("continua", None)]
    assert [continua.child(i).text(0) for i in range(continua.childCount())] == ["Mesh", "Physics"]
    assert w._items[("none", None)].text(0) == "(none yet)"
    # Geometry, Parts, 3 parts, Continua, Mesh, Physics, Regions, Solvers, Reports = 11
    assert w.node_count() == 11 and w.node_badge.text() == "11 Nodes"
    w.act_add_part.trigger()
    assert w.node_badge.text() == "12 Nodes"


def test_placeholder_row_is_not_selectable(make_window) -> None:
    w = make_window()
    item = w._items[("none", None)]
    assert not item.flags() & Qt.ItemFlag.ItemIsSelectable


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
    w.tree.setCurrentItem(w._items[("mesh", None)])
    assert w.props_name.text() == "Mesh"
    assert not p._rows["name"].isVisible() and p.info_label.isVisible()
    w._select_root()
    assert p._rows["name"].isVisible() and not p._rows["source"].isVisible()


def test_future_actions_are_disabled_with_tooltips(make_window) -> None:
    w = make_window()
    assert not w.top_bar.mesh_button.isEnabled() and not w.top_bar.run_button.isEnabled()
    assert "Phase 5" in w.top_bar.mesh_button.toolTip()
    assert "Phase 4" in w.top_bar.run_button.toolTip()
    assert w.top_bar.mesh_button.text() == "Generate Mesh" and w.top_bar.run_button.text() == "Run Solver"


def test_top_bar_state_follows_dirty(make_window, tmp_path) -> None:
    w = make_window()
    assert w.top_bar.name_button.text() == "Untitled"
    assert w.top_bar.state_badge.text() == "Modified" and not w.top_bar.dirty_dot.isHidden()
    w.project.save(tmp_path / "proj.json")
    assert w.top_bar.name_button.text() == "proj.json"
    assert w.top_bar.state_badge.text() == "Saved" and w.top_bar.dirty_dot.isHidden()


def test_kpis_and_chart_are_empty_states(make_window) -> None:
    w = make_window()
    assert {k: v.text() for k, v in w.monitors.kpis.values.items()} == {
        "cl": "—", "cd": "—", "yplus": "—",
    }
    assert [t.text() for t in w.monitors.kpis.titles.values()] == [
        "LIFT COEFF (CL)", "DRAG COEFF (CD)", "MAX WALL Y+",
    ]
    assert w.monitors.chart.EMPTY_MESSAGE == "No solver run yet"
    assert w.monitors.chart.axis_labels() == ["1e0", "1e-1", "1e-2", "1e-3", "1e-4", "1e-5", "1e-6"]
    assert w.monitors.header.badge.text() == "Log10 Scale"


def test_console_receives_log_records_and_clears(make_window, tmp_path) -> None:
    w = make_window()
    assert "VortexCFD started" in w.console.text()
    logging.getLogger("vortexcfd.test").warning("something odd")
    assert "something odd" in w.console.text() and "WARNING" in w.console.text()
    w.project.save(tmp_path / "x.json")
    w.save()  # the window logs one INFO line per save
    assert "Saved" in w.console.text() and "x.json" in w.console.text()
    w.console.clear_button.click()
    assert w.console.text() == ""


def test_telemetry_has_real_values_only(make_window) -> None:
    w = make_window(parts=3)
    w.tree.setCurrentItem(w._items[("part", 1)])
    assert w.telemetry_text.splitlines() == [
        "VIEWPORT TELEMETRY", "Parts:    3", "Selected: Part 2", "Cells:    —",
    ]
    assert w.statusBar().children()


def test_view_buttons_disabled_without_viewer(make_window) -> None:
    w = make_window(with_viewer=False)
    assert not any(b.isEnabled() for b in w.top_bar.view_buttons.values())
    assert not w.top_bar.wireframe_button.isEnabled()


def test_view_buttons_call_plotter(make_window, monkeypatch) -> None:
    w = make_window(with_viewer=True)
    calls: list[str] = []
    for name in ("reset_camera", "view_isometric", "view_xz", "view_xy", "view_yz"):
        monkeypatch.setattr(w.viewer, name, lambda n=name, **k: calls.append(n))
    monkeypatch.setattr(w.viewer, "render", lambda *a, **k: None)
    texts = {b.text(): b for b in w.top_bar.view_buttons.values()}
    assert list(texts) == ["ISO", "XY", "XZ", "YZ", "Fit"]
    for button in texts.values():
        button.click()
    assert calls == ["view_isometric", "view_xy", "view_xz", "view_yz", "reset_camera"]


def test_wireframe_toggle_switches_representation(make_window) -> None:
    w = make_window(with_viewer=True)
    prop = w._mesh_actor.prop
    assert prop.style.lower() == "surface"
    w.top_bar.wireframe_button.click()
    assert prop.style.lower() == "wireframe"
    w.top_bar.wireframe_button.click()
    assert prop.style.lower() == "surface"


def test_status_line_shows_selection(make_window) -> None:
    w = make_window()
    w.tree.setCurrentItem(w._items[("part", 0)])
    assert w._selection_label.text() == "Active selection: Part 1"
