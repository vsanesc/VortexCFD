"""Ending windows deliberately (D-164): for scripts that open windows offscreen, and the test fixtures.

Qt deletes a window's widgets with it. Before that, the window ends what outlives them: MainWindow closes its worker
threads' signals and its viewer's VTK render window (``MainWindow._release_background``, run by an accepted close
and again when the window is about to be deleted). ``dispose`` closes and deletes windows at once, instead of at an
unknown later point; ``finish`` closes every pyvista plotter still open and deletes every remaining top-level
widget while the application still exists, so nothing is torn down by the interpreter's exit in an arbitrary order.

A window's VTK objects (its renderers among them) sit in Python reference cycles, so they are freed by the cyclic
garbage collector, not when the window goes: left alone, that happens at an arbitrary allocation later, possibly
while another window's OpenGL context is current (a new viewer's initializeGL, or a QOpenGLWidget deleting its
framebuffer with its own context current). VTK then frees its GL objects against that context, which corrupts the
driver's heap and crashes at a distance (QUESTIONS 82; Part 2 of task 1.1-transient, D-193). ``flush_deletions``
therefore collects that garbage itself, before and after the deletions, with no OpenGL context current.
"""

import gc
import sys

from PySide6.QtCore import QEvent
from PySide6.QtGui import QOpenGLContext
from PySide6.QtWidgets import QApplication


def collect_garbage() -> int:
    """Free unreachable objects now (``gc.collect``) with no OpenGL context current, so a VTK object freed here
    can only release its GL objects into no context, never into another window's (D-193). Returns the count."""
    context = QOpenGLContext.currentContext()
    if context is not None:
        context.doneCurrent()
    return gc.collect()


def flush_deletions() -> None:
    """Run the deletions scheduled with deleteLater now (an event loop would run them later), and free the garbage
    of earlier windows before and that of the deleted ones after, with no OpenGL context current (D-193)."""
    app = QApplication.instance()
    if app is None:
        return
    collect_garbage()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    collect_garbage()


def close_plotters() -> None:
    """Close (finalize) every pyvista plotter still open, if pyvista is loaded."""
    plotting = sys.modules.get("pyvista.plotting.plotter")
    if plotting is not None:
        plotting.close_all()


def dispose(*widgets) -> None:
    """Close the widgets and delete them now."""
    import shiboken6

    for widget in widgets:
        if widget is not None and shiboken6.isValid(widget):
            widget.close()
            widget.deleteLater()
    flush_deletions()


def finish() -> None:
    """Before a script exits: every top-level widget closed and deleted, every plotter closed."""
    app = QApplication.instance()
    if app is None:
        return
    dispose(*QApplication.topLevelWidgets())
    close_plotters()
    flush_deletions()
