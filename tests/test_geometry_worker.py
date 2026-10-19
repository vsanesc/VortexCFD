"""Geometry jobs run off the GUI thread; their results are applied once on the GUI thread (D-073).

The slow operations are fakes that block on an event until the test releases them."""

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer

from tests import cad_corpus
from tests.geometry_corpus import sphere_with_holes, two_spheres
from tests.test_import import _fresh_cache, make_window, wait_geometry  # noqa: F401 (fixtures)
from vortexcfd.gui import geometry_worker
from vortexcfd.workflow import part_ops
from vortexcfd.gui.geometry_worker import GeometryWorker


class Gate:
    """Wraps a function: each call records its thread, then blocks until ``release``."""

    def __init__(self, function) -> None:
        self.function = function
        self.event = threading.Event()
        self.calls: list[str] = []

    def __call__(self, *args, **kwargs):
        self.calls.append(threading.current_thread().name)
        assert self.event.wait(30), "the test never released the operation"
        return self.function(*args, **kwargs)

    def release(self) -> None:
        self.event.set()


def _event_loop_runs(qtbot) -> None:
    """A timer fires: the GUI thread is processing events."""
    fired = []
    QTimer.singleShot(20, lambda: fired.append(True))
    qtbot.waitUntil(lambda: bool(fired), timeout=2000)


def test_worker_runs_off_the_gui_thread_and_reports_once(qtbot) -> None:
    worker = GeometryWorker()
    results, errors = [], []
    worker.finished.connect(lambda job, result: results.append((job, result)))
    worker.failed.connect(lambda job, exc: errors.append((job, exc)))
    gate = Gate(lambda: 42)
    job = worker.start("Fake job", gate)
    with pytest.raises(RuntimeError, match="Fake job is still running"):
        worker.start("Another", lambda: 0)
    _event_loop_runs(qtbot)
    assert results == [] and worker.is_running()
    gate.release()
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert results == [(job, 42)] and errors == [] and gate.calls == [f"geometry-{job}"]
    job2 = worker.start("Failing", lambda: 1 / 0)
    qtbot.waitUntil(lambda: bool(errors), timeout=5000)
    assert errors[0][0] == job2 and isinstance(errors[0][1], ZeroDivisionError) and len(results) == 1


def test_repair_runs_in_the_background_and_applies_once(make_window, tmp_path: Path, qtbot, monkeypatch) -> None:
    gate = Gate(part_ops.repair_part)
    monkeypatch.setattr(part_ops, "repair_part", gate)
    (tmp_path / "src").mkdir()
    sphere_with_holes().save(str(tmp_path / "src" / "ball.stl"))
    w = make_window(import_path=tmp_path / "src" / "ball.stl")
    w.act_import.trigger()
    wait_geometry(qtbot, w)
    undo_depth = len(w.project._undo)
    w.act_repair_part.trigger()
    # While the repair runs: the GUI thread processes events, the geometry actions are disabled.
    _event_loop_runs(qtbot)
    assert gate.calls and gate.calls[0].startswith("geometry-")
    assert w.geometry_busy and not w.act_repair_part.isEnabled() and not w.act_import.isEnabled()
    assert not w.properties.region_split.isEnabled()
    assert "Repairing 'ball'..." in w.statusBar().currentMessage()
    assert "Repairing 'ball'..." in w.console.text()
    w.act_repair_part.trigger()  # disabled action: ignored; a direct call is refused
    w.repair_selected_part()
    assert len(gate.calls) == 1
    assert w.project.sim.geometry.parts[0].source_file == "geometry/ball.stl"
    gate.release()
    wait_geometry(qtbot, w)
    assert len(w.project._undo) == undo_depth + 1  # applied once, one undoable step
    assert w.project.sim.geometry.parts[0].source_file == "geometry/ball_repaired.stl"
    assert len(w.dialogs.repair_reports) == 1
    assert w.act_repair_part.isEnabled() and w.act_import.isEnabled()


