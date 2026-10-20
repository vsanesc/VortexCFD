"""Geometry of the user refinement volumes (D-103; numpy and pyvista, no Qt).

The shapes are core.model's BoxShape, CylinderShape, SphereShape and ConeShape, in metres. This module
answers which points a shape contains, its exact volume, how much of it lies inside the far-field domain
(sampled), its outline for the viewer, and the cone the "Add wake volume" helper proposes.
"""

import math

import numpy as np
import pyvista as pv

from vortexcfd.core.model import BoxShape, ConeShape, CylinderShape, SphereShape
from vortexcfd.geometry.domain import DomainBox

# Samples per axis of the shape's bounding box when the domain fraction is estimated (about 16,000
# points; the fraction is exact for a shape wholly inside or outside a box domain).
FRACTION_SAMPLES = 25
OUTLINE_SEGMENTS = 32

# The wake helper's defaults (D-103) [NUMERICS-REVIEW]: the cone runs this many reference lengths L
# downstream of the parts' rear, starts with the parts' largest half-extent across the flow (y or z) as
# radius, ends this many times wider, and asks for this many part surface cells as its cell size.
WAKE_LENGTH_L = 2.0
WAKE_END_RADIUS_FACTOR = 1.5
WAKE_SIZE_FACTOR = 2.0


def _arr(v) -> np.ndarray:
    return np.asarray(v, dtype=float)


def box_axes(shape: BoxShape) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The box's own unit axes (e1, e2, e3) after its pitch and yaw (BoxShape.axes)."""
    e1, e2, e3 = shape.axes()
    return _arr(e1), _arr(e2), _arr(e3)


def box_corners(shape: BoxShape) -> np.ndarray:
    e = box_axes(shape)
    half = _arr(shape.size) / 2
    c = _arr(shape.centre)
    return np.array([c + sx * half[0] * e[0] + sy * half[1] * e[1] + sz * half[2] * e[2]
                     for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])


def bounds(shape) -> tuple[float, float, float, float, float, float]:
    """The axis-aligned bounding box (xmin, xmax, ymin, ymax, zmin, zmax)."""
    if isinstance(shape, BoxShape):
        pts = box_corners(shape)
        lo, hi = pts.min(axis=0), pts.max(axis=0)
    elif isinstance(shape, SphereShape):
        lo, hi = _arr(shape.centre) - shape.radius, _arr(shape.centre) + shape.radius
    else:
        p1, p2 = _arr(shape.point1), _arr(shape.point2)
        r1, r2 = (shape.radius, shape.radius) if isinstance(shape, CylinderShape) else (shape.radius1, shape.radius2)
        axis = (p2 - p1) / np.linalg.norm(p2 - p1)
        # the end discs' extent along each world axis: r * sqrt(1 - a_i^2)
        spread = np.sqrt(np.clip(1.0 - axis ** 2, 0.0, 1.0))
        lo = np.minimum(p1 - r1 * spread, p2 - r2 * spread)
        hi = np.maximum(p1 + r1 * spread, p2 + r2 * spread)
    return (float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1]), float(lo[2]), float(hi[2]))


def contains(shape, points) -> np.ndarray:
    """Boolean mask of the points (n, 3) inside the shape (its boundary included)."""
    p = np.atleast_2d(_arr(points))
    if isinstance(shape, BoxShape):
        d = p - _arr(shape.centre)
        half = _arr(shape.size) / 2 * (1 + 1e-12)
        return np.all([np.abs(d @ e) <= h for e, h in zip(box_axes(shape), half)], axis=0)
    if isinstance(shape, SphereShape):
        return np.linalg.norm(p - _arr(shape.centre), axis=1) <= shape.radius * (1 + 1e-12)
    p1, p2 = _arr(shape.point1), _arr(shape.point2)
    axis = p2 - p1
    length2 = float(axis @ axis)
    t = (p - p1) @ axis / length2
    radial = np.linalg.norm(p - p1 - np.outer(t, axis), axis=1)
    r = (np.full(len(p), shape.radius) if isinstance(shape, CylinderShape)
         else shape.radius1 + np.clip(t, 0, 1) * (shape.radius2 - shape.radius1))
    return (t >= -1e-12) & (t <= 1 + 1e-12) & (radial <= r * (1 + 1e-12))


def volume(shape) -> float:
    """The shape's exact volume (m3)."""
    if isinstance(shape, BoxShape):
        return float(np.prod(shape.size))
    if isinstance(shape, SphereShape):
        return 4.0 / 3.0 * math.pi * shape.radius ** 3
    h = float(np.linalg.norm(_arr(shape.point2) - _arr(shape.point1)))
    if isinstance(shape, CylinderShape):
        return math.pi * shape.radius ** 2 * h
    r1, r2 = shape.radius1, shape.radius2
    return math.pi * h / 3.0 * (r1 * r1 + r1 * r2 + r2 * r2)


