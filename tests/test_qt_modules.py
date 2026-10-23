"""The Qt modules the app uses come from PySide6-Essentials only (D-139, QUESTIONS 213): a static scan of the sources,
a runtime check of sys.modules after the main window showed a project with results (offscreen; the real solved
fixture case of tests/test_scene_objects.py), a line plot's chart, an image export and a report, and the GUI's imports
with every other PySide6 module made unimportable (as in an install without PySide6-Addons, WebEngine and Pdf)."""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

from pytestqt.qtbot import QtBot

from tests.test_scene_objects import results_window  # noqa: F401 (fixture)
from vortexcfd.gui.image_export import render_image

SRC = Path(__file__).parent.parent / "src" / "vortexcfd"
# The Qt modules of the PySide6_Essentials 6.12.0 wheel (its RECORD); WebEngine, Pdf and the Addons are not here.
ESSENTIALS = {
    "QtConcurrent", "QtCore", "QtDBus", "QtDesigner", "QtGui", "QtHelp", "QtLabsStyleKit", "QtNetwork", "QtOpenGL",
    "QtOpenGLWidgets", "QtPrintSupport", "QtQml", "QtQmlFeatures", "QtQuick", "QtQuickControls2", "QtQuickTest",
    "QtQuickWidgets", "QtSql", "QtSvg", "QtSvgWidgets", "QtTest", "QtUiTools", "QtWidgets", "QtXml",
}
# qtpy (imported by pyvistaqt) tries `PySide6.QtDataVisualization` (Addons) inside suppress(ImportError) at import, for
# backward compatibility; without Addons it is skipped (test_the_gui_imports_without_the_other_modules).
OPTIONAL = {"QtDataVisualization"}


def _loaded_qt_modules() -> set[str]:
    return {name.split(".")[1] for name in sys.modules if name.startswith("PySide6.Qt")}


def test_the_sources_import_only_essentials_modules() -> None:
    found = set()
    for path in SRC.rglob("*.py"):
        found |= set(re.findall(r"\bPySide6\.(Qt\w+)", path.read_text()))
    assert found == {"QtCore", "QtGui", "QtWidgets"}


def test_the_running_app_loads_only_essentials_modules(results_window, qtbot: QtBot, tmp_path: Path) -> None:
    w = results_window()
    w.results_tab.click()
    qtbot.waitUntil(lambda: w.results_view.has_results, timeout=15000)
    w._select_node("results", None)
    w.properties.sc_add_buttons["line_plot"].click()  # the chart: matplotlib's Qt Agg canvas
    w.viewer.render()
    render_image(w.viewer, (320, 200))
    w.create_report()
    loaded = _loaded_qt_modules()
    assert {"QtCore", "QtGui", "QtWidgets"} <= loaded
    assert loaded <= ESSENTIALS | OPTIONAL, sorted(loaded - ESSENTIALS - OPTIONAL)


BLOCKER = """
import sys
from importlib.abc import MetaPathFinder

ESSENTIALS = %r

class Block(MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.startswith("PySide6.Qt") and name.split(".")[1] not in ESSENTIALS:
            raise ModuleNotFoundError(f"No module named {name!r} (blocked)", name=name)
        return None

sys.meta_path.insert(0, Block())
from vortexcfd.core.display_guard import apply_display_guard
apply_display_guard()
import matplotlib.backends.backend_qtagg, pyvistaqt, vortexcfd.cli, vortexcfd.gui.main_window
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pyvistaqt import QtInteractor
QtInteractor(auto_update=False).close()
print(sorted({n.split(".")[1] for n in sys.modules if n.startswith("PySide6.Qt")}))
"""


def test_the_gui_imports_without_the_other_modules() -> None:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    env.pop("VORTEXCFD_ALLOW_REAL_DISPLAY", None)
    result = subprocess.run([sys.executable, "-c", BLOCKER % sorted(ESSENTIALS)], capture_output=True, text=True,
                            env=env, timeout=120)
    assert result.returncode == 0, result.stderr
    loaded = set(ast.literal_eval(result.stdout.strip().splitlines()[-1]))
    assert {"QtCore", "QtGui", "QtWidgets", "QtOpenGLWidgets"} <= loaded <= ESSENTIALS
