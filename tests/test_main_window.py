"""Tests for the main window bound to a Project (no real modal dialogs)."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.gui.main_window import MainWindow


@pytest.fixture
def make_window(qtbot: QtBot):
    def make(project: Project | None = None, **dialog_args) -> tuple[MainWindow, FakeDialogs]:
        dialogs = FakeDialogs(**dialog_args)
        window = MainWindow(project or Project.new("Demo"), dialogs, with_viewer=False)
        qtbot.addWidget(window)
        window.show()
        return window, dialogs

    return make


def _part_items(window: MainWindow):
    geometry = window.tree.topLevelItem(0).child(0)
    return [geometry.child(i) for i in range(geometry.childCount())]


def _select_part(window: MainWindow, index: int) -> None:
    window.tree.setCurrentItem(_part_items(window)[index])


def test_title_follows_dirty(make_window, tmp_path: Path) -> None:
    window, dialogs = make_window(save_path=tmp_path / "demo.json")
    assert window.windowTitle() == "Demo[*] - Untitled - VortexCFD"
    assert window.isWindowModified()
    window.save()
    assert window.windowTitle() == "Demo[*] - demo.json - VortexCFD"
    assert not window.isWindowModified()
    window.act_add_part.trigger()
    assert window.isWindowModified()
    window.project.undo()
    assert not window.isWindowModified()
    assert not window.project.observer_errors


def test_tree_updates_after_add_part(make_window) -> None:
    window, _ = make_window()
    window.act_add_part.trigger()
    window.act_add_part.trigger()
    assert [i.text(0) for i in _part_items(window)] == ["Part 1", "Part 2"]
    assert window._parts_label.text() == "Parts: 2"
    window.project.remove_part(0)
    window.act_add_part.trigger()
    assert [i.text(0) for i in _part_items(window)] == ["Part 2", "Part 1"]
    assert not window.project.observer_errors


def test_selecting_part_shows_fields(make_window) -> None:
    project = Project.new("Demo")
    project.add_part(Part(name="Wing", source_file="wing.stl", units="cm"))
    window, _ = make_window(project)
    _select_part(window, 0)
    panel = window.properties
    assert panel.name_edit.text() == "Wing"
    assert panel.source_label.text() == "wing.stl"
    assert panel.units_combo.currentText() == "cm"
    assert window.act_remove_part.isEnabled()


def test_name_edit_is_one_undo_step(make_window) -> None:
    project = Project.new("Demo")
    project.add_part(Part(name="Wing", source_file="", units="m"))
    window, _ = make_window(project)
    _select_part(window, 0)
    window.properties.name_edit.setText("Fuselage")
    window.properties.name_edit.editingFinished.emit()
    assert project.sim.geometry.parts[0].name == "Fuselage"
    assert _part_items(window)[0].text(0) == "Fuselage"
    assert window.act_undo.text() == "Undo Edit part 'Wing' (name)"
    window.act_undo.trigger()
    assert project.sim.geometry.parts[0].name == "Wing"
    assert window.properties.name_edit.text() == "Wing"
    assert not project.observer_errors


def test_invalid_name_reverts_with_status_message(make_window) -> None:
    window, _ = make_window()
    window.properties.name_edit.setText("  ")
    window.properties.name_edit.editingFinished.emit()
    assert window.properties.name_edit.text() == "Demo"
    assert "empty" in window.statusBar().currentMessage()
    assert window.project.sim.name == "Demo"
    assert not window.project.observer_errors


def test_undo_redo_actions_follow_labels(make_window) -> None:
    window, _ = make_window()
    assert not window.act_undo.isEnabled() and not window.act_redo.isEnabled()
    assert window.act_undo.text() == "Undo"
    window.act_add_part.trigger()
    assert window.act_undo.isEnabled()
    assert window.act_undo.text() == "Undo Add part 'Part 1'"
    window.act_undo.trigger()
    assert window.act_redo.isEnabled() and not window.act_undo.isEnabled()
    assert window.act_redo.text() == "Redo Add part 'Part 1'"
    window.act_redo.trigger()
    assert [i.text(0) for i in _part_items(window)] == ["Part 1"]
    assert not window.project.observer_errors


def test_remove_part_and_selection_fallback(make_window) -> None:
    window, _ = make_window()
    assert not window.act_remove_part.isEnabled()
    window.act_add_part.trigger()
    _select_part(window, 0)
    window.act_remove_part.trigger()
    assert _part_items(window) == []
    assert window.tree.currentItem() is window.tree.topLevelItem(0)
    assert not window.act_remove_part.isEnabled()
    assert not window.project.observer_errors


def test_save_as_writes_file(make_window, tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    window, _ = make_window(save_path=target)
    window.act_save_as.trigger()
    assert target.exists()
    assert not window.isWindowModified()
    assert Project.open(target).sim.name == "Demo"
    assert not window.project.observer_errors


def test_open_replaces_project(make_window, tmp_path: Path) -> None:
    other = Project.new("Other")
    other.add_part(Part(name="A", source_file="", units="m"))
    path = tmp_path / "other.json"
    other.save(path)
    window, dialogs = make_window(open_path=path, discard="discard")
    old = window.project
    window.act_open.trigger()
    assert window.project is not old
    assert window.windowTitle() == "Other[*] - other.json - VortexCFD"
    assert [i.text(0) for i in _part_items(window)] == ["A"]
    assert not window.isWindowModified()
    old.add_part(Part(name="X", source_file="", units="m"))  # old project is unsubscribed
    assert [i.text(0) for i in _part_items(window)] == ["A"]
    assert not window.project.observer_errors and not old.observer_errors


def test_open_failure_keeps_project(make_window, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    window, _ = make_window(open_path=bad)
    old = window.project
    window.act_open.trigger()
    assert window.project is old
    assert "Could not open" in window.statusBar().currentMessage()


def test_close_dirty_cancel_keeps_window(make_window) -> None:
    window, dialogs = make_window(discard="cancel")
    assert not window.close()
    assert window.isVisible()
    assert dialogs.confirm_calls == 1


def test_close_dirty_discard_closes(make_window) -> None:
    window, _ = make_window(discard="discard")
    assert window.close()
    assert not window.isVisible()


def test_close_dirty_save_writes_and_closes(make_window, tmp_path: Path) -> None:
    target = tmp_path / "saved.json"
    window, _ = make_window(discard="save", save_path=target)
    assert window.close()
    assert target.exists()


def test_close_save_cancelled_ignores_close(make_window) -> None:
    window, _ = make_window(discard="save", save_path=None)
    assert not window.close()
    assert window.isVisible()


def test_close_clean_does_not_ask(make_window, tmp_path: Path) -> None:
    project = Project.new("Demo")
    project.save(tmp_path / "p.json")
    window, dialogs = make_window(project)
    assert window.close()
    assert dialogs.confirm_calls == 0


def test_refresh_errors_surface_in_status_bar(make_window, monkeypatch) -> None:
    window, _ = make_window()

    def boom() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(window, "_refresh", boom)
    window.project.rename("Renamed")
    assert "boom" in window.statusBar().currentMessage()
    assert not window.project.observer_errors


def test_new_project_asks_when_dirty(make_window) -> None:
    window, dialogs = make_window(discard="cancel")
    window.act_new.trigger()
    assert window.project.sim.name == "Demo"
    dialogs.discard = "discard"
    window.act_new.trigger()
    assert window.project.sim.name == "Untitled"
