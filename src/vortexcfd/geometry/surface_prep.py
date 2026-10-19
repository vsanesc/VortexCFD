"""Surface preparation of a multi-component model: diagnostics and intersection features (D-093).

No Qt. Works on the components' triangulated surfaces in metres (one per Part, as snappyHexMesh sees
them):

- ``diagnose``: per component whether it is closed (open and non-manifold edges), the gaps smaller
  than the surface cell size (open boundary loops, and components that come closer than a cell
  without touching), the area thinner than a surface cell (features smaller than the cell), and
  the pairs of components that intersect each other with the length of their intersection curve;
- ``intersection_curves``: the curves where the components cross each other (geometry/intersections),
  written as a featureEdgeMesh (``write_edge_mesh``) that snappyHexMesh snaps to.

The CAD union strategy is in geometry/cad_union.py.
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.geometry.intersections import intersection_segments

# Thickness probes: at most this many triangles per component are probed for the local thickness.
THICKNESS_SAMPLES = 4000
# Points closer than this fraction of the curves' extent are merged in the written edge mesh.
MERGE_FRACTION = 1e-9
# Intersection curves of a pair shorter than this fraction of the model's diagonal are numerical
# noise of surfaces that only touch (e.g. coplanar caps): the pair is reported as touching.
MIN_CURVE_FRACTION = 1e-6


def triangles(mesh: pv.PolyData) -> np.ndarray:
    return np.asarray(mesh.faces).reshape(-1, 4)[:, 1:]


@dataclass(frozen=True)
class Curves:
    """Intersection curves: ``segments`` (n, 2, 3) in metres and the component pair of each
    (indices into the components, lower first)."""

    segments: np.ndarray
    pairs: np.ndarray

    def length(self, mask: np.ndarray | None = None) -> float:
        s = self.segments if mask is None else self.segments[mask]
        return float(np.linalg.norm(s[:, 1] - s[:, 0], axis=1).sum()) if len(s) else 0.0

    def pair_lengths(self) -> dict[tuple[int, int], float]:
        out: dict[tuple[int, int], float] = {}
        for a, b in {tuple(int(v) for v in p) for p in self.pairs}:
            out[(a, b)] = self.length((self.pairs[:, 0] == a) & (self.pairs[:, 1] == b))
        return dict(sorted(out.items()))


def combined(meshes: list[pv.PolyData]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(points, triangles, component of each triangle) of several surfaces, points not merged."""
    pts, tris, comp = [], [], []
    offset = 0
    for k, mesh in enumerate(meshes):
        t = triangles(mesh)
        pts.append(np.asarray(mesh.points, dtype=float))
        tris.append(t + offset)
        comp.append(np.full(len(t), k, dtype=np.int64))
        offset += mesh.n_points
    if not pts:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), np.zeros(0, dtype=np.int64)
    return np.concatenate(pts), np.concatenate(tris), np.concatenate(comp)


# A point is inside a surface when its generalised winding number exceeds this (1 inside a closed,
# outward-oriented surface, 0 outside; small holes and gaps move it only a little).
INSIDE_WINDING = 0.5
WINDING_CHUNK = 2_000_000  # point-triangle pairs per chunk


