"""Generated dictionaries follow OpenFOAM's own syntax rules (docs/QUESTIONS.md item 145): scheme entries are
token streams, not lists, and keywords that are regular expressions are quoted."""

import re
from pathlib import Path

import pytest

from vortexcfd.core.model import Inflow, Mesh, Physics, Solvers
from vortexcfd.foam.case_writer import write_case
from vortexcfd.foam.mesh_case import MeshCaseInput, build_mesh_files
from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files
from vortexcfd.foam.runner import OPENFOAM_BASHRC, run_foam

needs_openfoam = pytest.mark.skipif(not Path(OPENFOAM_BASHRC).is_file(), reason="OpenFOAM v2606 not installed")

BOX = (-5, 10, -5, 5, -5, 5)
PARTS = (0.0, 1.0, -0.5, 0.5, 0.0, 0.3)
# A keyword meant as a regular expression: OpenFOAM's keyType is a pattern only when the keyword is quoted;
# unquoted, "cellDisplacement.*" is a plain word that matches nothing. (A "*" alone is a valid word
# character: div((nuEff*dev2(T(grad(U))))).)
REGEX = re.compile(r"\.\*|\.\+|\||^\^|\[.*\]")


def _cases(tmp_path: Path) -> dict[str, Path]:
    out = {}
    for name, mesh, kw in (
        ("yplus", Mesh(), {"first_layer_thickness": 1e-3, "layer_count": 12, "layer_expansion": 1.27}),
        ("relative", Mesh(layer_sizing="relative"), {}),
    ):
        folder = tmp_path / name
        write_case(folder, build_mesh_files(MeshCaseInput(BOX, False, ("Wing", "Tail"), PARTS, 1.0, mesh, **kw)))
        out[name] = folder
    folder = tmp_path / "solver"
    write_case(folder, build_solver_files(SolverCaseInput(Physics(), Inflow(), Solvers(), ("Wing", "Tail"),
                                                          PARTS, True)))
    out["solver"] = folder
    return out


def _dictionaries(folder: Path) -> list[Path]:
    return [p for p in sorted(folder.rglob("*")) if p.is_file() and p.read_text(errors="replace").lstrip().startswith(
        ("/*", "FoamFile"))]


def _entries(text: str):
    """(keyword, rest of the line) of every line that starts an entry or a sub-dictionary."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        if not line or line[0] in "(){};":
            continue
        if line[0] == '"':
            end = line.index('"', 1)
            yield line[:end + 1], line[end + 1:].strip()
        else:
            key, _, rest = line.partition(" ")
            yield key, rest.strip()


def test_scheme_entries_are_token_streams_not_lists(tmp_path: Path) -> None:
    for name, folder in _cases(tmp_path).items():
        text = (folder / "system" / "fvSchemes").read_text()
        for key, rest in _entries(text):
            assert not rest.startswith("("), f"{name}: fvSchemes entry {key} is a list: {key} {rest}"
        assert re.search(r"laplacianSchemes\s*\{\s*default\s+Gauss linear (corrected|limited)", text), name


def test_regular_expression_keywords_are_quoted(tmp_path: Path) -> None:
    files = [p for folder in _cases(tmp_path).values() for p in _dictionaries(folder)]
    assert any(p.name == "fvSolution" for p in files) and any(p.name == "snappyHexMeshDict" for p in files)
    quoted = 0
    for path in files:
        for key, _rest in _entries(path.read_text(errors="replace")):
            if key.startswith('"'):
                quoted += bool(REGEX.search(key))
                continue
            assert not REGEX.search(key), f"{path.relative_to(tmp_path)}: unquoted regular expression {key}"
    assert quoted > 0  # the per-part snappyHexMesh entries ("Wing.*") are there, quoted


def test_the_checks_catch_the_two_defects() -> None:
    entries = dict(_entries('laplacianSchemes\n{\n    default (Gauss linear corrected);\n}\n'
                            'solvers\n{\n    cellDisplacement.*\n    {\n    }\n    "(U|k).*" {}\n}\n'))
    assert entries["default"].startswith("(")  # a list value is seen
    assert REGEX.search("cellDisplacement.*") and '"(U|k).*"' in entries  # unquoted and quoted keys
    assert not REGEX.search("div((nuEff*dev2(T(grad(U)))))")  # a word with "*", not a pattern


@needs_openfoam
def test_openfoam_reads_the_placeholder_schemes_as_words(tmp_path: Path) -> None:
    folder = _cases(tmp_path)["yplus"]
    log = tmp_path / "log.foamDictionary"
    code = run_foam(["foamDictionary", "-entry", "laplacianSchemes/default", "-value", "system/fvSchemes"],
                    folder, log)
    assert code == 0 and log.read_text().strip().splitlines()[-1].strip() == "Gauss linear corrected"
