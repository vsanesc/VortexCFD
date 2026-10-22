"""Start state, Start dialog, recent projects, New simulation and presets in the window (D-077).

Every modal dialog is a fake (tests/fakes.py); the dialog widgets themselves are driven without exec.
"""

import json
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.presets import BUILTIN_PRESETS, Preset, PresetStore
from vortexcfd.core.project import Project, ProjectFolderError, check_new_project_folder, validate_project_name
from vortexcfd.foam.parallel import recommended_cores
from vortexcfd.gui.main_window import NO_PROJECT, MainWindow, start_window
from vortexcfd.gui.recent import MAX_RECENT, RecentProjects
from vortexcfd.gui.settings_store import presets_dir
from vortexcfd.gui.start_dialogs import (
    NOT_FOUND,
    ManagePresetsDialog,
    NewSimulationDialog,
    NewSimulationSpec,
    StartDialog,
    default_cores,
)


@pytest.fixture
def make_window(qtbot: QtBot):
    made: list[MainWindow] = []

    def make(project=None, with_viewer=False, **dialogs) -> MainWindow:
        w = MainWindow(project, FakeDialogs(**dialogs), with_viewer=with_viewer)
        qtbot.addWidget(w)
        w.show()
        made.append(w)
        return w

    yield make
    for w in made:
        assert not w.project.observer_errors
        w.close()


def _spec(parent: Path, name="Wing", preset=None, cores=1) -> NewSimulationSpec:
    return NewSimulationSpec(name, parent, preset or BUILTIN_PRESETS[0], cores)


# -- start state ---------------------------------------------------------------------------------


def test_the_app_starts_with_no_project(make_window) -> None:
    w = make_window(with_viewer=True)
    assert not w.has_project and w.node_count() == 0 and w.tree.topLevelItemCount() == 0
    assert w._empty_message.actor.GetInput() == NO_PROJECT and w._empty_message.actor.GetVisibility()
    assert not w.properties.isVisible()
    assert w.windowTitle() == "VortexCFD"
    menus = {m.title().replace("&", ""): m.menuAction().isEnabled() for m in
             (a.menu() for a in w.menuBar().actions())}
    assert menus == {"File": True, "Edit": False, "View": False, "Help": True}
    assert w.act_new.isEnabled() and w.act_open.isEnabled() and w.act_about.isEnabled()
    for act in (w.act_import, w.act_save, w.act_save_as, w.act_save_preset):
        assert not act.isEnabled()
    assert w.solve_readiness() == NO_PROJECT
    w.act_about.trigger()
    assert w.dialogs.about_shown == 1


def test_start_window_opens_the_start_dialog_only_without_a_path(qtbot: QtBot, tmp_path: Path) -> None:
    dialogs = FakeDialogs()
    w = start_window([], dialogs)
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: dialogs.start_asked == 1)
    assert not w.has_project  # closing the dialog (None) leaves the empty window
    w.close()
    project = Project.create(tmp_path, "Direct")
    dialogs2 = FakeDialogs()
    w2 = start_window([str(project.path)], dialogs2)
    qtbot.addWidget(w2)
    qtbot.wait(50)
    assert dialogs2.start_asked == 0 and w2.has_project and w2.project.path == project.path
    assert w2.node_count() > 0 and w2.edit_menu.menuAction().isEnabled()
    w2.close()


def test_start_choices(make_window, tmp_path: Path) -> None:
    existing = Project.create(tmp_path, "Old")
    w = make_window()
    w.dialogs.start_choice = ("recent", existing.path)
    w.show_start()
    assert w.has_project and w.project.path == existing.path
    w2 = make_window()
    w2.dialogs.start_choice = ("new", None)
    w2.dialogs.new_simulation = _spec(tmp_path, "Brand")
    w2.show_start()
    assert w2.project.path == tmp_path / "Brand" / "Brand.vcfd"
    w3 = make_window(open_path=existing.path)
    w3.dialogs.start_choice = ("open", None)
    w3.show_start()
    assert w3.project.path == existing.path


def test_file_menu_reopens_the_flows(make_window, tmp_path: Path) -> None:
    w = make_window()
    w.act_new.trigger()  # the fake New simulation dialog is cancelled
    assert w.dialogs.new_asked == 1 and not w.has_project
    w.dialogs.new_simulation = _spec(tmp_path)
    w.act_new.trigger()
    assert w.has_project and w.edit_menu.menuAction().isEnabled() and w.act_import.isEnabled()
    w._fill_recent_menu()
    texts = [a.text() for a in w.recent_menu.actions()]
    assert texts[0] == str(tmp_path / "Wing" / "Wing.vcfd") and "Start screen..." in texts


