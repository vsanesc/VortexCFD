"""Tests for the properties panel."""

from pytestqt.qtbot import QtBot

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.gui.properties_panel import ALLOWED_UNITS, PropertiesPanel


def _panel(qtbot: QtBot) -> tuple[Project, PropertiesPanel]:
    project = Project.new("Demo")
    project.add_part(Part(name="Wing", source_file="wing.stl", units="mm"))
    panel = PropertiesPanel(project)
    qtbot.addWidget(panel)
    return project, panel


def test_units_combo_matches_model(qtbot: QtBot) -> None:
    _, panel = _panel(qtbot)
    items = [panel.units_combo.itemText(i) for i in range(panel.units_combo.count())]
    assert items == list(Part.model_fields["units"].annotation.__args__)
    assert tuple(items) == ALLOWED_UNITS


def test_part_fields_and_visibility(qtbot: QtBot) -> None:
    project, panel = _panel(qtbot)
    panel.show()
    panel.show_node("part", 0)
    assert panel.name_edit.text() == "Wing"
    assert panel.source_label.text() == "wing.stl"
    assert panel.units_combo.currentText() == "mm"
    assert panel.units_combo.isVisible()
    panel.show_node("geometry", None)
    assert not panel.name_edit.isVisible()
    assert panel.info_label.isVisible()
    assert not project.observer_errors


def test_refresh_does_not_commit(qtbot: QtBot) -> None:
    project, panel = _panel(qtbot)
    panel.show_node("part", 0)
    steps = len(project._undo)
    panel.refresh()
    assert len(project._undo) == steps


def test_units_edit_is_one_undo_step(qtbot: QtBot) -> None:
    project, panel = _panel(qtbot)
    panel.show_node("part", 0)
    panel.units_combo.setCurrentText("cm")
    assert project.sim.geometry.parts[0].units == "cm"
    project.undo()
    assert project.sim.geometry.parts[0].units == "mm"


def test_invalid_name_reverts_and_emits(qtbot: QtBot) -> None:
    project, panel = _panel(qtbot)
    project.add_part(Part(name="Other", source_file="", units="m"))
    panel.show_node("part", 0)
    messages: list[str] = []
    panel.message.connect(messages.append)
    panel.name_edit.setText("Other")
    panel.name_edit.editingFinished.emit()
    assert panel.name_edit.text() == "Wing"
    assert project.sim.geometry.parts[0].name == "Wing"
    assert messages and "Other" in messages[0]
    panel.name_edit.setText("   ")
    panel.name_edit.editingFinished.emit()
    assert panel.name_edit.text() == "Wing"
    assert len(messages) == 2
    assert not project.observer_errors
