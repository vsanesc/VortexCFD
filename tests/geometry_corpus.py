"""Surfaces generated for the geometry tests (no binary files in the repository)."""

from pathlib import Path

import numpy as np
import pyvista as pv


def tris(mesh: pv.PolyData) -> np.ndarray:
    return np.asarray(mesh.triangulate().faces).reshape(-1, 4)[:, 1:]


def ascii_solid(name: str, mesh: pv.PolyData) -> str:
    """One ASCII STL `solid` block of a mesh's triangles."""
    mesh = mesh.triangulate()
    pts = np.asarray(mesh.points)
    rows = [f"solid {name}".rstrip()]
    for t in tris(mesh):
        rows += ["  facet normal 0 0 0", "    outer loop"]
        rows += [f"      vertex {pts[i][0]:.9g} {pts[i][1]:.9g} {pts[i][2]:.9g}" for i in t]
        rows += ["    endloop", "  endfacet"]
    rows.append(f"endsolid {name}".rstrip())
    return "\n".join(rows) + "\n"


def write_multi_solid(path: Path, solids: list[tuple[str, pv.PolyData]]) -> Path:
    Path(path).write_text("".join(ascii_solid(n, m) for n, m in solids))
    return Path(path)


def box_faces(size: float = 1.0, resolution: int = 2) -> list[tuple[str, pv.PolyData]]:
    """The six faces of a closed, outward-oriented cube as separate meshes (shared corner points)."""
    cube = pv.Box(bounds=(0, size, 0, size, 0, size), level=resolution - 1, quads=True).triangulate().clean()
    centres = cube.cell_centers().points
    out = []
    for name, axis, value in (("xmin", 0, 0.0), ("xmax", 0, size), ("ymin", 1, 0.0), ("ymax", 1, size),
                              ("zmin", 2, 0.0), ("zmax", 2, size)):
        ids = np.flatnonzero(np.isclose(centres[:, axis], value))
        out.append((name, cube.extract_cells(ids).extract_surface(algorithm=None)))
    return out


def two_spheres() -> pv.PolyData:
    """Two overlapping closed spheres in one surface: 172 self-intersecting triangles."""
    a = pv.Sphere(radius=0.5, theta_resolution=20, phi_resolution=20)
    b = pv.Sphere(radius=0.5, center=(0.3, 0, 0), theta_resolution=20, phi_resolution=20)
    return (a + b).clean()


def _sphere(n: int = 24) -> pv.PolyData:
    return pv.Sphere(radius=0.5, theta_resolution=n, phi_resolution=n).clean()


def _with_triangles(points: np.ndarray, triangles: np.ndarray) -> pv.PolyData:
    return pv.PolyData(np.asarray(points, dtype=float), faces=np.hstack([np.full((len(triangles), 1), 3), triangles]).ravel())


def sphere_with_holes() -> pv.PolyData:
    """A sphere with two holes (6 and 1 triangles removed)."""
    s = _sphere()
    t = tris(s)
    centres = s.cell_centers().points
    hole = np.argsort(np.linalg.norm(centres - (0.5, 0, 0), axis=1))[:6]
    other = np.argsort(np.linalg.norm(centres - (-0.5, 0, 0), axis=1))[:1]
    return _with_triangles(s.points, np.delete(t, np.concatenate([hole, other]), axis=0))


def sphere_with_flipped_patch() -> pv.PolyData:
    """A sphere whose 10 triangles nearest +z are reversed (inconsistent orientation)."""
    s = _sphere()
    t = tris(s).copy()
    patch = np.argsort(np.linalg.norm(s.cell_centers().points - (0, 0, 0.5), axis=1))[:10]
    t[patch] = t[patch][:, ::-1]
    return _with_triangles(s.points, t)


def sphere_with_duplicates() -> pv.PolyData:
    """A sphere with 5 triangles stored twice."""
    s = _sphere()
    t = tris(s)
    return _with_triangles(s.points, np.vstack([t, t[:5]]))


BROKEN = {
    "holes": sphere_with_holes,
    "flipped patch": sphere_with_flipped_patch,
    "duplicated faces": sphere_with_duplicates,
    "self-intersection": two_spheres,
}
