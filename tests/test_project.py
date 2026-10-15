"""Tests for the Qt-free Project document (headless, no OpenFOAM)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from cfdgui.core.model import Part
from cfdgui.core.project import Project
from cfdgui.core.project_io import ProjectFileError


def make_part(name: str = "wing", source: str = "wing.stl", units: str = "m") -> Part:
    return Part(name=name, source_file=source, units=units)  # type: ignore[arg-type]


def part_names(project: Project) -> list[str]:
    return [p.name for p in project.sim.geometry.parts]


def test_new_project_is_dirty_without_path() -> None:
    project = Project.new("Demo")
    assert project.sim.name == "Demo"
    assert project.path is None
    assert project.dirty is True
    assert not project.can_undo and not project.can_redo
    assert project.undo_label is None and project.redo_label is None


def test_edit_undo_redo_round_trip_with_labels() -> None:
    project = Project.new("Demo")
    project.add_part(make_part("wing"))
    project.rename("Renamed")
    assert project.sim.name == "Renamed"
    assert project.undo_label == "Rename simulation to 'Renamed'"
    assert project.redo_label is None

    assert project.undo() is True
    assert project.sim.name == "Demo" and part_names(project) == ["wing"]
    assert project.undo_label == "Add part 'wing'"
    assert project.redo_label == "Rename simulation to 'Renamed'"

    assert project.undo() is True
    assert part_names(project) == []
    assert project.undo_label is None and project.can_undo is False

    assert project.redo() is True and project.redo() is True
    assert project.sim.name == "Renamed" and part_names(project) == ["wing"]
    assert project.can_redo is False
    assert project.undo() and project.undo() and project.undo() is False
    assert project.redo() and project.redo() and project.redo() is False


def test_new_edit_clears_redo() -> None:
    project = Project.new("Demo")
    project.rename("A")
    project.undo()
    assert project.can_redo
    project.rename("B")
    assert project.can_redo is False and project.redo_label is None
    assert project.redo() is False


def test_undo_back_to_saved_state_is_clean(tmp_path: Path) -> None:
    project = Project.new("Demo")
    project.save(tmp_path / "p.json")
    assert project.dirty is False
    project.rename("Other")
    assert project.dirty is True
    project.undo()
    assert project.dirty is False
    project.redo()
    assert project.dirty is True


def test_invalid_units_rejected_without_side_effects(tmp_path: Path) -> None:
    project = Project.new("Demo")
    project.add_part(make_part("wing"))
    project.save(tmp_path / "p.json")
    before = project.sim.model_copy(deep=True)

    with pytest.raises(ValidationError):
        project.update_part(0, units="parsec")
    with pytest.raises(ValidationError):
        project.update_part(0, bogus_field=1)

    assert project.sim == before
    assert project.dirty is False
    assert project.undo_label == "Add part 'wing'"  # history unchanged


def test_duplicate_and_empty_names_rejected() -> None:
    project = Project.new("Demo")
    project.add_part(make_part("wing"))
    project.add_part(make_part("tail", "tail.stl"))
    depth_marker = project.undo_label

    with pytest.raises(ValueError, match="already exists"):
        project.add_part(make_part("wing", "other.stl"))
    with pytest.raises(ValueError, match="already exists"):
        project.update_part(1, name="wing")
    with pytest.raises(ValueError, match="empty"):
        project.add_part(make_part("   "))
    with pytest.raises(ValueError, match="empty"):
        project.update_part(0, name="")
    with pytest.raises(ValueError, match="empty"):
        project.rename("  \t")
    with pytest.raises(ValueError, match="empty"):
        Project.new(" ")

    assert part_names(project) == ["wing", "tail"]
    assert project.sim.name == "Demo"
    assert project.undo_label == depth_marker

    project.update_part(0, name="wing")  # keeping its own name is not a duplicate (no-op)
    assert project.undo_label == depth_marker


def test_names_are_stripped() -> None:
    project = Project.new("  Demo  ")
    assert project.sim.name == "Demo"
    project.add_part(make_part("  wing "))
    assert part_names(project) == ["wing"]


def test_index_out_of_range() -> None:
    project = Project.new("Demo")
    project.add_part(make_part("wing"))
    for index in (1, -1, 99):
        with pytest.raises(IndexError):
            project.remove_part(index)
        with pytest.raises(IndexError):
            project.update_part(index, units="mm")
    assert part_names(project) == ["wing"]
    assert project.undo_label == "Add part 'wing'"


def test_update_and_remove_part() -> None:
    project = Project.new("Demo")
    project.add_part(make_part("wing"))
    project.update_part(0, units="mm", source_file="new.stl")
    part = project.sim.geometry.parts[0]
    assert (part.units, part.source_file) == ("mm", "new.stl")
    assert project.undo_label == "Edit part 'wing' (units, source_file)"
    project.remove_part(0)
    assert part_names(project) == []
    assert project.undo_label == "Remove part 'wing'"
    project.undo()
    assert project.sim.geometry.parts[0].units == "mm"


def test_noop_edit_creates_no_history_and_no_notification(tmp_path: Path) -> None:
    project = Project.new("Demo")
    project.add_part(make_part("wing"))
    project.save(tmp_path / "p.json")
    calls: list[Project] = []
    project.subscribe(calls.append)

    project.rename("Demo")
    project.update_part(0, units="m")
    assert project.undo_label == "Add part 'wing'"
    assert project.dirty is False
    assert calls == []


def test_depth_limit_drops_oldest_entry() -> None:
    project = Project.new("v0", max_depth=3)
    for i in range(1, 6):
        project.rename(f"v{i}")
    undone = 0
    while project.undo():
        undone += 1
    assert undone == 3
    assert project.sim.name == "v2"  # v0 and v1 fell off the history
    with pytest.raises(ValueError):
        Project.new("x", max_depth=0)


def test_default_depth_is_100() -> None:
    project = Project.new("v0")
    for i in range(1, 121):
        project.rename(f"v{i}")
    undone = 0
    while project.undo():
        undone += 1
    assert undone == 100
    assert project.sim.name == "v20"


def test_save_open_round_trip_preserves_parts(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "p.json"
    project = Project.new("Demo")
    project.add_part(make_part("wing", "geo/wing.stl", "mm"))
    project.add_part(make_part("tail", "tail.stl", "in"))
    project.save(path)
    assert project.path == path and project.dirty is False

    reopened = Project.open(path)
    assert reopened.sim == project.sim
    assert reopened.path == path and reopened.dirty is False
    assert not reopened.can_undo
    assert [(p.name, p.source_file, p.units) for p in reopened.sim.geometry.parts] == [
        ("wing", "geo/wing.stl", "mm"),
        ("tail", "tail.stl", "in"),
    ]


def test_save_without_path_raises_and_save_uses_stored_path(tmp_path: Path) -> None:
    project = Project.new("Demo")
    with pytest.raises(ValueError, match="no path"):
        project.save()
    assert project.dirty is True

    path = tmp_path / "p.json"
    project.save(path)
    project.rename("Changed")
    project.save()  # uses the stored path
    assert Project.open(path).sim.name == "Changed"
    assert project.dirty is False


def test_open_missing_file_propagates_project_file_error(tmp_path: Path) -> None:
    with pytest.raises(ProjectFileError):
        Project.open(tmp_path / "missing.json")


def test_observers_called_once_per_change(tmp_path: Path) -> None:
    project = Project.new("Demo")
    seen: list[tuple[str, bool]] = []
    project.subscribe(lambda p: seen.append((p.sim.name, p.dirty)))

    project.rename("A")
    assert seen == [("A", True)]
    project.undo()
    project.redo()
    assert len(seen) == 3
    project.save(tmp_path / "p.json")
    assert seen[-1] == ("A", False) and len(seen) == 4


def test_failing_observer_does_not_stop_others_or_corrupt_state() -> None:
    project = Project.new("Demo")
    received: list[str] = []

    def boom(_: Project) -> None:
        raise RuntimeError("observer failed")

    project.subscribe(boom)
    project.subscribe(lambda p: received.append(p.sim.name))

    project.rename("A")
    assert received == ["A"]
    assert project.sim.name == "A" and project.undo_label == "Rename simulation to 'A'"
    assert len(project.observer_errors) == 1
    assert str(project.observer_errors[0]) == "observer failed"

    for i in range(30):
        project.rename(f"n{i}")
    assert len(project.observer_errors) == 20  # only the last 20 are kept


def test_unsubscribe() -> None:
    project = Project.new("Demo")
    calls: list[int] = []
    unsubscribe = project.subscribe(lambda p: calls.append(1))
    project.rename("A")
    unsubscribe()
    unsubscribe()  # idempotent
    project.rename("B")
    assert calls == [1]


def test_resolve_part_path(tmp_path: Path) -> None:
    project = Project.new("Demo")
    part = make_part("wing", "geo/wing.stl")
    with pytest.raises(ValueError, match="not been saved"):
        project.resolve_part_path(part)
    project.save(tmp_path / "proj" / "p.json")
    assert project.resolve_part_path(part) == tmp_path / "proj" / "geo" / "wing.stl"
    absolute = make_part("abs", str(tmp_path / "elsewhere.stl"))
    assert project.resolve_part_path(absolute) == tmp_path / "elsewhere.stl"


def test_mutating_returned_sim_changes_nothing(tmp_path: Path) -> None:
    """The object returned by sim is a copy: state, dirty and history are unaffected."""
    project = Project.new("Demo")
    project.add_part(make_part("wing"))
    project.rename("A")
    project.save(tmp_path / "p.json")
    calls: list[Project] = []
    project.subscribe(calls.append)

    sim = project.sim
    sim.name = "tampered"
    sim.geometry.parts[0].units = "mm"
    sim.geometry.parts.append(make_part("extra", "x.stl"))

    assert project.sim.name == "A"
    assert [(p.name, p.units) for p in project.sim.geometry.parts] == [("wing", "m")]
    assert project.dirty is False
    assert project.undo_label == "Rename simulation to 'A'"
    assert project.can_redo is False
    assert calls == []
    project.undo()
    assert project.sim.name == "Demo"


def test_sim_reads_are_equal_but_distinct_objects() -> None:
    project = Project.new("Demo")
    project.add_part(make_part("wing"))
    first, second = project.sim, project.sim
    assert first == second
    assert first is not second
    assert first.geometry.parts[0] is not second.geometry.parts[0]
