"""The closed, triangulated surface of a far-field domain with one region per boundary role (no Qt, D-078).

``domain_surface`` returns a PyVista surface whose cell array ``role`` indexes ``box.roles``. The
rounded shapes are built from one "D" profile in the plane that contains the flow direction x: a
quarter (bullet) or half (C-type) circle of radius R in front, centred on ``box.axis``, then a
straight part up to the outlet plane x = ``box.x_rear``:

- bullet: the profile (front arc, cylinder, rear disc) revolved about the x axis through
  ``box.axis``; with symmetry only the half y >= axis y, closed by the D-shaped cut in that plane.
- C-type: the D shape in the x-z plane (front half-disc, flat top and bottom, flat rear) extruded
  along y over ``box.y_span``, closed by two D-shaped spanwise sides.

Seam vertices are computed once and shared, so the surface is closed and manifold.
"""

import math

import numpy as np
import pyvista as pv

from vortexcfd.geometry.domain import DomainBox, face_corners

ROLE_ARRAY = "role"
# Resolution: segments of the quarter circle of the front, of the rear radius, and around the full
# circle of the bullet (all well inside 1 % of the analytic volume).
ARC_SEGMENTS = 16
REAR_SEGMENTS = 8
MAX_STRAIGHT_SEGMENTS = 200


class _Builder:
    """Vertices deduplicated by position (so seams computed twice are one vertex) and triangles."""

    def __init__(self, scale: float) -> None:
        self.tol = max(scale, 1e-12) * 1e-9
        self.index: dict[tuple[int, int, int], int] = {}
        self.points: list[tuple[float, float, float]] = []
        self.tris: list[tuple[int, int, int]] = []
        self.roles: list[int] = []

    def vertex(self, p) -> int:
        key = tuple(int(round(c / self.tol)) for c in p)
        found = self.index.get(key)
        if found is None:
            found = self.index[key] = len(self.points)
            self.points.append((float(p[0]), float(p[1]), float(p[2])))
        return found

    def tri(self, a: int, b: int, c: int, role: int) -> None:
        if a != b and b != c and a != c:
            self.tris.append((a, b, c))
            self.roles.append(role)

    def quad(self, a: int, b: int, c: int, d: int, role: int) -> None:
        self.tri(a, b, c, role)
        self.tri(a, c, d, role)

    def mesh(self) -> pv.PolyData:
        faces = np.hstack([np.full((len(self.tris), 1), 3), np.array(self.tris, dtype=np.int64)]).ravel()
        out = pv.PolyData(np.array(self.points, dtype=float), faces)
        out.cell_data[ROLE_ARRAY] = np.array(self.roles, dtype=np.int32)
        return out


def _profile(box: DomainBox) -> tuple[list[float], list[float], int]:
    """Column x positions and half-heights h of the D profile from the front tip (h = 0) to the rear
    (h = R), and the index of the last arc column (the seam at the axis x)."""
    ax, r = box.axis[0], box.radius_m
    xs, hs = [], []
    for k in range(ARC_SEGMENTS + 1):
        phi = k * (math.pi / 2) / ARC_SEGMENTS
        xs.append(ax - r * math.cos(phi) if k < ARC_SEGMENTS else ax)
        hs.append(r * math.sin(phi) if k < ARC_SEGMENTS else r)
    length = max(0.0, box.x_rear - ax)
    step = r * (math.pi / 2) / ARC_SEGMENTS
    n = min(MAX_STRAIGHT_SEGMENTS, max(1, math.ceil(length / step))) if length > 0 else 0
    for j in range(1, n + 1):
        xs.append(box.x_rear if j == n else ax + length * j / n)
        hs.append(r)
    return xs, hs, ARC_SEGMENTS


def _d_cap(b: _Builder, box: DomainBox, plane, role: int, flip: bool) -> None:
    """The D shape triangulated by columns: column c at xs[c] holds 2 * REAR_SEGMENTS + 1 points from
    the top (h) to the bottom (-h); the tip column is one point. ``plane(x, s)`` maps x and the signed
    offset s (top +h) to a 3D point; ``flip`` reverses the triangles (outward normal)."""
    xs, hs, _ = _profile(box)
    m = 2 * REAR_SEGMENTS
    cols = [[b.vertex(plane(x, h * (1 - 2 * i / m))) for i in range(m + 1)] if h > 0 else [b.vertex(plane(x, 0.0))]
            for x, h in zip(xs, hs)]

    def tri(p, q, s):
        b.tri(*((p, s, q) if flip else (p, q, s)), role)

    for c in range(len(cols) - 1):
        left, right = cols[c], cols[c + 1]
        if len(left) == 1:
            for i in range(m):
                tri(left[0], right[i + 1], right[i])
            continue
        for i in range(m):
            tri(left[i], right[i + 1], right[i])
            tri(left[i], left[i + 1], right[i + 1])