def winding_numbers(points: np.ndarray, mesh: pv.PolyData) -> np.ndarray:
    """Generalised winding number of ``points`` with respect to a triangulated surface (Jacobson et
    al. 2013: the sum of the triangles' signed solid angles over 4 pi), robust to small holes."""
    pts = np.asarray(points, dtype=float)
    tris = triangles(mesh)
    corners = np.asarray(mesh.points, dtype=float)[tris]  # (m, 3, 3)
    out = np.zeros(len(pts))
    step = max(1, WINDING_CHUNK // max(len(tris), 1))
    for s in range(0, len(pts), step):
        p = pts[s:s + step]
        a, b, c = (corners[None, :, k, :] - p[:, None, :] for k in range(3))
        la, lb, lc = (np.linalg.norm(v, axis=2) for v in (a, b, c))
        det = np.einsum("pmi,pmi->pm", a, np.cross(b, c))
        div = (la * lb * lc + np.einsum("pmi,pmi->pm", a, b) * lc + np.einsum("pmi,pmi->pm", b, c) * la
               + np.einsum("pmi,pmi->pm", c, a) * lb)
        out[s:s + step] = (2.0 * np.arctan2(det, div)).sum(axis=1) / (4.0 * np.pi)
    return out


def intersection_curves(meshes: list[pv.PolyData], subset: list[int] | None = None,
                        drop_hidden: bool = True) -> Curves:
    """The curves where the surfaces (one per component) cross each other. With ``subset``, only the
    pairs that involve at least one component of ``subset``. With ``drop_hidden``, segments whose
    middle lies inside a third component are left out: they are not on the outer skin, and as snap
    features they would pull that component's surface inwards."""
    pts, tris, comp = combined(meshes)
    segments, pairs = intersection_segments(pts, tris, comp)
    if drop_hidden and len(segments) and len(meshes) > 2:
        middle = segments.mean(axis=1)
        hidden = np.zeros(len(segments), dtype=bool)
        for k, mesh in enumerate(meshes):
            others = (pairs[:, 0] != k) & (pairs[:, 1] != k) & ~hidden
            if others.any():
                hidden[others] |= np.abs(winding_numbers(middle[others], mesh)) > INSIDE_WINDING
        segments, pairs = segments[~hidden], pairs[~hidden]
    if len(pairs):  # drop the noise of pairs that only touch
        diag = float(np.linalg.norm(np.ptp(pts, axis=0)))
        lengths = Curves(segments, pairs).pair_lengths()
        noise = [ab for ab, length in lengths.items() if length < MIN_CURVE_FRACTION * diag]
        keep = np.ones(len(pairs), dtype=bool)
        for a, b in noise:
            keep &= ~((pairs[:, 0] == a) & (pairs[:, 1] == b))
        segments, pairs = segments[keep], pairs[keep]
    if subset is not None and len(pairs):
        keep = np.isin(pairs[:, 0], subset) | np.isin(pairs[:, 1], subset)
        segments, pairs = segments[keep], pairs[keep]
    return Curves(segments, pairs)


def edge_mesh(segments: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(points, edges) of segments, with coincident end points merged."""
    if not len(segments):
        return np.zeros((0, 3)), np.zeros((0, 2), dtype=np.int64)
    ends = segments.reshape(-1, 3)
    extent = float(np.ptp(ends, axis=0).max()) or 1.0
    key = np.round(ends / (MERGE_FRACTION * extent * 1e3)).astype(np.int64)
    _unique, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    points = ends[first]
    edges = inverse.reshape(-1, 2)
    edges = edges[edges[:, 0] != edges[:, 1]]
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    return points, edges


def write_edge_mesh(path: Path, segments: np.ndarray, comment: str = "") -> int:
    """Write segments (metres) as an OpenFOAM featureEdgeMesh (.eMesh); returns the edge count."""
    points, edges = edge_mesh(segments)
    rows = "\n".join(f"({x:.9g} {y:.9g} {z:.9g})" for x, y, z in points)
    lines = "\n".join(f"({a} {b})" for a, b in edges)
    text = (
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n    class       featureEdgeMesh;\n"
        f"    object      {Path(path).name};\n}}\n"
        + (f"// {comment}\n" if comment else "")
        + f"{len(points)}\n(\n{rows}\n)\n{len(edges)}\n(\n{lines}\n)\n"
    )
    Path(path).write_text(text, encoding="utf-8")
    return len(edges)


def read_edge_mesh(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(points, edges) of a featureEdgeMesh written by ``write_edge_mesh``."""
    text = Path(path).read_text(encoding="utf-8")
    body = text[text.index("}") + 1:]
    body = "\n".join(line for line in body.splitlines() if not line.strip().startswith("//"))
    tokens = body.replace("(", " ( ").replace(")", " ) ").split()
    n = int(tokens[0])
    values = [float(t) for t in tokens[1:] if t not in "()"]
    points = np.array(values[:3 * n]).reshape(n, 3)
    m = int(values[3 * n])
    edges = np.array(values[3 * n + 1:3 * n + 1 + 2 * m], dtype=np.int64).reshape(m, 2)
    return points, edges


# -- diagnostics -------------------------------------------------------------------------------


def _edges(tris: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    e = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
    return np.unique(e, axis=0, return_counts=True)


def boundary_loops(mesh: pv.PolyData) -> list[np.ndarray]:
    """The point ids of every connected chain of open edges (edges used by one triangle)."""
    edges, counts = _edges(triangles(mesh))
    open_edges = edges[counts == 1]
    if not len(open_edges):
        return []
    ids = np.unique(open_edges)
    index = {int(p): i for i, p in enumerate(ids)}
    parent = list(range(len(ids)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in open_edges:
        ra, rb = find(index[int(a)]), find(index[int(b)])
        if ra != rb:
            parent[ra] = rb
    roots = np.array([find(i) for i in range(len(ids))])
    return [ids[roots == r] for r in np.unique(roots)]


def _loop_width(points: np.ndarray) -> float:
    """The width of a single open loop (a hole or a slit): its smaller in-plane extent (principal
    axes of its points)."""
    if len(points) < 3:
        return 0.0
    centred = points - points.mean(axis=0)
    _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
    proj = centred @ vt[:2].T
    return float(np.ptp(proj, axis=0).min())


def _point_segments_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Distance from each point to the nearest of the segments a[i]-b[i] (numpy, in chunks)."""
    out = np.empty(len(points))
    ab = b - a
    denom = np.maximum((ab * ab).sum(axis=1), 1e-300)
    for s in range(0, len(points), 256):
        p = points[s:s + 256, None, :]
        t = np.clip(((p - a[None]) * ab[None]).sum(axis=2) / denom[None], 0.0, 1.0)
        d = np.linalg.norm(p - (a[None] + t[..., None] * ab[None]), axis=2)
        out[s:s + 256] = d.min(axis=1)
    return out


def gap_widths(mesh: pv.PolyData) -> list[float]:
    """Width of every gap of an open surface: for two or more open loops, the median distance from
    each loop's points to the nearest open edge of another loop (unsewn edges facing each other); for
    a single loop, its smaller in-plane extent."""
    loops = boundary_loops(mesh)
    pts = np.asarray(mesh.points, dtype=float)
    if len(loops) == 1:
        return [_loop_width(pts[loops[0]])]
    edges, counts = _edges(triangles(mesh))
    open_edges = edges[counts == 1]
    owner = np.full(len(pts), -1)
    for k, loop in enumerate(loops):
        owner[loop] = k
    widths = []
    for k, loop in enumerate(loops):
        others = open_edges[owner[open_edges[:, 0]] != k]
        d = _point_segments_distance(pts[loop], pts[others[:, 0]], pts[others[:, 1]])
        widths.append(float(np.median(d)))
    return widths


def thickness_sample(mesh: pv.PolyData, samples: int = THICKNESS_SAMPLES, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """(local thickness, triangle area) of up to ``samples`` triangles: the distance from a triangle's
    centre to the nearest other crossing of the surface along its normal, in either direction (the
    faces of an unsewn component need not be oriented consistently). On a convex closed part that is
    its thickness; across a concave region it is the gap between facing surfaces. inf when neither
    ray meets the surface. Uses VTK's static cell locator."""
    import vtk

    tris = triangles(mesh)
    if not len(tris):
        return np.zeros(0), np.zeros(0)
    pts = np.asarray(mesh.points, dtype=float)
    a, b, c = pts[tris[:, 0]], pts[tris[:, 1]], pts[tris[:, 2]]
    normal = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(normal, axis=1)
    chosen = np.arange(len(tris))
    if len(chosen) > samples:
        chosen = np.random.default_rng(seed).choice(len(tris), samples, replace=False)
    unit = normal[chosen] / np.maximum(2 * area[chosen], 1e-300)[:, None]
    centre = (a + b + c)[chosen] / 3.0
    diag = float(np.linalg.norm(np.ptp(pts, axis=0))) or 1.0
    locator = vtk.vtkStaticCellLocator()
    locator.SetDataSet(mesh)
    locator.BuildLocator()
    hits, cells = vtk.vtkPoints(), vtk.vtkIdList()
    out = np.full(len(chosen), np.inf)
    eps = 1e-7 * diag
    for i, (p, n) in enumerate(zip(centre, unit)):
        for sign in (-1.0, 1.0):
            locator.IntersectWithLine(p + sign * eps * n, p + sign * 2 * diag * n, eps, hits, cells)
            for k in range(hits.GetNumberOfPoints()):
                d = float(np.linalg.norm(np.array(hits.GetPoint(k)) - p))
                if d > 2 * eps:
                    out[i] = min(out[i], d)
    return out, area[chosen]


@dataclass
class ComponentReport:
    name: str
    triangles: int
    open_edges: int
    non_manifold_edges: int
    closed: bool
    gaps: list[float] = field(default_factory=list)  # widths below the cell size, m
    open_loops: int = 0
    thin_area_fraction: float = 0.0  # share of the probed area thinner than the cell size
    min_thickness: float | None = None  # m, the thinnest probe (None: no closed probe)
    sews_closed: bool | None = None  # CAD components: the faces sew into a closed solid (None: not CAD)
    free_edges_after_sewing: int | None = None

    def rows(self) -> list[tuple[str, str]]:
        closed = "yes" if self.closed else (f"no: {self.open_edges} open edges" if self.open_edges else "no")
        if self.non_manifold_edges:
            closed += f", {self.non_manifold_edges} non-manifold edges"
        rows = [(f"{self.name}: closed", closed)]
        if self.sews_closed is not None:
            rows.append((f"{self.name}: CAD faces sew closed",
                         "yes" if self.sews_closed else f"no ({self.free_edges_after_sewing} free edges)"))
        if self.gaps:
            rows.append((f"{self.name}: gaps below the cell size",
                         ", ".join(f"{g * 1000:.3g} mm" for g in sorted(self.gaps))))
        if self.thin_area_fraction > 0:
            rows.append((f"{self.name}: thinner than a cell (or facing surfaces closer)",
                         f"{self.thin_area_fraction:.1%} of the area (min {self.min_thickness * 1000:.3g} mm)"
                         if self.min_thickness is not None else f"{self.thin_area_fraction:.1%} of the area"))
        return rows


@dataclass
class Diagnostics:
    cell_size: float  # m, the surface cell size the checks compare with
    components: list[ComponentReport]
    intersecting: list[tuple[str, str, float, float]]  # (a, b, curve length, of it on the outer skin; m)
    near: list[tuple[str, str, float]]  # (a, b, distance in m): closer than a cell, not touching

    def rows(self) -> list[tuple[str, str]]:
        rows = [("Surface cell size", f"{self.cell_size * 1000:.3g} mm")]
        for comp in self.components:
            rows += comp.rows()
        rows.append(("Intersecting pairs", "; ".join(
            f"{a} / {b} ({length:.3g} m" + (f", {outer:.3g} m outside the other parts)" if outer < length - 1e-9
                                            else ")") for a, b, length, outer in self.intersecting) or "none"))
        if self.near:
            rows.append(("Gaps between components (closer than a cell, not crossing)",
                         "; ".join(f"{a} / {b} ({'touching' if d <= 0 else f'{d * 1000:.3g} mm'})"
                                   for a, b, d in self.near)))
        return rows


def _min_distance(a: pv.PolyData, b: pv.PolyData) -> float:
    _cells, closest = b.find_closest_cell(np.asarray(a.points), return_closest_point=True)
    return float(np.linalg.norm(np.asarray(a.points) - closest, axis=1).min())


def _boxes_within(a: pv.PolyData, b: pv.PolyData, margin: float) -> bool:
    ba, bb = a.bounds, b.bounds
    return all(ba[2 * k] - margin <= bb[2 * k + 1] and bb[2 * k] - margin <= ba[2 * k + 1] for k in range(3))


def diagnose(names: list[str], meshes: list[pv.PolyData], cell_size: float, curves: Curves | None = None,
             sewing: dict[str, tuple[bool, int]] | None = None, outer: Curves | None = None) -> Diagnostics:
    """Diagnostics of the components (surfaces in metres) against the surface cell size (m).
    ``curves``: all their intersection curves (``drop_hidden`` False) and ``outer`` the ones on the
    outer skin, when already computed; ``sewing``: per CAD component, (sews closed, free edges after
    sewing)."""
    curves = curves if curves is not None else intersection_curves(meshes, drop_hidden=False)
    outer = outer if outer is not None else intersection_curves(meshes)
    reports = []
    for name, mesh in zip(names, meshes):
        edges, counts = _edges(triangles(mesh))
        open_edges, non_manifold = int((counts == 1).sum()), int((counts > 2).sum())
        widths = gap_widths(mesh) if open_edges else []
        thick, area = thickness_sample(mesh)
        finite = np.isfinite(thick)
        thin = finite & (thick < cell_size)
        rep = ComponentReport(
            name=name, triangles=int(mesh.n_cells), open_edges=open_edges, non_manifold_edges=non_manifold,
            closed=open_edges == 0 and non_manifold == 0,
            gaps=[w for w in widths if w < cell_size], open_loops=len(boundary_loops(mesh)) if open_edges else 0,
            thin_area_fraction=float(area[thin].sum() / area.sum()) if area.sum() > 0 else 0.0,
            min_thickness=float(thick[finite].min()) if finite.any() else None,
        )
        if sewing and name in sewing:
            rep.sews_closed, rep.free_edges_after_sewing = sewing[name]
        reports.append(rep)
    pair_lengths = curves.pair_lengths()
    outer_lengths = outer.pair_lengths()
    intersecting = [(names[a], names[b], length, outer_lengths.get((a, b), 0.0)) for (a, b), length in pair_lengths.items()]
    near = []
    for a in range(len(meshes)):
        for b in range(a + 1, len(meshes)):
            if (a, b) in pair_lengths or not _boxes_within(meshes[a], meshes[b], cell_size):
                continue
            d = min(_min_distance(meshes[a], meshes[b]), _min_distance(meshes[b], meshes[a]))
            if d < cell_size:
                near.append((names[a], names[b], d))
    return Diagnostics(cell_size, reports, intersecting, near)
