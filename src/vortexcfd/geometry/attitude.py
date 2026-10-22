"""The angle of attack as a rotation of the geometry (D-120; numpy and pyvista, no Qt). [NUMERICS-REVIEW]

The flow is always along +x. A positive angle of attack alpha turns the parts nose up about the y axis
through the reference centre of rotation c (CofR, Reports.center_of_rotation or the centre of the parts'
bounding box): p' = c + R (p - c) with R = R_y(alpha) = [[cos a, 0, sin a], [0, 1, 0], [-sin a, 0, cos a]],
the right-handed rotation about +y. A point ahead of c (x < c_x) moves up (+z): a symmetric airfoil whose
leading edge is at the smaller x gets a positive lift (+z) at a positive alpha. Directions (normals, box
axes) turn with R alone.

The project's stored geometry never changes: the meshing case gets rotated copies of the surfaces, the
junction curves and the body-frame refinement volumes (Mesh frame "body"); "wind"-frame volumes stay as
they are.
"""

import math

import numpy as np
import pyvista as pv

from vortexcfd.core.model import BoxShape, ConeShape, CylinderShape, OrientedBoxShape, SphereShape

Vector = tuple[float, float, float]


def rotation_matrix(alpha_deg: float) -> np.ndarray:
    """R_y(alpha): the nose-up rotation of a positive angle of attack (see the module docstring)."""
    a = math.radians(alpha_deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def rotate_points(points, alpha_deg: float, centre: Vector) -> np.ndarray:
    """Points (n, 3) turned by alpha about the y axis through ``centre``."""
    p = np.atleast_2d(np.asarray(points, dtype=float))
    c = np.asarray(centre, dtype=float)
    return (p - c) @ rotation_matrix(alpha_deg).T + c


def rotate_vector(vector, alpha_deg: float) -> Vector:
    """A direction turned by alpha (no translation)."""
    v = rotation_matrix(alpha_deg) @ np.asarray(vector, dtype=float)
    return float(v[0]), float(v[1]), float(v[2])


def body_axes(alpha_deg: float) -> tuple[Vector, Vector]:
    """(x_body, z_body): the parts' own x and z axes in the wind (global) axes at angle of attack alpha:
    (cos a, 0, -sin a) and (sin a, 0, cos a)."""
    return rotate_vector((1.0, 0.0, 0.0), alpha_deg), rotate_vector((0.0, 0.0, 1.0), alpha_deg)


def rotate_surface(mesh: pv.PolyData, alpha_deg: float, centre: Vector) -> pv.PolyData:
    """A rotated copy of a surface (``mesh`` itself, often a cached load, is never changed). Point and cell
    vector arrays with three components named like normals are turned too; the triangle order (and so the
    orientation of every face) is kept."""
    out = mesh.copy(deep=True)
    if alpha_deg == 0.0:
        return out
    out.points = rotate_points(np.asarray(mesh.points), alpha_deg, centre)
    rot = rotation_matrix(alpha_deg)
    for data in (out.point_data, out.cell_data):
        for name in list(data.keys()):
            values = np.asarray(data[name])
            if values.ndim == 2 and values.shape[1] == 3 and "normal" in name.lower():
                data[name] = values @ rot.T
    return out


def rotate_bounds(bounds, alpha_deg: float, centre: Vector) -> tuple[float, float, float, float, float, float]:
    """The axis-aligned box of a rotated box (its eight corners turned); larger than the rotated surface's
    own box, used only where a surface is not at hand."""
    b = bounds
    corners = np.array([(x, y, z) for x in (b[0], b[1]) for y in (b[2], b[3]) for z in (b[4], b[5])])
    p = rotate_points(corners, alpha_deg, centre)
    lo, hi = p.min(axis=0), p.max(axis=0)
    return float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1]), float(lo[2]), float(hi[2])


def _point(p, alpha_deg: float, centre: Vector) -> Vector:
    r = rotate_points([p], alpha_deg, centre)[0]
    return float(r[0]), float(r[1]), float(r[2])


def rotate_shape(shape, alpha_deg: float, centre: Vector):
    """A refinement volume shape (core.model) turned with the parts: a box becomes an OrientedBoxShape (its
    axes turned, so any pitch and yaw stay exact), the other shapes have their points turned."""
    if alpha_deg == 0.0:
        return shape
    if isinstance(shape, BoxShape):
        e1, _e2, e3 = shape.axes()
        return OrientedBoxShape(centre=_point(shape.centre, alpha_deg, centre), size=shape.size,
                                e1=rotate_vector(e1, alpha_deg), e3=rotate_vector(e3, alpha_deg))
    if isinstance(shape, SphereShape):
        return shape.model_copy(update={"centre": _point(shape.centre, alpha_deg, centre)})
    if isinstance(shape, (CylinderShape, ConeShape)):
        return shape.model_copy(update={"point1": _point(shape.point1, alpha_deg, centre),
                                        "point2": _point(shape.point2, alpha_deg, centre)})
    raise TypeError(f"unknown refinement volume shape {type(shape).__name__}")


class Attitude:
    """The parts' rotation of a project: ``alpha_deg`` about the y axis through ``centre`` (the CofR)."""

    __slots__ = ("alpha_deg", "centre")

    def __init__(self, alpha_deg: float, centre: Vector) -> None:
        self.alpha_deg = float(alpha_deg)
        self.centre = (float(centre[0]), float(centre[1]), float(centre[2]))

    def __repr__(self) -> str:
        return f"Attitude(alpha_deg={self.alpha_deg!r}, centre={self.centre!r})"

    @property
    def rotated(self) -> bool:
        return self.alpha_deg != 0.0

    def surface(self, mesh: pv.PolyData) -> pv.PolyData:
        return rotate_surface(mesh, self.alpha_deg, self.centre) if self.rotated else mesh

    def points(self, points) -> np.ndarray:
        return rotate_points(points, self.alpha_deg, self.centre)

    def shape(self, shape):
        return rotate_shape(shape, self.alpha_deg, self.centre)

    def edge_mesh_text(self, text: str, object_name: str) -> str:
        """A featureEdgeMesh's text (as written by geometry/surface_prep) with its points turned."""
        from vortexcfd.geometry.surface_prep import edge_mesh_text, parse_edge_mesh

        points, edges = parse_edge_mesh(text)
        if self.rotated and len(points):
            points = self.points(points)
        return edge_mesh_text(points[edges] if len(edges) else np.zeros((0, 2, 3)), object_name)
