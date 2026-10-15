"""Tests verifying architectural layer boundaries.

Layer constraints:
- cfdgui.core (simulation data model) must NOT import PySide6, pyvista, pyvistaqt,
  or cfdgui.gui.
- cfdgui.foam (OpenFOAM integration) must NOT import PySide6, pyvista, pyvistaqt,
  or cfdgui.gui.
"""

import ast
from pathlib import Path

FORBIDDEN_MODULES = ("PySide6", "pyvista", "pyvistaqt", "cfdgui.gui")


def _is_forbidden(module_name: str) -> bool:
    for forbidden in FORBIDDEN_MODULES:
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


def check_file_imports(file_path: Path, src_root: Path) -> list[str]:
    violations: list[str] = []
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden(alias.name):
                    violations.append(
                        f"{file_path}:{node.lineno}: forbidden import '{alias.name}'"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module and _is_forbidden(node.module):
                    violations.append(
                        f"{file_path}:{node.lineno}: forbidden import from '{node.module}'"
                    )
                else:
                    for alias in node.names:
                        full_name = (
                            f"{node.module}.{alias.name}" if node.module else alias.name
                        )
                        if _is_forbidden(full_name):
                            violations.append(
                                f"{file_path}:{node.lineno}: forbidden import '{full_name}'"
                            )
            else:
                resolved_mod = _resolve_relative_import(
                    file_path, src_root, node.level, node.module
                )
                if resolved_mod and _is_forbidden(resolved_mod):
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
                        if _is_forbidden(full_name):
                            violations.append(
                                f"{file_path}:{node.lineno}: forbidden relative import resolved to '{full_name}'"
                            )
    return violations


def test_core_and_foam_do_not_import_gui_or_viz() -> None:
    """Ensure core and foam packages do not import PySide6, pyvista, pyvistaqt, or cfdgui.gui."""
    repo_root = Path(__file__).resolve().parent.parent
    src_root = repo_root / "src"
    scanned_dirs = [src_root / "cfdgui" / "core", src_root / "cfdgui" / "foam"]

    files_to_scan: list[Path] = []
    for d in scanned_dirs:
        assert d.is_dir(), f"Expected layer directory does not exist: {d}"
        files_to_scan.extend(d.rglob("*.py"))

    assert files_to_scan, "No Python files found in core or foam directories"

    violations: list[str] = []
    for py_file in files_to_scan:
        violations.extend(check_file_imports(py_file, src_root))

    assert not violations, (
        f"Layer boundary violations detected ({len(violations)}):\n"
        + "\n".join(violations)
    )
