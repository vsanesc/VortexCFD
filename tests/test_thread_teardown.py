"""Worker threads and windows ending (D-164, QUESTIONS 82): a closed ThreadGate never emits again and waits for an
emission in progress; a main window closes every worker's gate, the console and its viewer when it is closed or
deleted (also when the close was refused); the intersection checker's thread ends when shut down."""

import threading
import time
from pathlib import Path

import pyvista as pv
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.project import Project
from vortexcfd.gui.teardown import flush_deletions
from vortexcfd.gui.thread_gate import ThreadGate


class Emitter(QObject):
    ping = Signal(int)


def test_a_closed_gate_never_emits_and_close_waits_for_an_emission(qtbot: QtBot) -> None:
    source = Emitter()
    received = []
    source.ping.connect(received.append)
    gate = ThreadGate()
    in_emit, release = threading.Event(), threading.Event()

    class SlowSignal:  # an emission that is still going on when close() is called
        def emit(self, value):
            in_emit.set()
            release.wait(2)
            source.ping.emit(value)

    worker = threading.Thread(target=lambda: gate.emit(SlowSignal(), 1))
    worker.start()
    assert in_emit.wait(2)
    closer = threading.Thread(target=gate.close)
    closer.start()
    time.sleep(0.1)
    assert closer.is_alive()  # close waits for the emission in progress
    release.set()
    closer.join(2)
    worker.join(2)
    assert not gate.is_open
    assert gate.emit(source.ping, 2) is False  # never again
    qtbot.waitUntil(lambda: received == [1], timeout=2000)
    QApplication.processEvents()
    assert received == [1]


def test_a_gate_survives_a_deleted_owner() -> None:
    import shiboken6

    source = Emitter()
    gate = ThreadGate()
    shiboken6.delete(source)
    assert gate.emit(source.ping, 1) is False and not gate.is_open


def _window(qtbot: QtBot, tmp_path: Path, dialogs: FakeDialogs, with_viewer: bool = True):
    from vortexcfd.gui.main_window import MainWindow

    project = Project.create(tmp_path, "teardown")
    w = MainWindow(project, dialogs, with_viewer=with_viewer)
    w.show()
    return w


def _gates(w) -> list[ThreadGate]:
    return [worker.gate for worker in (w.mesh_worker, w.solver_worker, w.study_worker, w.sweep_worker,
                                       w.geometry_worker, w.intersections, w.overlaps, w.results_loader)]


def test_closing_the_window_ends_its_threads_signals_and_its_viewer(qtbot: QtBot, tmp_path: Path) -> None:
    w = _window(qtbot, tmp_path, FakeDialogs())
    viewer = w.viewer
    viewer.add_mesh(pv.Sphere())
    handler = w._console_handler
    assert all(g.is_open for g in _gates(w)) and handler.gate.is_open
    w.close()
    assert not any(g.is_open for g in _gates(w)) and not handler.gate.is_open
    assert viewer._closed  # the VTK render window and interactor finalized while the widget exists
    w.deleteLater()
    flush_deletions()


def test_a_window_deleted_after_a_refused_close_still_ends_them(qtbot: QtBot, tmp_path: Path) -> None:
    w = _window(qtbot, tmp_path, FakeDialogs(discard="cancel"))
    w.project.update_physics(nu=2e-5)  # unsaved: the close asks and is refused
    gates, viewer = _gates(w), w.viewer
    w.close()
    assert w.isVisible() and all(g.is_open for g in gates) and not viewer._closed
    w.deleteLater()  # deleted anyway (a test or a script)
    flush_deletions()
    assert not any(g.is_open for g in gates) and viewer._closed


def test_the_intersection_checker_stops(qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.geometry_worker import IntersectionChecker

    checker = IntersectionChecker()
    delivered = []
    checker.checked.connect(lambda path, units: delivered.append(path))
    surfaces = []
    for i in range(3):
        path = tmp_path / f"s{i}.stl"
        pv.Sphere(theta_resolution=40 + i, phi_resolution=40).save(str(path))
        surfaces.append(path)
    for path in surfaces:
        assert checker.request(path, "m")
    checker.shutdown()
    qtbot.waitUntil(lambda: checker._thread is None or not checker._thread.is_alive(), timeout=10000)
    QApplication.processEvents()
    assert not checker.busy() and len(delivered) == 0  # nothing reported after the shutdown


def _renderers() -> int:
    import gc

    import vtkmodules.vtkRenderingOpenGL2 as gl

    return sum(isinstance(o, gl.vtkOpenGLRenderer) for o in gc.get_objects())


def test_a_viewer_window_whose_vtk_objects_are_left_in_cycles(qtbot: QtBot, tmp_path: Path) -> None:
    """D-193, part 1 of 2: a viewer window with a mesh, ended as a test ends it (closed, deleted by the fixtures).
    Its renderers sit in reference cycles; the next test checks that the teardown freed them."""
    w = _window(qtbot, tmp_path, FakeDialogs())
    w.viewer.add_mesh(pv.Sphere())
    w.viewer.render()
    assert _renderers() > 0
    qtbot.addWidget(w)


def test_the_teardown_freed_the_previous_windows_vtk_objects_with_no_context_current() -> None:
    """D-193, part 2 of 2: tests/conftest.py's flush (gui/teardown.flush_deletions) freed the previous test's
    renderers before this test began (they used to survive into it and be freed by a later collection, possibly
    with another window's OpenGL context current), and left no OpenGL context current."""
    from PySide6.QtGui import QOpenGLContext

    assert _renderers() == 0 and QOpenGLContext.currentContext() is None
