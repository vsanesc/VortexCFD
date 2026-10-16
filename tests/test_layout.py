"""Tests for the reference layout: sidebar, stage/view pills, property cards."""

import pytest
from PySide6.QtCore import QPoint, Qt
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.gui.main_window import MainWindow


@pytest.fixture
def make_window(qtbot: QtBot):
    made: list[MainWindow] = []

    def make(with_viewer: bool = False, parts: int = 2) -> MainWindow:
        project = Project.new("Demo")
        for i in range(parts):
            project.add_part(Part(name=f"Part {i + 1}", source_file=f"p{i}.stl", units="m"))
        w = MainWindow(project, FakeDialogs(), with_viewer=with_viewer)
        qtbot.addWidget(w)
        w.show()
        made.append(w)
        return w

    yield make
    for w in made:
        assert not w.project.observer_errors
        w.project.save = lambda *a, **k: None
        w.close()


def _section(window: MainWindow, kind: str):
    return window._items[(kind, None)]


def test_stage_buttons_select_sections(make_window) -> None:
    window = make_window()
    names = {"Geometry": "geometry", "Mesh": "mesh", "Physics": "physics",
             "Solve": "solvers", "Results": "reports"}
    buttons = {b.text(): b for b in window.stage_pill.buttons}
    assert list(buttons) == list(names)
    for text, kind in names.items():
        buttons[text].click()
        assert window.tree.currentItem() is _section(window, kind)
        assert buttons[text].isChecked() and window.stage_pill.stage() == kind


def test_tree_selection_updates_stage(make_window) -> None:
    window = make_window()
    window.tree.setCurrentItem(_section(window, "physics"))
    assert window.stage_pill.stage() == "physics"
    window.tree.setCurrentItem(window._items[("part", 0)])
    assert window.stage_pill.stage() == "geometry"
    window.tree.setCurrentItem(_section(window, "reports"))
    window._select_root()
    assert window._selection == ("root", None)
    assert window.stage_pill.stage() == "reports"  # root keeps the previous stage


def test_header_name_selects_root_and_shows_name_field(make_window) -> None:
    window = make_window()
    window.tree.setCurrentItem(window._items[("part", 1)])
    window.header.name_button.click()
    assert window._selection == ("root", None)
    assert window.properties.name_edit.text() == "Demo"
    assert not window.properties.card_source.isVisible()


def test_root_row_is_hidden_sections_are_top_level_rows(make_window) -> None:
    window = make_window()
    root_index = window.tree.rootIndex()
    assert window.tree.model().data(root_index) == "Demo"
    assert window.tree.model().rowCount(root_index) == 5


def test_search_filters_and_restores(make_window) -> None:
    window = make_window()
    window.tree.setCurrentItem(window._items[("part", 0)])
    window.search.setText("part 2")
    assert window._items[("part", 0)].isHidden()
    assert not window._items[("part", 1)].isHidden()
    assert not _section(window, "geometry").isHidden()  # parent of a match
    assert _section(window, "mesh").isHidden()
    assert window._selection == ("part", 0)  # selection preserved
    window.search.setText("MESH")
    assert not _section(window, "mesh").isHidden()
    window.search.setText("")
    assert all(not i.isHidden() for i in window._items.values())
    window.act_add_part.trigger()
    window.search.setText("part 3")
    assert not window._items[("part", 2)].isHidden() and window._items[("part", 0)].isHidden()


def test_ctrl_b_hides_and_restores_sidebars(make_window, qtbot: QtBot) -> None:
    window = make_window()
    qtbot.wait(30)
    before = window._splitter.sizes()
    window.act_toggle_sidebars.trigger()
    assert window._left.isHidden() and window._right.isHidden()
    window.act_toggle_sidebars.trigger()
    qtbot.wait(30)
    assert window._splitter.sizes() == before
    # The header's collapse button does the same.
    window.header.collapse_button.click()
    assert window._left.isHidden()
    window.header.collapse_button.click()
    assert not window._left.isHidden()
    assert window.act_toggle_sidebars.shortcut().toString() == "Ctrl+B"


def test_header_menu_has_the_file_actions(make_window) -> None:
    window = make_window()
    actions = [a for a in window.header.menu.actions() if not a.isSeparator()]
    assert actions == [window.act_new, window.act_open, window.act_save, window.act_save_as]


def test_modified_dot_follows_dirty(make_window, tmp_path) -> None:
    window = make_window()
    assert not window.header.dirty_dot.isHidden()
    window.project.save(tmp_path / "p.json")
    assert window.header.dirty_dot.isHidden()


def test_card_collapse_hides_body_and_is_remembered(make_window) -> None:
    window = make_window()
    window.tree.setCurrentItem(window._items[("part", 0)])
    card = window.properties.card_source
    assert card.body.isVisible()
    card.header.clicked.emit()
    assert card.collapsed and not card.body.isVisible()
    window.tree.setCurrentItem(window._items[("part", 1)])
    assert card.collapsed  # kept per card title
    card.toggle()
    assert card.body.isVisible()


def test_property_cards_per_node_kind(make_window) -> None:
    window = make_window()
    p = window.properties
    window.tree.setCurrentItem(window._items[("part", 0)])
    assert p.card_general.isVisible() and p.card_source.isVisible()
    window.tree.setCurrentItem(_section(window, "mesh"))
    assert not p.card_general.isVisible() and not p.card_source.isVisible()
    assert p.info_label.isVisible() and p.info_label.text() == "No properties yet"
    window._select_root()
    assert p.card_general.isVisible() and not p.card_source.isVisible()


def test_view_buttons_disabled_without_viewer(make_window) -> None:
    window = make_window(with_viewer=False)
    assert not window.view_pill.isEnabled()
    assert [b.text() for b in window.view_pill.buttons] == ["Fit", "Iso", "Front", "Top", "Right"]
    assert all(b.toolTip() for b in window.view_pill.buttons)


def test_view_buttons_call_plotter(make_window, monkeypatch) -> None:
    window = make_window(with_viewer=True)
    calls: list[str] = []
    for name in ("reset_camera", "view_isometric", "view_xz", "view_xy", "view_yz"):
        monkeypatch.setattr(window.viewer, name, lambda n=name, **k: calls.append(n))
    monkeypatch.setattr(window.viewer, "render", lambda *a, **k: None)
    assert window.view_pill.isEnabled()
    for button in window.view_pill.buttons:
        button.click()
    assert calls == ["reset_camera", "view_isometric", "view_xz", "view_xy", "view_yz"]


def test_chevron_click_toggles_without_selecting(make_window) -> None:
    window = make_window()
    window.tree.setCurrentItem(window._items[("part", 0)])
    item = _section(window, "geometry")
    rect = window.tree.visualItemRect(item)
    assert item.isExpanded()
    pos = QPoint(rect.left() + 2, rect.center().y())
    window.tree.viewport().update()
    from PySide6.QtTest import QTest
    QTest.mouseClick(window.tree.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert not item.isExpanded()
    assert window._selection == ("part", 0)