def _role(box: DomainBox, name: str) -> int:
    return box.roles.index(name)


def _bullet(box: DomainBox) -> pv.PolyData:
    ax, ay, az = box.axis
    r = box.radius_m
    b = _Builder(max(box.size))
    xs, hs, seam = _profile(box)
    # profile points (x, h, segment role) from the tip along the arc and cylinder, then down the rear disc
    prof = list(zip(xs, hs))
    prof += [(box.x_rear, r * (1 - j / REAR_SEGMENTS)) for j in range(1, REAR_SEGMENTS + 1)]
    seg_role = ([_role(box, "inlet")] * seam + [_role(box, "farfield")] * (len(xs) - 1 - seam)
                + [_role(box, "outlet")] * REAR_SEGMENTS)
    n_theta = 64
    if box.symmetric:
        thetas = [math.pi * j / (n_theta // 2) for j in range(n_theta // 2 + 1)]
    else:
        thetas = [2 * math.pi * j / n_theta for j in range(n_theta)]

    def point(x, h, t):
        sin_t = 0.0 if t in (0.0, math.pi) else math.sin(t)
        cos_t = 1.0 if t == 0.0 else -1.0 if t == math.pi else math.cos(t)
        return (x, ay + h * sin_t, az + h * cos_t)

    grid = [[b.vertex(point(x, h, t)) for t in thetas] for x, h in prof]
    count = len(thetas) if not box.symmetric else len(thetas) - 1
    for i in range(len(prof) - 1):
        for j in range(count):
            j1 = (j + 1) % len(thetas)
            # outward normals: the profile runs from the tip (-x) to the rear, theta from +z towards +y
            b.quad(grid[i][j], grid[i][j1], grid[i + 1][j1], grid[i + 1][j], seg_role[i])
    if box.symmetric:
        _d_cap(b, box, lambda x, s: (x, ay, az + s), _role(box, "symmetry"), flip=True)
    return b.mesh()


def _c_type(box: DomainBox) -> pv.PolyData:
    ax, _ay, az = box.axis
    y0, y1 = box.y_span
    b = _Builder(max(box.size))
    xs, hs, seam = _profile(box)
    m = 2 * REAR_SEGMENTS
    # the D outline in (x, s), counter-clockwise seen from -y: top from the rear to the tip, bottom
    # from the tip to the rear, then the rear from the bottom up (closing at the rear top)
    loop, roles = [], []
    inlet, far, outlet = _role(box, "inlet"), _role(box, "farfield"), _role(box, "outlet")
    n = len(xs)
    for c in range(n - 1, 0, -1):  # top: columns n-1 .. 1, segment to column c-1
        loop.append((xs[c], hs[c]))
        roles.append(inlet if c - 1 < seam else far)
    loop.append((xs[0], 0.0))  # the tip
    roles.append(inlet)
    for c in range(1, n):  # bottom: columns 1 .. n-1, segment to column c+1
        loop.append((xs[c], -hs[c]))
        roles.append(inlet if c < seam else far)
    roles[-1] = outlet  # the segment leaving the rear bottom corner goes up the rear
    for i in range(m - 1, 0, -1):  # rear interior points from the bottom up
        s = box.radius_m * (1 - 2 * i / m)
        loop.append((box.x_rear, s))
        roles.append(outlet)
    span = y1 - y0
    step = box.radius_m * (math.pi / 2) / ARC_SEGMENTS
    ny = min(MAX_STRAIGHT_SEGMENTS, max(1, math.ceil(span / step)))
    ys = [y0 + span * j / ny if j < ny else y1 for j in range(ny + 1)]
    grid = [[b.vertex((x, y, az + s)) for y in ys] for x, s in loop]
    for i in range(len(loop)):
        i1 = (i + 1) % len(loop)
        for j in range(ny):
            b.quad(grid[i][j], grid[i1][j], grid[i1][j + 1], grid[i][j + 1], roles[i])
    low = _role(box, "symmetry") if box.symmetric else _role(box, "sides")
    _d_cap(b, box, lambda x, s: (x, y0, az + s), low, flip=False)
    _d_cap(b, box, lambda x, s: (x, y1, az + s), _role(box, "sides"), flip=True)
    return b.mesh()


def _box(box: DomainBox, triangulate: bool) -> pv.PolyData:
    b = _Builder(max(box.size))
    quads = []
    for name in box.roles:
        for axis, side in box.boundaries.get(name, ()):
            corners = [b.vertex(p) for p in face_corners(box.bounds, axis, side)]
            quads.append((corners, _role(box, name)))
    if triangulate:
        for corners, role in quads:
            b.quad(*corners, role)
        out = b.mesh()
    else:
        faces = np.hstack([[4, *c] for c, _ in quads])
        out = pv.PolyData(np.array(b.points, dtype=float), faces)
        out.cell_data[ROLE_ARRAY] = np.array([r for _, r in quads], dtype=np.int32)
    return _outward(out)


def _outward(mesh: pv.PolyData) -> pv.PolyData:
    """Consistent outward normals (the role array follows the cells)."""
    out = mesh.compute_normals(cell_normals=True, point_normals=False, consistent_normals=True,
                               auto_orient_normals=True, split_vertices=False)
    for data in (out.point_data, out.cell_data):
        for name in [n for n in data.keys() if n.lower().startswith("normals")]:
            del data[name]
    return out


def domain_surface(box: DomainBox, triangulate: bool = True) -> pv.PolyData:
    """The domain's closed surface with the cell array ``role`` (an index into ``box.roles``). The box
    keeps its six faces as quads when ``triangulate`` is False (for the viewer)."""
    if box.bounds is None:
        raise ValueError("no domain without parts")
    if box.shape == "box":
        return _box(box, triangulate)
    if box.shape == "bullet":
        return _outward(_bullet(box))
    if box.shape == "c_type":
        return _outward(_c_type(box))
    raise ValueError(f"unknown domain shape {box.shape!r}")


def role_names(box: DomainBox, surface: pv.PolyData) -> list[str]:
    """The role name of every cell of ``surface``."""
    return [box.roles[i] for i in np.asarray(surface.cell_data[ROLE_ARRAY])]


def meshing_surface(box: DomainBox, extension: float) -> pv.PolyData:
    """The surface written for snappyHexMesh: with symmetry, the symmetry region is left out (the
    background mesh's y_min face is the exactly planar symmetry patch) and the open edge on the plane is
    extended by ``extension`` through it (a skirt continuing the surface along -y), so the surface
    crosses the background boundary instead of ending on it."""
    surface = domain_surface(box)
    if not box.symmetric or not box.rounded:
        return surface
    roles = np.asarray(surface.cell_data[ROLE_ARRAY])
    keep = roles != _role(box, "symmetry")
    tris = surface.faces.reshape(-1, 4)[:, 1:][keep]
    roles = roles[keep]
    pts = np.asarray(surface.points, dtype=float)
    plane_y = box.bounds[2]
    edges: dict[tuple[int, int], int] = {}
    for t, (a, b_, c) in enumerate(tris):
        for p, q in ((a, b_), (b_, c), (c, a)):
            key = (min(p, q), max(p, q))
            edges[key] = -1 if key in edges else t
    builder_pts = list(map(tuple, pts))
    new_index: dict[int, int] = {}

    def lowered(i: int) -> int:
        if i not in new_index:
            new_index[i] = len(builder_pts)
            x, y, z = pts[i]
            builder_pts.append((x, plane_y - extension, z))
        return new_index[i]

    out_tris, out_roles = [list(t) for t in tris], list(roles)
    tol = 1e-9 * max(box.size)
    for (p, q), t in edges.items():
        if t < 0 or abs(pts[p][1] - plane_y) > tol or abs(pts[q][1] - plane_y) > tol:
            continue
        a, b_, c = tris[t]
        u, v = next((u, v) for u, v in ((a, b_), (b_, c), (c, a)) if {u, v} == {p, q})  # the triangle's direction
        out_tris += [[v, u, lowered(u)], [v, lowered(u), lowered(v)]]
        out_roles += [roles[t], roles[t]]
    faces = np.hstack([np.full((len(out_tris), 1), 3), np.array(out_tris, dtype=np.int64)]).ravel()
    out = pv.PolyData(np.array(builder_pts, dtype=float), faces)
    out.cell_data[ROLE_ARRAY] = np.array(out_roles, dtype=np.int32)
    return out
