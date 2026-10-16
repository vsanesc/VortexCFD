"""Parsers for checkMesh and snappyHexMesh output (no Qt)."""

import re
from dataclasses import dataclass


# Per-patch layer coverage below this percentage is a warning.
LAYER_WARN_PERCENT = 80.0


@dataclass(frozen=True)
class LayerCoverage:
    """One row of snappyHexMesh's final layer table.

    snappyHexMesh prints no per-patch count of faces that received layers, so the coverage
    of a patch is the achieved fraction of the target layer thickness (``basis`` is
    "thickness"); the overall share of extruded faces is ``MeshReport.extruded_percent``.
    """

    patch: str
    faces: int
    target_layers: int
    mesh_layers: float  # layers actually present (average)
    thickness_m: float  # overall layer thickness
    thickness_percent: float  # achieved fraction of the target thickness
    basis: str = "thickness"

    @property
    def coverage_percent(self) -> float:
        return self.thickness_percent

    @property
    def below_threshold(self) -> bool:
        return self.coverage_percent < LAYER_WARN_PERCENT


@dataclass(frozen=True)
class MeshReport:
    """Summary of a checkMesh run. Numbers that the log did not print are None."""

    points: int | None
    faces: int | None
    cells: int | None
    max_non_orthogonality: float | None
    avg_non_orthogonality: float | None
    max_skewness: float | None
    failed_checks: int  # 0 when "Mesh OK."
    mesh_ok: bool
    layers: tuple[LayerCoverage, ...] = ()
    extruded_percent: float | None = None  # share of surface faces that got layers (overall)

    def summary(self) -> str:
        parts = []
        if self.cells is not None:
            parts.append(f"{self.cells} cells")
        if self.faces is not None:
            parts.append(f"{self.faces} faces")
        if self.max_non_orthogonality is not None:
            parts.append(f"max non-orthogonality {self.max_non_orthogonality:g}")
        if self.max_skewness is not None:
            parts.append(f"max skewness {self.max_skewness:g}")
        parts.append("Mesh OK" if self.mesh_ok else f"{self.failed_checks} failed checks")
        return ", ".join(parts)

    def layer_summary(self) -> str:
        """One line about the layers ("" when none were added)."""
        if not self.layers:
            return ""
        rows = ", ".join(f"{c.patch} {c.coverage_percent:g}% ({c.mesh_layers:g}/{c.target_layers} layers)"
                         for c in self.layers)
        return f"layer thickness achieved: {rows}"


_INT = r"(\d+)"
_NUM = r"([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)"


def _find(pattern: str, text: str, cast):
    match = re.search(pattern, text, re.MULTILINE)
    return cast(match.group(1)) if match else None


def parse_check_mesh(text: str) -> MeshReport:
    """Parse the output of ``checkMesh``.

    "Mesh OK." means no failed checks; "Failed N mesh checks." gives the count. A log with
    neither (checkMesh crashed or was stopped) is reported as not OK with one failed check.
    """
    mesh_ok = re.search(r"^\s*Mesh OK\.", text, re.MULTILINE) is not None
    failed = _find(rf"^\s*Failed {_INT} mesh checks?\.", text, int)
    if mesh_ok:
        failed = 0
    elif failed is None:
        failed = 1
    non_ortho = re.search(rf"Mesh non-orthogonality Max: {_NUM} average: {_NUM}", text)
    return MeshReport(
        points=_find(rf"^\s*points:\s+{_INT}", text, int),
        faces=_find(rf"^\s*faces:\s+{_INT}", text, int),
        cells=_find(rf"^\s*cells:\s+{_INT}", text, int),
        max_non_orthogonality=float(non_ortho.group(1)) if non_ortho else None,
        avg_non_orthogonality=float(non_ortho.group(2)) if non_ortho else None,
        max_skewness=_find(rf"Max skewness = {_NUM}", text, float),
        failed_checks=failed,
        mesh_ok=mesh_ok,
    )


def parse_layer_table(text: str) -> tuple[tuple[LayerCoverage, ...], float | None]:
    """Parse snappyHexMesh's final layer summary table and the last "Extruding" line.

    The final table (header "patch faces layers overall thickness") has one row per patch:
    ``name faces target-layers mesh-layers thickness[m] thickness[%]``. Returns the rows and the
    overall percentage of extruded faces (None if the log has no such line).
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*patch\s+faces\s+layers\s+overall thickness", line):
            start = i  # keep the LAST table: it is the final summary
    rows: list[LayerCoverage] = []
    if start is not None:
        for line in lines[start + 1:]:
            if not line.strip():
                if rows:
                    break
                continue
            if line.lstrip().startswith(("target", "-----")):
                continue
            fields = line.split()
            if len(fields) != 6:
                break
            try:
                rows.append(LayerCoverage(
                    patch=fields[0], faces=int(fields[1]), target_layers=int(fields[2]),
                    mesh_layers=float(fields[3]), thickness_m=float(fields[4]),
                    thickness_percent=float(fields[5]),
                ))
            except ValueError:
                break
    extruded = None
    for match in re.finditer(rf"Extruding {_INT} out of {_INT} faces \({_NUM}%\)", text):
        extruded = float(match.group(3))
    return tuple(rows), extruded
