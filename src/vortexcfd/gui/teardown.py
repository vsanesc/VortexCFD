"""Ending windows deliberately (D-164): for scripts that open windows offscreen, and the test fixtures.

Qt deletes a window's widgets with it. Before that, the window ends what outlives them: MainWindow closes its worker
threads' signals and its viewer's VTK render window (``MainWindow._release_background``, run by an accepted close
and again when the window is about to be deleted). ``dispose`` closes and deletes windows at once, instead of at an
unknown later point; ``finish`` closes every pyvista plotter still open and deletes every remaining top-level
widget while the application still exists, so nothing is torn down by the interpreter's exit in an arbitrary order.
"""

import sys

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication


def flush_deletions() -> None:
    """Run the deletions scheduled with deleteLater now (an event loop would run them later)."""
    app = QApplication.instance()
    if app is None:
        return
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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
