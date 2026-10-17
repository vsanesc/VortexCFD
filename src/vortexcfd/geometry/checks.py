"""Quality checks for triangulated surfaces."""

from dataclasses import dataclass

import numpy as np
import pyvista as pv

from vortexcfd.geometry import loader

# A triangle is degenerate when its area is below this fraction of the squared bbox diagonal.
DEGENERATE_AREA_TOLERANCE = 1e-10


@dataclass(frozen=True)
class SurfaceReport:
    """Result of ``check_surface``."""

    n_triangles: int
    n_points: int
    bounds: tuple[float, float, float, float, float, float]
    size: tuple[float, float, float]
    open_edges: int  # edges used by exactly one triangle
    non_manifold_edges: int  # edges used by more than two triangles
    degenerate_triangles: int
    duplicate_faces: int
    inconsistent_orientation: int  # triangles to flip to make orientation consistent
    watertight: bool
    # Signed volume (m3) enclosed by the triangles, from their orientation: negative for a closed
    # surface whose normals point inward. Meaningful only when watertight.
    signed_volume: float = 0.0

    @property
    def normals_inward(self) -> bool:
        """A closed surface whose normals point inward (negative signed volume). Not flipped."""
        return self.watertight and self.signed_volume < 0

    def summary(self) -> str:
        """One-line summary for logs."""
        problems = []
        if self.open_edges:
            problems.append(f"{self.open_edges} open edges")
        if self.non_manifold_edges:
            problems.append(f"{self.non_manifold_edges} non-manifold edges")
        if self.degenerate_triangles:
            problems.append(f"{self.degenerate_triangles} degenerate triangles")
        if self.duplicate_faces:
            problems.append(f"{self.duplicate_faces} duplicate faces")
        if self.inconsistent_orientation:
            problems.append(f"{self.inconsistent_orientation} inconsistently oriented triangles")
        if self.normals_inward:
            problems.append("normals point inward")
        head = f"{self.n_triangles} triangles, {self.n_points} points, watertight: {'yes' if self.watertight else 'no'}"
        return head + ("; " + ", ".join(problems) if problems else "")


_report_cache: dict[tuple, SurfaceReport] = {}


def surface_report(path, units: str) -> SurfaceReport:
    """Report for a surface file, computed once per (resolved path, mtime, units).

    The report is cached alongside the loader cache (``loader.clear_cache`` clears both).
    Raises what ``load_surface`` raises.
    """
    from pathlib import Path

    key = loader.cache_key(Path(path), units)
    report = _report_cache.get(key)
    if report is None:
        report = check_surface(loader.load_surface(Path(path), units))
        _report_cache[key] = report
    return report


loader._clear_hooks.append(_report_cache.clear)


def _triangles(mesh: pv.PolyData) -> np.ndarray:
    tri = mesh if mesh.is_all_triangles else mesh.triangulate()
    return np.asarray(tri.faces).reshape(-1, 4)[:, 1:]


def _group_counts(rows: np.ndarray, n_points: int) -> np.ndarray:
    """Occurrence count of each distinct row (rows of point ids, each < ``n_points``)."""
    width = rows.shape[1]
    if n_points ** width < np.iinfo(np.int64).max:  # pack each row into one integer: fast
        key = np.zeros(len(rows), dtype=np.int64)
        for col in range(width):
            key = key * n_points + rows[:, col]
        return np.unique(key, return_counts=True)[1]
    return np.unique(rows, axis=0, return_counts=True)[1]


def _orientation_conflicts(mesh: pv.PolyData) -> int:
    """Triangles that disagree with an auto-oriented copy (the smaller side of the split)."""
    n = mesh.n_cells
    try:
        base = mesh.compute_normals(cell_normals=True, point_normals=False, split_vertices=False,
                                    consistent_normals=False, auto_orient_normals=False)
        fixed = mesh.compute_normals(cell_normals=True, point_normals=False, split_vertices=False,
                                     consistent_normals=True, auto_orient_normals=True)
    except Exception:  # pragma: no cover - VTK failure on pathological input
        return 0
    if fixed.n_cells != n:  # cell order not preserved: cannot compare
        return 0
    dots = np.einsum("ij,ij->i", base.cell_data["Normals"], fixed.cell_data["Normals"])
    flipped = int(np.count_nonzero(dots < 0))
    return min(flipped, n - flipped)


def check_surface(mesh: pv.PolyData) -> SurfaceReport:
    """Check a triangulated surface.

    Reports open and non-manifold edges, degenerate triangles, duplicate faces and
    inconsistent orientation, and the signed volume (negative: normals point inward).
    Self-intersections are NOT checked (Phase 3.3).
    """
    tris = _triangles(mesh)
    n_tri = len(tris)
    bounds = tuple(float(b) for b in mesh.bounds)
    size = (bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
    if n_tri == 0:
        return SurfaceReport(0, mesh.n_points, bounds, size, 0, 0, 0, 0, 0, False)

    n_points = int(mesh.n_points)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    edges.sort(axis=1)
    counts = _group_counts(edges, n_points)
    open_edges = int(np.count_nonzero(counts == 1))
    non_manifold = int(np.count_nonzero(counts > 2))

    pts = np.asarray(mesh.points, dtype=float)
    a, b, c = pts[tris[:, 0]], pts[tris[:, 1]], pts[tris[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    diag2 = float(size[0] ** 2 + size[1] ** 2 + size[2] ** 2)
    degenerate = int(np.count_nonzero(areas <= DEGENERATE_AREA_TOLERANCE * diag2))

    sorted_tris = np.sort(tris, axis=1)
    duplicates = n_tri - len(_group_counts(sorted_tris, n_points))

    tri_mesh = mesh if mesh.is_all_triangles else mesh.triangulate()
    return SurfaceReport(
        n_triangles=n_tri,
        n_points=int(mesh.n_points),
        bounds=bounds,
        size=size,
        open_edges=open_edges,
        non_manifold_edges=non_manifold,
        degenerate_triangles=degenerate,
        duplicate_faces=duplicates,
        inconsistent_orientation=_orientation_conflicts(tri_mesh),
        watertight=open_edges == 0 and non_manifold == 0,
        signed_volume=float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0),
    )
