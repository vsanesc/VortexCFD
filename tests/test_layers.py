"""Tests verifying architectural layer boundaries.

Layer constraints:
- vortexcfd.core (simulation data model) must NOT import PySide6, pyvista, pyvistaqt,
  or vortexcfd.gui.
- vortexcfd.foam (OpenFOAM integration) must NOT import PySide6, pyvista, pyvistaqt,
  or vortexcfd.gui.
- vortexcfd.geometry (surface loading and checks) may import numpy and pyvista but must NOT
  import PySide6, pyvistaqt or vortexcfd.gui; core must not import vortexcfd.geometry.
"""

import ast
from pathlib import Path

FORBIDDEN_MODULES = ("PySide6", "pyvista", "pyvistaqt", "vortexcfd.gui")
CORE_FORBIDDEN = FORBIDDEN_MODULES + ("vortexcfd.geometry",)
# foam must stay pyvista-free even transitively, so it must not import geometry either.
FOAM_FORBIDDEN = FORBIDDEN_MODULES + ("vortexcfd.geometry",)
GEOMETRY_FORBIDDEN = ("PySide6", "pyvistaqt", "vortexcfd.gui", "vortexcfd.foam")

# The Qt-free orchestration modules of gui/ (they join core, geometry and foam); the benchmark may
# import only these from gui/ (D-082), and they must never import Qt.
GUI_QT_FREE = ("meshing", "solving", "part_ops")
_GUI_DIR = Path(__file__).resolve().parent.parent / "src" / "vortexcfd" / "gui"
BENCH_FORBIDDEN = ("PySide6", "pyvistaqt", "vortexcfd.gui.MainWindow", "vortexcfd.gui.main") + tuple(
    f"vortexcfd.gui.{p.stem}" for p in sorted(_GUI_DIR.glob("*.py"))
    if p.stem not in GUI_QT_FREE and p.stem != "__init__")

# Every module under src/vortexcfd/ lives in one of these layers; gui/ is unrestricted.
LAYER_RULES: dict[str, tuple[str, ...]] = {
    "core": CORE_FORBIDDEN,
    "foam": FOAM_FORBIDDEN,
    "geometry": GEOMETRY_FORBIDDEN,
    "bench": BENCH_FORBIDDEN,
    "gui": (),
}


def _is_forbidden(module_name: str, forbidden_modules: tuple[str, ...] = FORBIDDEN_MODULES) -> bool:
    for forbidden in forbidden_modules:
        if module_name == forbidden or module_name.startswith(forbidden + "."):
            return True
    return False


def _resolve_relative_import(
    file_path: Path, src_root: Path, level: int, module: str | None
) -> str:
    rel_path = file_path.relative_to(src_root)
    pkg_parts = list(rel_path.parent.parts)
    if level > len(pkg_parts):
        base_parts: list[str] = []
    else:
        base_parts = pkg_parts[: len(pkg_parts) - level + 1]

    if module:
        base_parts.extend(module.split("."))
    return ".".join(base_parts)