# -- recent projects ----------------------------------------------------------------------------


def test_recent_list_order_limit_and_removal(tmp_path: Path) -> None:
    recent = RecentProjects()
    assert recent.paths() == []
    paths = [tmp_path / f"p{i}.vcfd" for i in range(MAX_RECENT + 3)]
    for path in paths:
        recent.add(path)
    assert recent.paths() == list(reversed(paths))[:MAX_RECENT]
    recent.add(paths[5])
    assert recent.paths()[0] == paths[5] and len(recent.paths()) == MAX_RECENT
    recent.remove(paths[5])
    assert paths[5] not in recent.paths()
    assert RecentProjects().paths() == recent.paths()  # stored in QSettings


def test_start_dialog_greys_missing_projects_and_removes_them(qtbot: QtBot, tmp_path: Path) -> None:
    good = Project.create(tmp_path, "Good").path
    gone = tmp_path / "Gone" / "Gone.vcfd"
    recent = RecentProjects()
    recent.add(gone)
    recent.add(good)
    dialog = StartDialog(recent)
    qtbot.addWidget(dialog)
    items = dialog.items()
    assert [enabled for _, enabled in items] == [True, False]
    assert NOT_FOUND in items[1][0] and NOT_FOUND not in items[0][0]
    dialog.select(1)
    assert not dialog.open_recent_button.isEnabled() and dialog.remove_button.isEnabled()
    dialog._open_item(dialog.list.currentItem())  # a missing file cannot be opened
    assert dialog.choice is None
    dialog.remove_selected()
    assert [enabled for _, enabled in dialog.items()] == [True] and recent.paths() == [good]
    dialog.select(0)
    dialog.open_recent_button.click()
    assert dialog.choice == ("recent", good)


# -- creating a project -------------------------------------------------------------------------


def test_create_makes_the_folder_layout_and_saves(make_window, tmp_path: Path) -> None:
    w = make_window()
    w.dialogs.new_simulation = _spec(tmp_path / "projects", "Wing study", BUILTIN_PRESETS[1], 3)
    w.new_project()
    folder = tmp_path / "projects" / "Wing study"
    assert sorted(p.name for p in folder.iterdir()) == ["Wing study.vcfd", "case", "geometry"]
    assert w.project.path == folder / "Wing study.vcfd" and not w.project.dirty
    data = json.loads((folder / "Wing study.vcfd").read_text())
    assert data["name"] == "Wing study" and data["analysis_type"] == "empty" and data["preset_name"] == "Empty"
    assert data["solvers"]["cores"] == 3 and data["domain"]["enabled"] is False
    assert RecentProjects().paths()[0] == folder / "Wing study.vcfd"
    # the cores are shown in the Solvers node
    w.tree.setCurrentItem(w._items[("solvers", None)])
    assert w.properties.group_fields["solvers"]["cores"].value() == 3


def test_create_refuses_a_non_empty_folder(make_window, tmp_path: Path) -> None:
    (tmp_path / "Busy").mkdir()
    (tmp_path / "Busy" / "notes.txt").write_text("mine")
    w = make_window()
    w.dialogs.new_simulation = _spec(tmp_path, "Busy")
    w.new_project()
    assert not w.has_project and (tmp_path / "Busy" / "notes.txt").read_text() == "mine"
    assert sorted(p.name for p in (tmp_path / "Busy").iterdir()) == ["notes.txt"]
    assert "already exists and is not empty" in w.dialogs.errors[-1][1]
    with pytest.raises(ProjectFolderError, match="not empty"):
        Project.create(tmp_path, "Busy")
    (tmp_path / "Empty").mkdir()
    assert Project.create(tmp_path, "Empty").path == tmp_path / "Empty" / "Empty.vcfd"  # an empty folder is used


@pytest.mark.parametrize("name", ["", "   ", "a/b", "..", ".hidden", "trailing.", "x" * 65, "wing?", "con:1",
                                  "back\\slash", "-dash"])
def test_invalid_project_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        validate_project_name(name)
    with pytest.raises(ValueError):
        Project.create(tmp_path, name)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["Wing", "wing_2", "Ala del ñandú", "run-3.b", "A"])
def test_valid_project_names(tmp_path: Path, name: str) -> None:
    assert check_new_project_folder(tmp_path, f"  {name} ") == tmp_path / name


