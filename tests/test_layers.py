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
GEOMETRY_FORBIDDEN = ("PySide6", "pyvistaqt", "vortexcfd.gui")


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
        src_root / "vortexcfd" / "foam": FORBIDDEN_MODULES,
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
