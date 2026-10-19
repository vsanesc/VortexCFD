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
        """Thickness coverage: the achieved fraction of the target layer thickness."""
        return self.thickness_percent

    @property
    def layers_percent(self) -> float:
        """Average layers present / target layers, in percent (100 when no layers were asked)."""
        return 100.0 * self.mesh_layers / self.target_layers if self.target_layers else 100.0

    @property
    def below_threshold(self) -> bool:
        """Either metric (layer count or thickness) is below 80 %."""
        return min(self.layers_percent, self.thickness_percent) < LAYER_WARN_PERCENT

    def description(self) -> str:
        """E.g. "2.1 / 3 (70 %), thickness 64 %"."""
        return (f"{self.mesh_layers:g} / {self.target_layers} ({self.layers_percent:.0f} %), "
                f"thickness {self.thickness_percent:g} %")


# checkMesh failure classes (D-100, from the v2606 sources: primitiveMeshCheck.C, polyMeshCheck.C,
# checkTopology.C, checkGeometry.C). A "***" line starts with one of these texts. HARD failures make
# the mesh unusable for the solver and block it; SOFT ones are quality warnings. A "***" line matching
# neither, and any failure checkMesh counted without a "***" line, is HARD. [NUMERICS-REVIEW]
HARD_CHECKS = (
    "Zero or negative cell volume detected",  # checkCellVolumes
    "Zero or negative face area detected",  # checkFaceAreas
    "Error in face pyramids",  # checkFacePyramids: incorrectly oriented faces
    "Number of non-orthogonality errors",  # checkFaceOrthogonality: faces above 90 degrees
    "Open cells found",  # checkCellsZipUp (number of cells) and checkClosedCells (max cell openness)
    "Cells with invalid face labels found",  # checkClosedCells: illegal cells
    "Illegal cells",  # checkTopology: cells with fewer than 4 faces or out-of-range faces
    "Faces not in upper triangular order",  # checkUpperTriangular
    "Boundary openness",  # checkClosedBoundary: a hole in the boundary
    "Total number of faces on empty patches",  # checkTopology: a 2D set-up error
    "Cannot find opposite wedge",  # checkGeometry: axisymmetric set-up errors
    "Wedges do not have the same axis",
    "Wedge patch",
)
SOFT_CHECKS = (
    "Max skewness",  # checkFaceSkewness: above 4
    "High aspect ratio cells found",  # checkClosedCells: above 1000
    "Concave cells",  # checkConcaveCells (-allGeometry)
    "Faces with small interpolation weight",  # checkFaceWeight (-allGeometry)
    "Faces with small volume ratio",  # checkVolRatio (-allGeometry)
    "Cells with small determinant",  # checkCellDeterminant (-allGeometry)
    "Number of edges not aligned with or perpendicular to",  # checkEdgeAlignment (2D meshes)
    "Unused points found in the mesh",  # checkPoints
)
# Lines with a single "*" are printed without failing the mesh; they are SOFT warnings too:
# "*Number of severely non-orthogonal faces" (70 to 90 degrees), "*There are N faces with concave
# angles", "*There are N warped faces", "*Number of regions".


def check_class(line: str) -> str:
    """"hard" or "soft" for a checkMesh "***" line (its text after the stars)."""
    if line.startswith(SOFT_CHECKS):
        return "soft"
    return "hard"


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
    # Part patches with no faces in constant/polyMesh/boundary (D-052): checkMesh can still say
    # "Mesh OK" when a whole part was never meshed.
    lost_parts: tuple[str, ...] = ()
    # The domain guard (D-078): a background-box patch left with faces or a domain patch without any.
    domain_errors: tuple[str, ...] = ()
    # checkMesh's "***" lines of the failed checks (D-096), e.g. "Zero or negative cell volume detected.
    # Minimum negative volume: -6e-06, Number of negative volume cells: 6".
    failed_check_lines: tuple[str, ...] = ()
    # checkMesh's single-"*" lines, printed without failing the mesh (severe non-orthogonality, ...).
    warning_lines: tuple[str, ...] = ()

    @property
    def hard_failures(self) -> tuple[str, ...]:
        """The failed checks that make the mesh unusable (D-100): the HARD "***" lines, plus one entry
        for failures checkMesh counted without a "***" line (or a record that kept no lines)."""
        if self.mesh_ok:
            return ()
        hard = tuple(line for line in self.failed_check_lines if check_class(line) == "hard")
        unexplained = self.failed_checks - len(self.failed_check_lines)
        if unexplained > 0:
            hard += (f"{unexplained} failed check{'s' if unexplained != 1 else ''} without a description",)
        return hard

    @property
    def soft_warnings(self) -> tuple[str, ...]:
        """Quality warnings that do not block the solver (D-100): SOFT "***" lines and "*" lines."""
        soft = tuple(line for line in self.failed_check_lines if check_class(line) == "soft")
        return soft + self.warning_lines

    def failed_checks_message(self) -> str | None:
        """Why the solver must not run on this mesh: its HARD checkMesh failures (None: none, D-100)."""
        hard = self.hard_failures
        if not hard:
            return None
        n = len(hard)
        return f"{n} hard failure{'s' if n != 1 else ''}: " + "; ".join(hard)

    def warnings_message(self) -> str | None:
        """The soft checkMesh warnings as one line (None: none)."""
        soft = self.soft_warnings
        return None if not soft else "checkMesh warnings: " + "; ".join(soft)

    @property
    def valid(self) -> bool:
        """No hard checkMesh failure (soft quality warnings allowed, D-100) AND every part and domain
        patch is in the mesh ("Mesh OK" alone is not enough)."""
        return not self.hard_failures and not self.lost_parts and not self.domain_errors

    def lost_messages(self) -> list[str]:
        """Why the mesh is invalid although checkMesh may pass: lost parts, then the domain guard."""
        return [lost_part_message(name) for name in self.lost_parts] + list(self.domain_errors)

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
        parts.extend(self.lost_messages())
        return ", ".join(parts)

    def layer_summary(self) -> str:
        """One line about the layers ("" when none were added)."""
        if not self.layers:
            return ""
        rows = ", ".join(f"{c.patch} {c.description()}" for c in self.layers)
        return f"layers per patch: {rows}"


def lost_part_message(name: str) -> str:
    return f"Part {name} was lost during meshing"


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
        failed_check_lines=tuple(" ".join(m.split()) for m in re.findall(r"^\s*\*{3}\s*(.+?)\s*$", text, re.MULTILINE)),
        warning_lines=tuple(" ".join(m.split()) for m in re.findall(r"^\s*\*(?!\*)\s*(\S.*?)\s*$", text, re.MULTILINE)),
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
