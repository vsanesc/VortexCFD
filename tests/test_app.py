"""Tests for the VortexCFD main window application."""

from pyvistaqt import QtInteractor
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.project import Project
from vortexcfd.gui.main_window import MainWindow


def test_main_window_creates_viewer(qtbot: QtBot) -> None:
    """With with_viewer=True the placeholder 3D viewer is created next to the tree."""
    project = Project.new("Demo")
    window = MainWindow(project, dialogs=FakeDialogs(discard="discard"))
    qtbot.addWidget(window)
    window.show()

    assert isinstance(window.viewer, QtInteractor)
    assert window.viewer.isVisible()
    root = window.tree.topLevelItem(0)
    assert [root.child(i).text(0) for i in range(root.childCount())] == [
        "Geometry", "Mesh", "Physics", "Solvers", "Reports",
    ]
    assert not project.observer_errors
    window.close()