def check_file_imports(
    file_path: Path, src_root: Path, forbidden: tuple[str, ...] = FORBIDDEN_MODULES
) -> list[str]:
    violations: list[str] = []
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden(alias.name, forbidden):
                    violations.append(
                        f"{file_path}:{node.lineno}: forbidden import '{alias.name}'"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module and _is_forbidden(node.module, forbidden):
                    violations.append(
                        f"{file_path}:{node.lineno}: forbidden import from '{node.module}'"
                    )
                else:
                    for alias in node.names:
                        full_name = (
                            f"{node.module}.{alias.name}" if node.module else alias.name
                        )
                        if _is_forbidden(full_name, forbidden):
                            violations.append(
                                f"{file_path}:{node.lineno}: forbidden import '{full_name}'"
                            )
            else:
                resolved_mod = _resolve_relative_import(
                    file_path, src_root, node.level, node.module
                )
                if resolved_mod and _is_forbidden(resolved_mod, forbidden):
                    violations.append(
                        f"{file_path}:{node.lineno}: forbidden relative import resolved to '{resolved_mod}'"
                    )
                else:
                    for alias in node.names:
                        full_name = (
                            f"{resolved_mod}.{alias.name}"
                            if resolved_mod
                            else alias.name
                        )
                        if _is_forbidden(full_name, forbidden):
                            violations.append(
                                f"{file_path}:{node.lineno}: forbidden relative import resolved to '{full_name}'"
                            )
    return violations


def test_core_and_foam_do_not_import_gui_or_viz() -> None:
    """Ensure core and foam packages do not import PySide6, pyvista, pyvistaqt, or vortexcfd.gui."""
    repo_root = Path(__file__).resolve().parent.parent
    src_root = repo_root / "src"
    scanned = {
        src_root / "vortexcfd" / "core": CORE_FORBIDDEN,
        src_root / "vortexcfd" / "foam": FOAM_FORBIDDEN,
    }

    violations: list[str] = []
    for d, forbidden in scanned.items():
        assert d.is_dir(), f"Expected layer directory does not exist: {d}"
        files = list(d.rglob("*.py"))
        assert files, f"No Python files found in {d}"
        for py_file in files:
            violations.extend(check_file_imports(py_file, src_root, forbidden))

    assert not violations, (
        f"Layer boundary violations detected ({len(violations)}):\n"
        + "\n".join(violations)
    )


def test_geometry_layer_has_no_qt_or_gui_imports() -> None:
    """geometry may use numpy and pyvista, but never Qt, pyvistaqt or vortexcfd.gui."""
    src_root = Path(__file__).resolve().parent.parent / "src"
    d = src_root / "vortexcfd" / "geometry"
    assert d.is_dir()
    files = list(d.rglob("*.py"))
    assert files
    violations: list[str] = []
    for py_file in files:
        violations.extend(check_file_imports(py_file, src_root, GEOMETRY_FORBIDDEN))
    assert not violations, "\n".join(violations)


def test_every_module_belongs_to_a_known_layer_and_follows_its_rules() -> None:
    """No module may live outside core/, foam/, geometry/ or gui/ (except the package __init__,
    which gets the strictest rules); an unknown location fails the test."""
    src_root = Path(__file__).resolve().parent.parent / "src"
    package = src_root / "vortexcfd"
    unknown: list[str] = []
    violations: list[str] = []
    for py_file in sorted(package.rglob("*.py")):
        rel = py_file.relative_to(package)
        if len(rel.parts) == 1:  # a top-level module
            if rel.name != "__init__.py":
                unknown.append(str(rel))
                continue
            rules = CORE_FORBIDDEN  # the package __init__ must stay free of Qt, pyvista and gui
        elif rel.parts[0] in LAYER_RULES:
            rules = LAYER_RULES[rel.parts[0]]
        else:
            unknown.append(str(rel))
            continue
        violations.extend(check_file_imports(py_file, src_root, rules))
    assert not unknown, f"modules outside the known layers {sorted(LAYER_RULES)}: {unknown}"
    assert not violations, "\n".join(violations)


def test_bench_uses_only_the_qt_free_gui_modules() -> None:
    """The benchmark imports no Qt and, from gui/, only the Qt-free orchestration modules, which
    themselves import no Qt and no other gui module that would (D-082)."""
    src_root = Path(__file__).resolve().parent.parent / "src"
    violations: list[str] = []
    for py_file in sorted((src_root / "vortexcfd" / "bench").rglob("*.py")):
        violations.extend(check_file_imports(py_file, src_root, BENCH_FORBIDDEN))
    for name in GUI_QT_FREE:
        violations.extend(check_file_imports(_GUI_DIR / f"{name}.py", src_root, BENCH_FORBIDDEN))
    assert not violations, "\n".join(violations)
    assert "vortexcfd.gui.main_window" in BENCH_FORBIDDEN and "vortexcfd.gui.meshing" not in BENCH_FORBIDDEN


def test_checker_detects_violations_and_unknown_layers(tmp_path: Path) -> None:
    """The checker itself works: forbidden imports are reported (absolute and relative)."""
    root = tmp_path / "src"
    mod = root / "vortexcfd" / "foam"
    mod.mkdir(parents=True)
    (mod / "bad.py").write_text("import pyvista\nfrom vortexcfd.geometry import loader\nfrom PySide6 import QtCore\n")
    found = check_file_imports(mod / "bad.py", root, FOAM_FORBIDDEN)
    assert len(found) == 3
    (mod / "ok.py").write_text("import numpy\nfrom vortexcfd.core import model\n")
    assert check_file_imports(mod / "ok.py", root, FOAM_FORBIDDEN) == []
    geo = root / "vortexcfd" / "geometry"
    geo.mkdir()
    (geo / "bad.py").write_text("from vortexcfd.foam import mesh_case\n")
    assert check_file_imports(geo / "bad.py", root, GEOMETRY_FORBIDDEN)
