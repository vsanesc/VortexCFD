"""Tests for CFD GUI main window application."""

from pyvistaqt import QtInteractor
from pytestqt.qtbot import QtBot

from cfdgui.app import MainWindow


def test_main_window_structure(qtbot: QtBot) -> None:
    """Verify that MainWindow contains the 5 tree nodes and the 3D viewer widget."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    # Check tree widget exists and contains the expected placeholder nodes
    assert hasattr(window, "tree")
    expected_nodes = ["Geometry", "Mesh", "Physics", "Solvers", "Reports"]
    assert window.tree.topLevelItemCount() == len(expected_nodes)
    actual_nodes = [
        window.tree.topLevelItem(i).text(0)
        for i in range(window.tree.topLevelItemCount())
    ]
    assert actual_nodes == expected_nodes

    # Check embedded 3D viewer widget exists
    assert hasattr(window, "viewer")
    assert isinstance(window.viewer, QtInteractor)
    assert window.viewer.isVisible()

    window.close()