def test_new_simulation_dialog(qtbot: QtBot, tmp_path: Path) -> None:
    store = PresetStore(tmp_path / "presets")
    store.save(Preset(name="Big", mesh={"background_cells_target": 400_000}))
    dialog = NewSimulationDialog(store, physical=8)
    qtbot.addWidget(dialog)
    assert [dialog.preset_combo.itemText(i) for i in range(dialog.preset_combo.count())] == [
        "External flow", "Empty", "2D airfoil", "Big (user)"]
    assert dialog.cores_spin.maximum() == 8
    expected = recommended_cores(BUILTIN_PRESETS[0].mesh.background_cells_target, 8)
    assert dialog.cores_spin.value() == expected == default_cores(BUILTIN_PRESETS[0], 8)
    assert dialog.parallel_check.isChecked() == (expected > 1)
    dialog.select_preset("Big")
    assert dialog.cores_spin.value() == recommended_cores(400_000, 8)
    dialog.parent_edit.setText(str(tmp_path))
    dialog.name_edit.setText("bad/name")
    assert not dialog.create_button.isEnabled() and dialog.error_label.text()
    dialog.name_edit.setText("Good")
    assert dialog.create_button.isEnabled() and dialog.error_label.text() == ""
    dialog.parallel_check.setChecked(False)
    spec = dialog.spec()
    assert (spec.name, spec.parent, spec.preset.name, spec.cores) == ("Good", tmp_path, "Big", 1)
    dialog.parallel_check.setChecked(True)
    dialog.cores_spin.setValue(5)
    dialog._create()
    assert dialog.result_spec.cores == 5
    (tmp_path / "Taken").mkdir()
    (tmp_path / "Taken" / "f").write_text("x")
    dialog.name_edit.setText("Taken")
    assert not dialog.create_button.isEnabled() and "not empty" in dialog.error_label.text()


# -- presets in the window ----------------------------------------------------------------------


def test_save_as_preset_and_overwrite_confirmation(make_window, tmp_path: Path) -> None:
    w = make_window(project=Project.create(tmp_path, "Src"))
    w.project.update_domain(shape="c_type", radius=6.0)
    w.project.update_physics(nu=1e-6)
    w.dialogs.preset_name = "Channel"
    w.act_save_preset.trigger()
    store = PresetStore(presets_dir())
    preset = store.find("Channel").preset
    assert (preset.domain.shape, preset.domain.radius) == ("c_type", 6.0)
    assert "physics" not in json.loads(store.find("Channel").path.read_text())
    w.project.update_domain(radius=8.0)
    w.dialogs.preset_overwrite = False
    w.act_save_preset.trigger()
    assert w.dialogs.preset_overwrite_asked == ["Channel"] and store.find("Channel").preset.domain.radius == 6.0
    w.dialogs.preset_overwrite = True
    w.act_save_preset.trigger()
    assert store.find("Channel").preset.domain.radius == 8.0
    w.dialogs.preset_name = "Empty"  # a built-in name is refused
    w.act_save_preset.trigger()
    assert "built-in" in w.statusBar().currentMessage()
    w.act_manage_presets.trigger()
    assert w.dialogs.presets_managed == 1


def test_manage_presets_dialog_renames_and_deletes(qtbot: QtBot, tmp_path: Path) -> None:
    store = PresetStore(tmp_path)
    store.save(Preset(name="Alpha"))
    store.save(Preset(name="Beta"))
    (tmp_path / "broken.json").write_text("{")
    answers = {"name": "Gamma", "confirm": True}
    dialog = ManagePresetsDialog(store, ask_name=lambda current: answers["name"],
                                 confirm=lambda text: answers["confirm"])
    qtbot.addWidget(dialog)
    texts = dialog.texts()
    assert texts[:2] == ["Alpha", "Beta"] and texts[2].startswith("broken.json (broken:")
    dialog.select("Alpha")
    dialog.rename_selected()
    assert [p.name for p in store.presets()] == ["Beta", "Gamma"]
    answers["name"] = "Beta"
    dialog.select("Gamma")
    dialog.rename_selected()
    assert "already exists" in dialog.error and [p.name for p in store.presets()] == ["Beta", "Gamma"]
    answers["confirm"] = False
    dialog.select("Beta")
    dialog.delete_selected()
    assert [p.name for p in store.presets()] == ["Beta", "Gamma"]
    answers["confirm"] = True
    dialog.delete_selected()
    assert [p.name for p in store.presets()] == ["Gamma"]
    dialog.select(dialog.texts()[-1])  # the broken file: deletable, not renamable
    assert not dialog.rename_button.isEnabled()
    dialog.delete_selected()
    assert not (tmp_path / "broken.json").exists() and dialog.texts() == ["Gamma"]


def test_presets_live_in_the_temporary_config_dir(isolated_config) -> None:
    assert presets_dir().is_relative_to(isolated_config)