def test_a_result_for_a_changed_part_is_discarded(make_window, tmp_path: Path, qtbot, monkeypatch) -> None:
    gate = Gate(part_ops.repair_part)
    monkeypatch.setattr(part_ops, "repair_part", gate)
    (tmp_path / "src").mkdir()
    sphere_with_holes().save(str(tmp_path / "src" / "ball.stl"))
    w = make_window(import_path=tmp_path / "src" / "ball.stl")
    w.act_import.trigger()
    wait_geometry(qtbot, w)
    w.act_repair_part.trigger()
    w.project.update_part(0, units="mm")  # the part changes while the repair runs
    gate.release()
    wait_geometry(qtbot, w)
    assert w.project.sim.geometry.parts[0].source_file == "geometry/ball.stl"
    assert "changed during the repair: the result was discarded" in w.console.text()
    assert w.dialogs.repair_reports == []


def test_retessellation_runs_in_the_background(make_window, tmp_path: Path, qtbot, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    step = cad_corpus.cylinder_step(tmp_path / "src" / "rod.step")
    w = make_window(import_path=step)
    w.act_import.trigger()
    wait_geometry(qtbot, w)
    gate = Gate(part_ops.retessellate)
    monkeypatch.setattr(part_ops, "retessellate", gate)
    undo_depth = len(w.project._undo)
    p = w.properties
    p.cad_angular.setValue(5.0)
    p.cad_angular.editingFinished.emit()
    _event_loop_runs(qtbot)
    assert w.geometry_busy and not p.cad_linear.isEnabled() and "Tessellating 'rod'..." in w.console.text()
    assert w.project.sim.geometry.parts[0].cad.angular_deflection == 20.0
    gate.release()
    wait_geometry(qtbot, w)
    assert gate.calls and len(gate.calls) == 1
    assert w.project.sim.geometry.parts[0].cad.angular_deflection == 5.0
    assert len(w.project._undo) == undo_depth + 1 and p.cad_linear.isEnabled()


def test_cad_import_reads_and_tessellates_in_the_background(make_window, tmp_path: Path, qtbot, monkeypatch) -> None:
    gate = Gate(part_ops.cad_parts)
    monkeypatch.setattr(part_ops, "cad_parts", gate)
    (tmp_path / "src").mkdir()
    w = make_window(import_path=cad_corpus.named_box_step(tmp_path / "src" / "box.step"))
    w.act_import.trigger()
    qtbot.waitUntil(lambda: bool(gate.calls), timeout=10000)  # reading done, tessellating
    _event_loop_runs(qtbot)
    assert w.project.sim.geometry.parts == [] and "Tessellating box.step..." in w.console.text()
    gate.release()
    wait_geometry(qtbot, w)
    assert [p.name for p in w.project.sim.geometry.parts] == ["box"] and len(gate.calls) == 1
    assert w.project.undo_label == "Add part 'box'"


def test_self_intersection_check_runs_in_the_background(make_window, tmp_path: Path, qtbot, monkeypatch) -> None:
    gate = Gate(geometry_worker.surface_report)
    monkeypatch.setattr(geometry_worker, "surface_report", gate)
    (tmp_path / "src").mkdir()
    two_spheres().save(str(tmp_path / "src" / "spheres.stl"))
    w = make_window(import_path=tmp_path / "src" / "spheres.stl")
    w.act_import.trigger()
    assert w.project.sim.geometry.parts[0].name == "spheres"  # imported at once
    _event_loop_runs(qtbot)
    value = w.properties.check_values["intersections"]
    assert value.text() == "checking…" and w.properties.check_values["watertight"].text() == "yes"
    assert gate.calls == ["intersections"]
    gate.release()
    wait_geometry(qtbot, w)
    assert value.text() == "172" and w.scene.defect_actor is not None and len(gate.calls) == 1
    assert w.console.text().count("172 self-intersecting triangles") == 1
