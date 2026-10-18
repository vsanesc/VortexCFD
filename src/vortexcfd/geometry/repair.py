"""Surface repair: pymeshfix first, the pytetwild (fTetWild) envelope as the fallback (no Qt).

``repair_surface`` never modifies its input: it returns a new mesh with the before / after
reports. A pymeshfix result is accepted only when it is snappy-ready AND faithful (FIDELITY):
MeshFix removes self-intersecting regions and may drop whole pieces of a surface (two overlapping
spheres came back as a cap 0.65 m long instead of 0.8 m), so a result whose bounding box shrank,
or whose points left the original surface, falls back to the envelope (D-072).
"""

import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.geometry.checks import SurfaceReport, check_surface

# A repaired surface is faithful when its bounding box matches the original's within BOX_TOLERANCE
# and at least ON_SURFACE_FRACTION of its points lie within DISTANCE_TOLERANCE of the original
# surface (both relative to the original bounding-box diagonal).
BOX_TOLERANCE = 0.02
DISTANCE_TOLERANCE = 0.01
ON_SURFACE_FRACTION = 0.9
# fTetWild envelope: maximum distance of the output from the input, relative to the bbox diagonal.
ENVELOPE_EPSILON = 1e-3
ENVELOPE_EDGE_FACTOR = 0.05


@dataclass(frozen=True)
class Fidelity:
    """How closely a repaired surface follows the original (relative to its bounding-box diagonal)."""

    box_change: float  # largest change of a bounding-box bound
    on_surface: float  # fraction of the repaired points within DISTANCE_TOLERANCE of the original

    @property
    def ok(self) -> bool:
        return self.box_change <= BOX_TOLERANCE and self.on_surface >= ON_SURFACE_FRACTION

    def text(self) -> str:
        return (f"bounding box changed by {self.box_change:.2%} of the diagonal, {self.on_surface:.1%} of the "
                f"repaired points within {DISTANCE_TOLERANCE:.0%} of it from the original surface")


@dataclass
class RepairResult:
    mesh: pv.PolyData  # the repaired surface (the input unchanged when method is "none")
    before: SurfaceReport
    after: SurfaceReport
    method: str  # "none" (already clean), "pymeshfix", "pytetwild envelope"
    notes: list[str] = field(default_factory=list)
    fidelity: Fidelity | None = None  # of the returned surface (None when nothing was repaired)

    @property
    def remaining(self) -> list[str]:
        """Defects still present after the repair (empty when snappy-ready)."""
        return remaining_defects(self.after)


def remaining_defects(report: SurfaceReport) -> list[str]:
    out = []
    if report.open_edges:
        out.append(f"{report.open_edges} open edges")
    if report.non_manifold_edges:
        out.append(f"{report.non_manifold_edges} non-manifold edges")
    if report.self_intersections:
        out.append(f"{report.self_intersections} self-intersecting triangles")
    elif report.self_intersections is None:
        out.append(f"self-intersections {report.intersections_note}")
    if report.duplicate_faces:
        out.append(f"{report.duplicate_faces} duplicate faces")
    if report.inconsistent_orientation:
        out.append(f"{report.inconsistent_orientation} inconsistently oriented triangles")
    return out


def _triangles(mesh: pv.PolyData) -> np.ndarray:
    return np.asarray(mesh.triangulate().faces).reshape(-1, 4)[:, 1:]


def _polydata(points: np.ndarray, triangles: np.ndarray) -> pv.PolyData:
    triangles = np.asarray(triangles, dtype=np.int64)
    return pv.PolyData(np.asarray(points, dtype=float),
                       faces=np.hstack([np.full((len(triangles), 1), 3), triangles]).ravel())


def fidelity(original: pv.PolyData, repaired: pv.PolyData) -> Fidelity:
    """The fidelity metrics of a repaired surface (an empty one: box change 1, nothing on surface)."""
    if repaired.n_cells == 0:
        return Fidelity(1.0, 0.0)
    diag = original.length
    shift = float(np.abs(np.asarray(repaired.bounds) - np.asarray(original.bounds)).max())
    distance = np.abs(repaired.compute_implicit_distance(original)["implicit_distance"])
    return Fidelity(shift / diag, float((distance <= DISTANCE_TOLERANCE * diag).mean()))


def faithful(original: pv.PolyData, repaired: pv.PolyData) -> tuple[bool, str]:
    """(ok, reason): see BOX_TOLERANCE and ON_SURFACE_FRACTION."""
    if repaired.n_cells == 0:
        return False, "the repair removed every triangle"
    f = fidelity(original, repaired)
    if f.box_change > BOX_TOLERANCE:
        return False, f"the bounding box changed by {f.box_change:.1%} of the diagonal"
    if f.on_surface < ON_SURFACE_FRACTION:
        return False, f"only {f.on_surface:.0%} of the repaired points lie on the original surface"
    return True, ""


def meshfix(mesh: pv.PolyData) -> pv.PolyData:
    """pymeshfix's default repair (fill holes, remove degenerate and self-intersecting triangles),
    keeping every component."""
    import pymeshfix

    fixer = pymeshfix.MeshFix(np.asarray(mesh.points, dtype=float), _triangles(mesh).astype(np.int32))
    fixer.repair(joincomp=False, remove_smallest_components=False)
    return _polydata(fixer.points, fixer.faces)


def envelope(mesh: pv.PolyData) -> pv.PolyData:
    """The outer boundary of fTetWild's tetrahedralisation of the surface: a closed, manifold
    surface within ENVELOPE_EPSILON of the input (a "wrap" of a leaky or self-intersecting one)."""
    import pytetwild

    # fTetWild writes a debug copy of its surface to "__tracked_surface.stl" in the current directory.
    debug_file = Path.cwd() / "__tracked_surface.stl"
    existed = debug_file.exists()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # pytetwild 0.4.2 uses a deprecated PyVista accessor
            grid = pytetwild.tetrahedralize_pv(pv.PolyData(mesh.points, mesh.faces),
                                               edge_length_fac=ENVELOPE_EDGE_FACTOR, epsilon=ENVELOPE_EPSILON,
                                               quiet=True)
    finally:
        if not existed:
            debug_file.unlink(missing_ok=True)
    surface = grid.extract_surface(algorithm=None).triangulate().clean()
    surface.point_data.clear()
    surface.cell_data.clear()
    if check_surface(surface, intersections=False).signed_volume < 0:
        surface = surface.flip_faces()
    return surface


def repair_surface(mesh: pv.PolyData) -> RepairResult:
    """Repair a triangulated surface (any units): pymeshfix, then the envelope if needed."""
    clean = _polydata(mesh.points, _triangles(mesh))
    before = check_surface(clean)
    if before.snappy_ready:
        return RepairResult(clean, before, before, "none", ["The surface needs no repair."])
    notes = []
    fixed = meshfix(clean)
    after = check_surface(fixed)
    ok, reason = faithful(clean, fixed)
    if after.snappy_ready and ok:
        return RepairResult(fixed, before, after, "pymeshfix", notes, fidelity(clean, fixed))
    notes.append("pymeshfix: " + (reason if not ok else "; ".join(remaining_defects(after))) + "; using the envelope")
    wrapped = envelope(clean)
    after = check_surface(wrapped)
    ok, reason = faithful(clean, wrapped)
    if not ok:
        notes.append(f"pytetwild envelope: {reason}")
    return RepairResult(wrapped, before, after, "pytetwild envelope", notes, fidelity(clean, wrapped))
