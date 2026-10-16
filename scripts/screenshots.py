"""Render window screenshots into /tmp/vortexcfd_shots/.

Run on the real display (WSLg) so the OpenGL viewer renders:
    .venv/bin/python scripts/screenshots.py
Offscreen (QT_QPA_PLATFORM=offscreen) works only for the tree/panels; the viewer stays empty.
"""

import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

OUT = Path("/tmp/vortexcfd_shots")


def main() -> int:
    # Never touch the user's real settings: redirect QSettings to a temp folder first.
    tmp = tempfile.mkdtemp(prefix="vortexcfd_settings_")
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
            QSettings.setPath(fmt, scope, tmp)

    from vortexcfd.core.model import Part
    from vortexcfd.core.project import Project
    from vortexcfd.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    project = Project.new("Wing study")
    for name, units in (("Wing", "mm"), ("Fuselage", "m"), ("Tail", "cm")):
        project.add_part(Part(name=name, source_file=f"{name.lower()}.stl", units=units))

    window = MainWindow(project, with_viewer=True)  # placeholder viewer shows a sphere
    window.resize(1400, 850)
    window.show()
    OUT.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    def shot(name: str) -> None:
        window.viewer.render()
        for _ in range(5):
            app.processEvents()
        path = OUT / name
        window.grab().save(str(path))
        paths.append(path)
        plotter_path = OUT / f"plotter_{name}"
        window.plotter.screenshot(str(plotter_path))
        paths.append(plotter_path)

    window.set_point_size(11)
    window.tree.setCurrentItem(window.tree.topLevelItem(0).child(0).child(1))
    shot("font11.png")
    window.set_point_size(14)
    shot("font14.png")
    for p in paths:
        print(p)
    sys.stdout.flush()
    # Skip teardown: closing the OpenGL viewer can hang on WSLg/Mesa; the PNGs are saved.
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