def inside_domain(box: DomainBox, points) -> np.ndarray:
    """Vectorised DomainBox.contains (box, bullet and C-type, D-078)."""
    p = np.atleast_2d(_arr(points))
    if box.bounds is None:
        return np.zeros(len(p), dtype=bool)
    b = box.bounds
    tol = 1e-9
    mask = ((p[:, 0] >= b[0] - tol) & (p[:, 0] <= b[1] + tol) & (p[:, 1] >= b[2] - tol) & (p[:, 1] <= b[3] + tol)
            & (p[:, 2] >= b[4] - tol) & (p[:, 2] <= b[5] + tol))
    if not box.rounded:
        return mask
    ax, ay, az = box.axis
    r2 = (box.radius_m + tol) ** 2
    front = p[:, 0] < ax
    if box.shape == "bullet":
        radial = (p[:, 1] - ay) ** 2 + (p[:, 2] - az) ** 2
        ok = np.where(front, (p[:, 0] - ax) ** 2 + radial <= r2, radial <= r2)
    else:  # c_type
        ok = np.where(front, (p[:, 0] - ax) ** 2 + (p[:, 2] - az) ** 2 <= r2, True)
    return mask & ok


def _overlap(a, b) -> bool:
    return all(a[2 * i] <= b[2 * i + 1] and b[2 * i] <= a[2 * i + 1] for i in range(3))


def _inside_box(a, b) -> bool:
    return all(a[2 * i] >= b[2 * i] and a[2 * i + 1] <= b[2 * i + 1] for i in range(3))


def domain_fraction(shape, box: DomainBox, samples: int = FRACTION_SAMPLES) -> float:
    """The share of the shape's volume inside the domain: 0 when its bounding box misses the domain's, 1
    when it lies within a box domain's bounds, otherwise sampled on a regular grid of ``samples`` points
    per axis over the shape's bounding box (the points inside the shape; at least one such point is
    taken, the shape's centre)."""
    if box.bounds is None:
        return 0.0
    sb = bounds(shape)
    if not _overlap(sb, box.bounds):
        return 0.0
    if not box.rounded and _inside_box(sb, box.bounds):
        return 1.0
    axes = [np.linspace(sb[2 * i], sb[2 * i + 1], samples + 2)[1:-1] for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    grid = grid[contains(shape, grid)]
    if not len(grid):
        grid = np.atleast_2d(_arr([(sb[0] + sb[1]) / 2, (sb[2] + sb[3]) / 2, (sb[4] + sb[5]) / 2]))
    return float(inside_domain(box, grid).mean())


def _frustum(p1, p2, r1: float, r2: float, segments: int = OUTLINE_SEGMENTS) -> pv.PolyData:
    """A closed (truncated) cone or cylinder surface between p1 and p2."""
    p1, p2 = _arr(p1), _arr(p2)
    axis = (p2 - p1) / np.linalg.norm(p2 - p1)
    helper = _arr((1.0, 0.0, 0.0)) if abs(axis[0]) < 0.9 else _arr((0.0, 1.0, 0.0))
    u = np.cross(axis, helper)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    angles = np.linspace(0.0, 2 * math.pi, segments, endpoint=False)
    ring = np.outer(np.cos(angles), u) + np.outer(np.sin(angles), v)
    points = np.vstack([p1 + r1 * ring, p2 + r2 * ring, p1, p2])
    n = segments
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces += [4, i, j, n + j, n + i]
        faces += [3, 2 * n, j, i]
        faces += [3, 2 * n + 1, n + i, n + j]
    return pv.PolyData(points, np.array(faces))


def outline(shape) -> pv.PolyData:
    """The shape's surface for the viewer (drawn translucent with its edges)."""
    if isinstance(shape, BoxShape):
        c = box_corners(shape)  # index = 4 sx + 2 sy + sz, each 0 or 1
        quads = ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5))
        return pv.PolyData(c, np.hstack([[4, *q] for q in quads]))
    if isinstance(shape, SphereShape):
        return pv.Sphere(radius=shape.radius, center=shape.centre, theta_resolution=OUTLINE_SEGMENTS,
                         phi_resolution=OUTLINE_SEGMENTS // 2)
    if isinstance(shape, CylinderShape):
        return _frustum(shape.point1, shape.point2, shape.radius, shape.radius)
    return _frustum(shape.point1, shape.point2, shape.radius1, shape.radius2)


def rear_point(parts_bounds, direction) -> np.ndarray:
    """Where the line from the centre of the parts' box along ``direction`` leaves the box."""
    b = parts_bounds
    c = _arr([(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2])
    d = _arr(direction) / np.linalg.norm(direction)
    steps = []
    for i in range(3):
        if abs(d[i]) > 1e-12:
            steps.append(((b[2 * i + 1] if d[i] > 0 else b[2 * i]) - c[i]) / d[i])
    return c + min(steps) * d


def wake_cone(parts_bounds, direction, surface_size: float) -> tuple[ConeShape, float]:
    """(the wake cone, its target cell size) behind the parts' box for the free-stream ``direction``
    (D-103): from the parts' rear along the flow, WAKE_LENGTH_L x L long (L: the box's largest extent),
    start radius = the largest of the box's half-width (y) and half-height (z), end radius
    WAKE_END_RADIUS_FACTOR x that; target size WAKE_SIZE_FACTOR x the part surface cell size."""
    b = parts_bounds
    d = _arr(direction) / np.linalg.norm(direction)
    length = max(b[1] - b[0], b[3] - b[2], b[5] - b[4])
    start = rear_point(b, d)
    end = start + WAKE_LENGTH_L * length * d
    r1 = max((b[3] - b[2]) / 2, (b[5] - b[4]) / 2)
    cone = ConeShape(point1=tuple(float(x) for x in start), point2=tuple(float(x) for x in end),
                     radius1=float(r1), radius2=float(WAKE_END_RADIUS_FACTOR * r1))
    return cone, WAKE_SIZE_FACTOR * surface_size
