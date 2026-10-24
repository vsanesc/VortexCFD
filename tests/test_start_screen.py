"""Start state, Start dialog, recent projects, New simulation and presets in the window (D-077).

Every modal dialog is a fake (tests/fakes.py); the dialog widgets themselves are driven without exec.
"""

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.presets import BUILTIN_PRESETS, Preset, PresetStore, preset_description, preset_summary
from vortexcfd.core.project import Project, ProjectFolderError, check_new_project_folder, validate_project_name
from vortexcfd.foam.parallel import recommended_cores
from vortexcfd.gui.main_window import NO_PROJECT, MainWindow, start_window
from vortexcfd.gui.recent import MAX_RECENT, RecentProjects
from vortexcfd.gui.settings_store import presets_dir
from vortexcfd.gui.start_dialogs import (
    NAME_TOOLTIP,
    ROLE_DATE,
    ROLE_FOLDER,
    ManagePresetsDialog,
    NewSimulationDialog,
    NewSimulationSpec,
    StartDialog,
    default_cores,
    default_project_name,
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
    assert menus == {"File": True, "Edit": False, "View": False, "Solution": False, "Help": True}
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


def test_file_menu_reopens_the_flows(make_window, tmp_path: Path, allow_temporary_recent) -> None:
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


def test_recent_list_order_limit_and_removal(tmp_path: Path, allow_temporary_recent) -> None:
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


def test_start_screen_has_two_large_buttons_and_no_duplicates(qtbot: QtBot) -> None:
    dialog = StartDialog(RecentProjects())
    qtbot.addWidget(dialog)
    assert dialog.pages.currentIndex() == 0
    assert dialog.new_button.accessibleName() == "New simulation"
    assert dialog.open_button.accessibleName() == "Open project"
    assert dialog.new_button.objectName() == dialog.open_button.objectName() == "startTile"
    texts = [b.text() or b.accessibleName() for b in dialog.findChildren(QPushButton)]
    assert texts.count("Open project") == 1 and not any("Remove" in t for t in texts)
    dialog.new_button.click()
    assert dialog.choice == ("new", None)


def test_open_panel_lists_existing_recent_projects(qtbot: QtBot, tmp_path: Path, allow_temporary_recent) -> None:
    good = Project.create(tmp_path, "Good").path
    other = Project.create(tmp_path, "Other").path
    gone = tmp_path / "Gone" / "Gone.vcfd"
    recent = RecentProjects()
    for path in (gone, other, good):
        recent.add(path)
    dialog = StartDialog(recent)
    qtbot.addWidget(dialog)
    dialog.open_button.click()
    assert dialog.pages.currentIndex() == 1 and dialog.choice is None
    assert dialog.items() == [("Good", str(good.parent)), ("Other", str(other.parent))]  # the missing one hidden
    assert dialog.list.item(0).data(ROLE_DATE)  # the last-opened date
    assert not dialog.empty_label.isVisibleTo(dialog)
    item = dialog.list.item(1)
    dialog.list.itemDoubleClicked.emit(item)
    assert dialog.choice == ("recent", other)


def test_browse_asks_the_window_for_a_file(qtbot: QtBot) -> None:
    dialog = StartDialog(RecentProjects())
    qtbot.addWidget(dialog)
    dialog.show_open_panel()
    assert dialog.items() == [] and dialog.empty_label.isVisibleTo(dialog)
    dialog.browse_button.click()
    assert dialog.choice == ("open", None)


def test_right_click_menu_opens_and_removes(qtbot: QtBot, tmp_path: Path, allow_temporary_recent) -> None:
    a = Project.create(tmp_path, "A").path
    b = Project.create(tmp_path, "B").path
    recent = RecentProjects()
    recent.add(a)
    recent.add(b)
    dialog = StartDialog(recent)
    qtbot.addWidget(dialog)
    dialog.show_open_panel()
    menu = dialog.context_menu(dialog.list.item(0))
    assert [act.text() for act in menu.actions()] == ["Open", "Remove from list"]
    menu.actions()[1].trigger()
    assert recent.paths() == [a] and dialog.items() == [("A", str(a.parent))]
    assert a.is_file() and b.is_file()  # only the list changes
    dialog.context_menu(dialog.list.item(0)).actions()[0].trigger()
    assert dialog.choice == ("recent", a)


# -- creating a project -------------------------------------------------------------------------


def test_create_makes_the_folder_layout_and_saves(make_window, tmp_path: Path, allow_temporary_recent) -> None:
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
    assert dialog.preset_texts() == ["External flow", "Empty", "2D airfoil", "Internal flow", "2D internal flow",
                                     "Big (user)"]
    # every entry has a one-line description; the selected preset's full description shows below the list
    first = dialog.preset_list.item(0)
    assert first.data(ROLE_FOLDER) == preset_summary(BUILTIN_PRESETS[0])
    assert dialog.description_label.text() == preset_description(BUILTIN_PRESETS[0])
    assert "Big" not in [dialog.preset_list.item(i).data(ROLE_FOLDER) for i in range(6)]
    assert dialog.preset_list.item(5).data(ROLE_FOLDER).startswith("User preset")
    assert dialog.cores_spin.maximum() == 8 and dialog.cores_spin.suffix() == " / 8"
    assert "physical cores" in dialog.cores_spin.toolTip() and "physical" not in dialog.cores_spin.text()
    expected = recommended_cores(BUILTIN_PRESETS[0].mesh.background_cells_target, 8)
    assert dialog.cores_spin.value() == expected == default_cores(BUILTIN_PRESETS[0], 8)
    assert dialog.parallel_check.isChecked() == (expected > 1)
    dialog.select_preset("Big")
    assert dialog.cores_spin.value() == recommended_cores(400_000, 8)
    assert dialog.description_label.text() == preset_description(store.presets()[0])
    dialog.parent_edit.setText(str(tmp_path))
    dialog.name_edit.setText("bad/name")
    assert not dialog.create_button.isEnabled()
    dialog.name_edit.setText("Good")
    assert dialog.create_button.isEnabled()
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
    assert not dialog.create_button.isEnabled() and "not empty" in dialog.name_edit.toolTip()


def test_new_simulation_validation_is_inline(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = NewSimulationDialog(PresetStore(tmp_path / "presets"), physical=4)
    qtbot.addWidget(dialog)
    dialog.parent_edit.setText(str(tmp_path))
    dialog.name_edit.setText("")
    assert dialog.name_edit.property("invalid") is True and dialog.name_edit.toolTip() == "Enter a project name."
    assert not dialog.parent_edit.property("invalid") and not dialog.create_button.isEnabled()
    # no footer message: no label anywhere repeats the reason
    assert not [lab for lab in dialog.findChildren(QLabel) if "Enter a project name" in lab.text()]
    dialog.name_edit.setText("Wing")
    assert not dialog.name_edit.property("invalid") and dialog.create_button.isEnabled()
    assert dialog.name_edit.toolTip() == NAME_TOOLTIP
    dialog.parent_edit.setText("")
    assert dialog.parent_edit.property("invalid") is True and not dialog.name_edit.property("invalid")
    assert "parent folder" in dialog.parent_edit.toolTip()


def test_new_simulation_layout(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = NewSimulationDialog(PresetStore(tmp_path / "presets"), physical=12)
    qtbot.addWidget(dialog)
    sections = [lab.text() for lab in dialog.findChildren(QLabel) if lab.objectName() == "dialogSection"]
    assert sections == ["PROJECT", "ANALYSIS", "SOLVER"]
    texts = [lab.text() for lab in dialog.findChildren(QLabel)]
    assert "Analysis type" not in texts  # the preset says it
    assert not dialog.findChildren(QComboBox)  # the presets are a list, the dimension a segmented row
    assert dialog.dimension == "3d" and dialog.dimension_buttons["3d"].isChecked()
    dialog.select_preset("2D airfoil")
    assert dialog.dimension == "2d"  # from the preset
    dialog.set_dimension("3d")
    dialog.parent_edit.setText(str(tmp_path))
    dialog.name_edit.setText("Wing")
    assert dialog.spec().dimension == "3d" and dialog.spec().preset.name == "2D airfoil"


def test_new_simulation_default_name_is_unique(qtbot: QtBot, tmp_path: Path) -> None:
    (tmp_path / "simulation_1").mkdir()
    other = tmp_path / "other"
    other.mkdir()
    dialog = NewSimulationDialog(PresetStore(tmp_path / "presets"), physical=4)
    qtbot.addWidget(dialog)
    dialog.parent_edit.setText(str(tmp_path))
    assert dialog.name_edit.text() == "simulation_2" == default_project_name(tmp_path)
    assert dialog.create_button.isEnabled()
    dialog.parent_edit.setText(str(other))  # the default follows the parent folder
    assert dialog.name_edit.text() == "simulation_1"
    dialog.name_edit.setText("Wing")
    dialog.parent_edit.setText(str(tmp_path))  # a name of the user's own is kept
    assert dialog.name_edit.text() == "Wing"


def test_new_simulation_disabled_create_says_why(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = NewSimulationDialog(PresetStore(tmp_path / "presets"), physical=4)
    qtbot.addWidget(dialog)
    dialog.parent_edit.setText(str(tmp_path))
    dialog.name_edit.setText("")
    assert not dialog.create_button.isEnabled() and dialog.create_button.toolTip() == "Enter a project name."
    dialog.name_edit.setText("bad/name")
    assert dialog.create_button.toolTip() == dialog.name_edit.toolTip() != ""
    dialog.name_edit.setText("Wing")
    assert dialog.create_button.isEnabled() and dialog.create_button.toolTip() == ""


def _geometry(widget, root):
    return widget.geometry().translated(widget.parentWidget().mapTo(root, widget.pos()) - widget.pos())


def test_new_simulation_sizes(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    store = PresetStore(tmp_path / "presets")
    dialog = NewSimulationDialog(store, physical=12)
    qtbot.addWidget(dialog)
    dialog.show()
    QApplication.processEvents()
    pl, desc = dialog.preset_list, dialog.description_label
    # the default size fits the content: every preset visible, the description as tall as its text
    assert pl.height() >= pl.count() * pl.sizeHintForRow(0)
    assert pl.verticalScrollBar().maximum() == 0
    fitted = desc.height()
    dialog._fit_description()
    assert desc.height() == fitted
    # the description directly below the list, wrapped and top-left aligned
    assert desc.wordWrap() and desc.alignment() == Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
    assert 0 <= _geometry(desc, dialog).top() - _geometry(pl, dialog).bottom() <= dialog.fontMetrics().height()
    # short: only the list gives way (it scrolls); the rest keeps its size and stays visible
    others = [dialog.dimension_buttons["3d"], dialog.cores_spin, dialog.create_button, dialog.name_edit]
    heights = {w: w.height() for w in others}
    dialog.resize(dialog.width(), dialog.minimumSizeHint().height())
    QApplication.processEvents()
    assert pl.height() < pl.count() * pl.sizeHintForRow(0) and pl.verticalScrollBar().maximum() > 0
    assert pl.height() >= 2 * pl.sizeHintForRow(0)
    assert {w: w.height() for w in others} == heights
    for w in [*others, desc]:
        assert dialog.rect().contains(_geometry(w, dialog)), w
    # tall: the list stops at its rows; the spare height goes above the buttons
    dialog.resize(dialog.width(), 3 * dialog.height())
    QApplication.processEvents()
    assert pl.height() <= pl.count() * pl.sizeHintForRow(0) + 2 * pl.frameWidth()
    assert desc.height() == fitted


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
