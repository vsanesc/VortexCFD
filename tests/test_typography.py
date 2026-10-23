"""Text roles (D-153): the theme's TEXT_ROLES are the only text sizes. A static scan fails on a font size set outside
gui/theme.py, and every widget of the main window and the start screen at each interface size uses a role's size."""

import ast
import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.gui.theme import DARK, INTERFACE_SIZES, TEXT_ROLES, apply_theme, build_stylesheet, metrics, role_font

GUI_DIR = Path(__file__).resolve().parent.parent / "src" / "vortexcfd" / "gui"
# Font calls only theme.py may make: sizes, weights, spacing and font construction.
FORBIDDEN_CALLS = {"setPointSize", "setPointSizeF", "setPixelSize", "setBold", "setWeight", "setLetterSpacing",
                   "QFont", "mono_font", "section_title_font"}
FORBIDDEN_TEXT = re.compile(r"font-size|font-weight|font:\s*\d")


def _violations(path: Path) -> list[str]:
    source = path.read_text()
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in FORBIDDEN_CALLS:
                out.append(f"{path.name}:{node.lineno} {name}()")
            for kw in node.keywords:  # matplotlib: fontsize=<number> instead of role_point_size(...)
                if kw.arg in ("fontsize", "size") and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, (int, float)) and name in ("text", "set_title", "legend"):
                    out.append(f"{path.name}:{node.lineno} {kw.arg}={kw.value.value}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and FORBIDDEN_TEXT.search(node.value):
            out.append(f"{path.name}:{node.lineno} stylesheet font")
    return out


def test_no_font_size_outside_the_theme_roles() -> None:
    violations = [v for path in sorted(GUI_DIR.glob("*.py")) if path.name != "theme.py" for v in _violations(path)]
    assert violations == []


def test_the_scan_catches_an_ad_hoc_size(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("f = label.font()\nf.setPointSizeF(7)\nlabel.setStyleSheet('font-size: 8pt')\n"
                   "fig.text(0, 0, 'x', fontsize=8)\n")
    assert len(_violations(bad)) == 3


@pytest.mark.parametrize("size", INTERFACE_SIZES.values())
def test_roles_scale_with_the_interface_size(qapp, size: int) -> None:
    apply_theme(DARK, size)
    try:
        for name, role in TEXT_ROLES.items():
            font = role_font(name)
            assert font.pointSizeF() == pytest.approx(size * role.scale), name
            assert font.weight().value == role.weight, name
        sheet = build_stylesheet(DARK, metrics(), float(size))
        sizes = {round(size * role.scale, 1) for role in TEXT_ROLES.values()}
        for found in re.findall(r"font-size: ([\d.]+)pt", sheet):
            assert float(found) in sizes, found
    finally:
        apply_theme(DARK, INTERFACE_SIZES["Small"])


def _role_sizes(size: int) -> list[float]:
    return [size * role.scale for role in TEXT_ROLES.values()]


def _off_role(root: QWidget, size: int) -> list[str]:
    allowed = _role_sizes(size)
    out = []
    for widget in [root, *root.findChildren(QWidget)]:
        points = widget.font().pointSizeF()
        if not any(abs(points - a) < 0.06 for a in allowed):
            out.append(f"{type(widget).__name__}#{widget.objectName()}: {points}")
    return out


@pytest.mark.parametrize("size", INTERFACE_SIZES.values())
def test_every_widget_uses_a_role_size(qtbot: QtBot, tmp_path: Path, size: int) -> None:
    from tests.test_boundary_types import sphere_project
    from vortexcfd.gui.main_window import MainWindow
    from vortexcfd.core.presets import PresetStore
    from vortexcfd.gui.recent import RecentProjects
    from vortexcfd.gui.start_dialogs import NewSimulationDialog, StartDialog

    apply_theme(DARK, size)
    try:
        w = MainWindow(sphere_project(tmp_path), FakeDialogs(), with_viewer=False)
        qtbot.addWidget(w)
        w.set_point_size(size)
        w.show()
        QApplication.processEvents()
        start = StartDialog(RecentProjects())
        new = NewSimulationDialog(PresetStore(tmp_path / "presets"), physical=4)
        for dialog in (start, new):
            qtbot.addWidget(dialog)
            dialog.show()
        QApplication.processEvents()
        assert _off_role(w, size) == []
        assert _off_role(start, size) == []
        assert _off_role(new, size) == []
        w.project.save = lambda *a, **k: None
        w.close()
    finally:
        apply_theme(DARK, INTERFACE_SIZES["Small"])


def test_a_state_change_keeps_the_role_after_a_size_change(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLabel

    from vortexcfd.gui.theme import repolish, set_text_role

    label = QLabel("x")
    label.setObjectName("checkValue")
    qtbot.addWidget(label)
    set_text_role(label, "value")
    label.show()
    apply_theme(DARK, INTERFACE_SIZES["Large"])
    try:
        set_text_role(label, "value")
        label.setProperty("warn", "true")
        repolish(label)  # Qt's re-polish alone would put back the Small size
        assert label.font().pointSizeF() == pytest.approx(INTERFACE_SIZES["Large"] * TEXT_ROLES["value"].scale)
    finally:
        apply_theme(DARK, INTERFACE_SIZES["Small"])
