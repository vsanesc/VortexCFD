"""Tests verifying architectural layer boundaries.

Layer constraints:
- vortexcfd.core (simulation data model) must NOT import PySide6, pyvista, pyvistaqt,
  or vortexcfd.gui.
- vortexcfd.foam (OpenFOAM integration) must NOT import PySide6, pyvista, pyvistaqt,
  or vortexcfd.gui.
- vortexcfd.geometry (surface loading and checks) may import numpy and pyvista but must NOT
  import PySide6, pyvistaqt or vortexcfd.gui; core must not import vortexcfd.geometry.
- vortexcfd.workflow (Qt-free orchestration) may import core, foam and geometry but must NOT import
  PySide6, pyvistaqt or vortexcfd.gui; gui may import workflow.
- vortexcfd.bench (the meshing benchmark) follows the workflow rules.
"""

import ast
from pathlib import Path

FORBIDDEN_MODULES = ("PySide6", "pyvista", "pyvistaqt", "vortexcfd.gui")
CORE_FORBIDDEN = FORBIDDEN_MODULES + ("vortexcfd.geometry",)
# foam must stay pyvista-free even transitively, so it must not import geometry either.
FOAM_FORBIDDEN = FORBIDDEN_MODULES + ("vortexcfd.geometry",)
GEOMETRY_FORBIDDEN = ("PySide6", "pyvistaqt", "vortexcfd.gui", "vortexcfd.foam")

# The Qt-free orchestration (it joins core, geometry and foam) and the benchmark that drives it.
WORKFLOW_FORBIDDEN = ("PySide6", "pyvistaqt", "vortexcfd.gui", "vortexcfd.bench")
BENCH_FORBIDDEN = ("PySide6", "pyvistaqt", "vortexcfd.gui")

# Every module under src/vortexcfd/ lives in one of these layers; gui/ is unrestricted.
# vortexcfd/cli.py (D-137): ``--version`` and ``--check-openfoam`` run without Qt (tests/test_openfoam_check.py
# checks it in a subprocess); it reaches vortexcfd.gui only inside main().
CLI_FORBIDDEN = ("PySide6", "pyvistaqt", "pyvista")
LAYER_RULES: dict[str, tuple[str, ...]] = {
    "core": CORE_FORBIDDEN,
    "foam": FOAM_FORBIDDEN,
    "geometry": GEOMETRY_FORBIDDEN,
    "workflow": WORKFLOW_FORBIDDEN,
    "bench": BENCH_FORBIDDEN,
    "brand": CORE_FORBIDDEN,  # the logo's data (D-175)
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
    """No module may live outside the known layers (except the package __init__,
    which gets the strictest rules); an unknown location fails the test."""
    src_root = Path(__file__).resolve().parent.parent / "src"
    package = src_root / "vortexcfd"
    unknown: list[str] = []
    violations: list[str] = []
    for py_file in sorted(package.rglob("*.py")):
        rel = py_file.relative_to(package)
        if len(rel.parts) == 1:  # a top-level module
            if rel.name == "cli.py":  # the console script (D-137): no Qt of its own, the GUI only imported lazily
                rules = CLI_FORBIDDEN
            elif rel.name != "__init__.py":
                unknown.append(str(rel))
                continue
            else:
                rules = CORE_FORBIDDEN  # the package __init__ must stay free of Qt, pyvista and gui
        elif rel.parts[0] in LAYER_RULES:
            rules = LAYER_RULES[rel.parts[0]]
        else:
            unknown.append(str(rel))
            continue
        violations.extend(check_file_imports(py_file, src_root, rules))
    assert not unknown, f"modules outside the known layers {sorted(LAYER_RULES)}: {unknown}"
    assert not violations, "\n".join(violations)


def test_workflow_and_bench_import_no_qt_and_no_gui() -> None:
    """workflow/ and bench/ import no Qt and nothing from gui/ (D-082, D-083)."""
    src_root = Path(__file__).resolve().parent.parent / "src"
    violations: list[str] = []
    for layer, forbidden in (("workflow", WORKFLOW_FORBIDDEN), ("bench", BENCH_FORBIDDEN)):
        files = sorted((src_root / "vortexcfd" / layer).rglob("*.py"))
        assert files, layer
        for py_file in files:
            violations.extend(check_file_imports(py_file, src_root, forbidden))
    assert not violations, "\n".join(violations)


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
    wf = root / "vortexcfd" / "workflow"
    wf.mkdir()
    (wf / "bad.py").write_text("from vortexcfd.gui.scene import MeshView\nimport pyvistaqt\n")
    assert len(check_file_imports(wf / "bad.py", root, WORKFLOW_FORBIDDEN)) == 2
    (wf / "ok.py").write_text("from vortexcfd.geometry import loader\nfrom vortexcfd.foam import mesh_case\n")
    assert check_file_imports(wf / "ok.py", root, WORKFLOW_FORBIDDEN) == []
