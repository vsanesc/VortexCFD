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
