"""Render window screenshots offscreen into /tmp/vortexcfd_shots/.

Run: QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/screenshots.py
"""

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

    window = MainWindow(project, with_viewer=False)
    window.resize(1400, 850)
    window.show()
    OUT.mkdir(parents=True, exist_ok=True)
    paths = []

    def shot(name: str) -> None:
        app.processEvents()
        path = OUT / name
        window.grab().save(str(path))
        paths.append(path)

    window.set_point_size(11)
    window.set_theme("dark")
    shot("dark.png")
    window.set_theme("light")
    shot("light.png")
    window.set_theme("dark")
    window.set_point_size(14)
    window.tree.setCurrentItem(window.tree.topLevelItem(0).child(0).child(1))
    shot("dark_font14_part.png")
    for p in paths:
        print(p)
    window.project.save = lambda *a, **k: None  # nothing to save; avoid the prompt on close
    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
