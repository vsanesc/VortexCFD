"""Main window with simulation tree and 3D viewer."""

import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)
import pyvista as pv
from pyvistaqt import QtInteractor


class MainWindow(QMainWindow):
    """Main window with a simulation tree panel and an embedded 3D viewer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CFD GUI")
        self.resize(1024, 768)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left panel: tree widget with placeholder nodes
        self.tree = QTreeWidget(splitter)
        self.tree.setHeaderLabel("Simulation Tree")
        placeholder_nodes = ["Geometry", "Mesh", "Physics", "Solvers", "Reports"]
        for name in placeholder_nodes:
            QTreeWidgetItem(self.tree, [name])

        # Right panel: embedded 3D viewer showing a sphere
        self.viewer = QtInteractor(splitter)
        self.plotter = self.viewer  # Alias for convenience
        sphere = pv.Sphere()
        self.viewer.add_mesh(sphere, color="lightblue", show_edges=True)
        self.viewer.reset_camera()

        splitter.addWidget(self.tree)
        splitter.addWidget(self.viewer)
        splitter.setSizes([250, 750])

        self.setCentralWidget(splitter)

    def closeEvent(self, event) -> None:
        """Ensure VTK interactor resources are cleanly closed on window close."""
        if hasattr(self, "viewer") and self.viewer is not None:
            self.viewer.close()
        super().closeEvent(event)


def main() -> int:
    """Application entry point."""
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
