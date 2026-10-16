"""Parser for checkMesh output (no Qt)."""

import re
from dataclasses import dataclass


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
