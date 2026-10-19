"""The reference surface of a local benchmark case (D-094). No Qt.

A local case is measured against a clean reference CAD file of the same model (the trimmed export of
a multi-component aircraft, say). The reference may itself be several closed solids that overlap; its
outer skin is the part of their surfaces that lies outside every other solid, found by point
classification (VTK's enclosed-points test on each solid's closed tessellation), not by a boolean
operation, so it does not share the CAD union's code path.

From the reference come:
- the outer skin, a fine tessellation (1e-5 of the diagonal, 2 degrees) in metres, for the fidelity
  distances in both directions;
- the solids' closed tessellations, for "inside another component" tests;
- l_ref, the geometric mean chord of the wing: the streamwise (x) chord of plane sections y = const,
  evenly spaced over the wing's span, averaged (planform area / span);
- the zones: junction bands around the solids' intersection curves (OpenCASCADE sections, the parts
  inside a third solid dropped), the wing's trailing-edge band around the line through the most
  downstream point of each section outside the other solids, and the wing tips (bands at the ends of
  its span).
Coordinates: x along the flow, y spanwise, z up (as the public cases).
"""

import hashlib
import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.bench.cases import INF, Zone
from vortexcfd.geometry.cad import read_cad, tessellate

FINE_DEFLECTION_FRACTION = 1e-5  # of the diagonal (as the public cases' CAD reference, D-082)
FINE_ANGLE_DEG = 2.0
CHORD_SECTIONS = 101  # plane sections y = const over the wing's span
CURVE_DEFLECTION_FRACTION = 1e-5  # discretisation of the intersection curves
TRAILING_EDGE_SECTIONS = 101
# Triangles whose corners lie on both sides of another body are split until their edges are shorter
# than this fraction of the diagonal, so the outer skin follows the intersection curves closely.
SPLIT_FRACTION = 2e-4
MAX_SPLIT_DEPTH = 16


@dataclass
class ReferenceSurface:
    path: Path
    components: dict[str, int]  # component name -> body index
    unit_to_metre: float
    skin: pv.PolyData  # outer skin, metres, cell array "body"
    bodies: list[pv.PolyData]  # closed tessellation per body, metres
    curves: dict[tuple[int, int], np.ndarray] = field(default_factory=dict)  # (i, j) -> segments (n, 2, 3), outer only
    l_ref: float = 0.0
    l_ref_method: str = ""
    zones: tuple[Zone, ...] = ()
    notes: list[str] = field(default_factory=list)

    def inside_any(self, points: np.ndarray, exclude: int | None = None) -> np.ndarray:
        """Points inside at least one body (``exclude``: a body to skip)."""
        pts = np.asarray(points, dtype=float).reshape(-1, 3)
        out = np.zeros(len(pts), dtype=bool)
        for k, body in enumerate(self.bodies):
            if k != exclude and len(pts):
                out |= inside(pts, body)
        return out


def inside(points: np.ndarray, closed: pv.PolyData) -> np.ndarray:
    """Points strictly inside a closed surface (vtkSelectEnclosedPoints; only the points inside its
    bounding box are tested)."""
    import vtk

    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    b = closed.bounds
    box = ((pts[:, 0] >= b[0]) & (pts[:, 0] <= b[1]) & (pts[:, 1] >= b[2]) & (pts[:, 1] <= b[3])
           & (pts[:, 2] >= b[4]) & (pts[:, 2] <= b[5]))
    out = np.zeros(len(pts), dtype=bool)
    if not box.any():
        return out
    cloud = pv.PolyData(pts[box])
    select = vtk.vtkSelectEnclosedPoints()
    select.SetInputData(cloud)
    select.SetSurfaceData(closed)
    select.SetTolerance(1e-9)
    select.CheckSurfaceOff()
    select.Update()
    out[box] = np.asarray(pv.wrap(select.GetOutput()).point_data["SelectedPoints"]).astype(bool)
    return out


def outer_part(mesh: pv.PolyData, is_inside, max_edge: float, curves: np.ndarray | None = None) -> pv.PolyData:
    """The triangles of ``mesh`` outside the region ``is_inside(points) -> bool`` marks. A triangle
    that may straddle the region's boundary (its corners disagree, or one of the boundary ``curves``
    (segments (n, 2, 3)) passes within 0.6 times its longest edge of its centre) is split in four (edge
    midpoints) until its edges are shorter than ``max_edge``; every final triangle is then kept or
    dropped by its centre."""
    from vortexcfd.bench.metrics import segments_distance

    pts = np.asarray(mesh.points, dtype=float)
    tris = np.asarray(mesh.faces).reshape(-1, 4)[:, 1:]
    flags = is_inside(pts)
    done, work = [], tris
    for _depth in range(MAX_SPLIT_DEPTH):
        corner = flags[work]
        mixed = corner.any(axis=1) != corner.all(axis=1)
        p = pts[work]
        longest = np.linalg.norm(p - np.roll(p, 1, axis=1), axis=2).max(axis=1)
        if curves is not None and len(curves):
            near = segments_distance(p.mean(axis=1), curves) <= 0.6 * longest  # > the circumradius
            mixed |= near
        split = mixed & (longest > max_edge)
        done.append(work[~split])
        if not split.any():
            work = work[:0]
            break
        sub = work[split]
        mids = np.concatenate([(pts[sub[:, a]] + pts[sub[:, b]]) / 2 for a, b in ((0, 1), (1, 2), (2, 0))])
        n, m = len(pts), len(sub)
        ids = n + np.arange(3 * m).reshape(3, m).T  # m01, m12, m20 of each triangle
        pts = np.concatenate([pts, mids])
        flags = np.concatenate([flags, is_inside(mids)])
        a, b, c = sub[:, 0], sub[:, 1], sub[:, 2]
        m01, m12, m20 = ids[:, 0], ids[:, 1], ids[:, 2]
        work = np.concatenate([np.stack(t, axis=1) for t in ((a, m01, m20), (m01, b, m12), (m20, m12, c),
                                                             (m01, m12, m20))])
    if len(work):
        done.append(work)
    final = np.concatenate(done) if done else np.zeros((0, 3), dtype=np.int64)
    centres = pts[final].mean(axis=1)
    keep = final[~is_inside(centres)]
    out = pv.PolyData(pts, faces=np.hstack([np.full((len(keep), 1), 3), keep]).ravel())
    return out.clean(tolerance=0.0)


def _edge_points(edge, deflection: float) -> np.ndarray:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.TopoDS import TopoDS

    curve = BRepAdaptor_Curve(TopoDS.Edge(edge))
    sampler = GCPnts_QuasiUniformDeflection(curve, deflection)
    if not sampler.IsDone() or sampler.NbPoints() < 2:
        a, b = curve.Value(curve.FirstParameter()), curve.Value(curve.LastParameter())
        return np.array([[a.X(), a.Y(), a.Z()], [b.X(), b.Y(), b.Z()]])
    return np.array([[p.X(), p.Y(), p.Z()] for p in (sampler.Value(i) for i in range(1, sampler.NbPoints() + 1))])


def _edges(shape) -> list:
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer

    out, explorer = [], TopExp_Explorer(shape, TopAbs_EDGE)
    while explorer.More():
        out.append(explorer.Current())
        explorer.Next()
    return out


def section_curves(a, b, deflection: float) -> np.ndarray:
    """Segments (n, 2, 3), model units, of the intersection curves of two solids' surfaces."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section

    section = BRepAlgoAPI_Section(a, b)
    section.Build()
    if not section.IsDone():
        return np.zeros((0, 2, 3))
    segments = []
    for edge in _edges(section.Shape()):
        pts = _edge_points(edge, deflection)
        segments.append(np.stack([pts[:-1], pts[1:]], axis=1))
    return np.concatenate(segments) if segments else np.zeros((0, 2, 3))


def plane_section_points(mesh: pv.PolyData, y: float) -> np.ndarray:
    """Points of the section of a tessellated body by the plane y = const."""
    cut = mesh.slice(normal=(0.0, 1.0, 0.0), origin=(0.0, y, 0.0))
    return np.asarray(cut.points, dtype=float) if cut.n_points else np.zeros((0, 3))


def _solid(body_shape):
    """The body as a solid (a body that is a shell or loose faces is sewn and closed first)."""
    from OCP.TopAbs import TopAbs_SOLID

    if body_shape.ShapeType() == TopAbs_SOLID:
        return body_shape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    sew = BRepBuilderAPI_Sewing(1e-6)
    sew.Add(body_shape)
    sew.Perform()
    explorer = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    if not explorer.More():
        raise ValueError("a reference body has no shell")
    fix = ShapeFix_Solid(BRepBuilderAPI_MakeSolid(TopoDS.Shell(explorer.Current())).Solid())
    fix.Perform()
    return fix.Solid()


def mean_chord(mesh: pv.PolyData, sections: int = CHORD_SECTIONS) -> float:
    """Geometric mean chord of a tessellated wing body: the mean of the x extents of ``sections``
    plane sections y = const evenly spaced over its span (half a step in from each end)."""
    y_min, y_max = _span(mesh)
    step = (y_max - y_min) / sections
    chords = []
    for k in range(sections):
        pts = plane_section_points(mesh, y_min + (k + 0.5) * step)
        if len(pts):
            chords.append(float(np.ptp(pts[:, 0])))
    if not chords:
        raise ValueError("no section of the wing body")
    return float(np.mean(chords))


def _span(mesh: pv.PolyData) -> tuple[float, float]:
    return float(mesh.bounds[2]), float(mesh.bounds[3])


def load_reference(path: Path, components: dict[str, int], zones: dict | None = None,
                   l_ref: dict | None = None) -> ReferenceSurface:
    """Analyse a reference CAD file. ``components``: component name -> body index; ``zones``:
    {"band": fraction of l_ref, "junctions": {zone name: component}, "trailing_edge": component,
    "tips": component}; ``l_ref``: {"mean_chord": component}."""
    zones = zones or {}
    model = read_cad(Path(path))
    scale = 1e-3 if model.units == "mm" else 1.0
    solids = [_solid(b.shape) for b in model.bodies]
    bodies = []
    for k in range(len(model.bodies)):
        mesh = tessellate(model, FINE_DEFLECTION_FRACTION * model.diagonal, FINE_ANGLE_DEG, [k])
        mesh.cell_data.clear()
        bodies.append(mesh.scale(scale, inplace=False))
    ref = ReferenceSurface(Path(path), dict(components), scale, pv.PolyData(), bodies)
    # Intersection curves of every pair (all of them bound the outer skin's pieces).
    deflection = CURVE_DEFLECTION_FRACTION * model.diagonal
    raw: dict[tuple[int, int], np.ndarray] = {}
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            seg = section_curves(solids[i], solids[j], deflection) * scale
            if len(seg):
                raw[(i, j)] = seg
    # Outer skin: the parts of each body outside every other body.
    split = SPLIT_FRACTION * model.diagonal * scale
    pieces = []
    for k, body in enumerate(bodies):
        own = [s for (i, j), s in raw.items() if k in (i, j)]
        piece = outer_part(body, lambda pts, k=k: ref.inside_any(pts, exclude=k), split,
                           np.concatenate(own) if own else None)
        piece.cell_data["body"] = np.full(piece.n_cells, k, dtype=np.int32)
        pieces.append(piece)
    ref.skin = pv.merge(pieces).clean(tolerance=0.0) if pieces else pv.PolyData()
    # The curves on the outer skin: without the parts inside a third body.
    for (i, j), seg in raw.items():
        middle = seg.mean(axis=1)
        hidden = np.zeros(len(seg), dtype=bool)
        for k, body in enumerate(bodies):
            if k not in (i, j):
                hidden |= inside(middle, body)
        if (~hidden).any():
            ref.curves[(i, j)] = seg[~hidden]
    # l_ref: the mean chord of a component.
    chord_of = (l_ref or {}).get("mean_chord")
    if chord_of is not None:
        k = components[chord_of]
        lo, hi = _span(bodies[k])
        ref.l_ref = mean_chord(bodies[k])
        ref.l_ref_method = (f"geometric mean chord of '{chord_of}': mean x extent of {CHORD_SECTIONS} plane sections "
                            f"y = const of its fine tessellation, evenly spaced over its span ({hi - lo:.4g} m), "
                            "i.e. planform area / span")
    if zones and ref.l_ref > 0:
        ref.zones = _zones(ref, solids, zones, deflection)
    return ref


def _zones(ref: ReferenceSurface, solids: list, spec: dict, deflection: float) -> tuple[Zone, ...]:
    band = float(spec.get("band", 0.05)) * ref.l_ref
    out = []
    for name, comp in (spec.get("junctions") or {}).items():
        k = ref.components[comp]
        segs = [s for (i, j), s in ref.curves.items() if k in (i, j)]
        others = sorted(n for n, idx in ref.components.items() if idx != k and (min(k, idx), max(k, idx)) in ref.curves)
        segments = tuple((tuple(a), tuple(b)) for s in segs for a, b in s)
        out.append(Zone(name, f"within {band:.4g} m ({spec.get('band', 0.05):g} l_ref) of the intersection curves of "
                              f"'{comp}' with {', '.join(repr(o) for o in others) or 'nothing'} (outer skin)",
                        segments=segments, width=band))
    te = spec.get("trailing_edge")
    if te is not None:
        k = ref.components[te]
        lo, hi = _span(ref.bodies[k])
        step = (hi - lo) / TRAILING_EDGE_SECTIONS
        points = []
        for s in range(TRAILING_EDGE_SECTIONS + 1):
            y = min(max(lo + s * step, lo + 1e-6 * step), hi - 1e-6 * step)
            pts = plane_section_points(ref.bodies[k], y)
            points.append(pts[np.argmax(pts[:, 0])] if len(pts) else None)
        outside = [p is not None and not ref.inside_any(p[None], exclude=k)[0] for p in points]
        segments = tuple((tuple(points[s]), tuple(points[s + 1])) for s in range(TRAILING_EDGE_SECTIONS)
                         if outside[s] and outside[s + 1])
        out.append(Zone("trailing_edge", f"within {band:.4g} m of the trailing-edge line of '{te}' (the most downstream "
                                         f"point of {TRAILING_EDGE_SECTIONS + 1} sections y = const) outside the "
                                         "other components", segments=segments, width=band))
    tips = spec.get("tips")
    if tips is not None:
        lo, hi = _span(ref.bodies[ref.components[tips]])
        out.append(Zone("tips", f"within {band:.4g} m of the span ends of '{tips}' (y = {lo:.4g} and {hi:.4g} m)",
                        boxes=((-INF, INF, hi - band, INF, -INF, INF), (-INF, INF, -INF, lo + band, -INF, INF))))
    return tuple(out)


# Bump when the analysis changes, so cached results are not reused.
ANALYSIS_VERSION = 1


def cached_reference(path: Path, components: dict[str, int], zones: dict | None = None, l_ref: dict | None = None,
                     cache: Path | None = None) -> ReferenceSurface:
    """``load_reference`` with a pickle cache in ``cache`` keyed by the file's content, the settings
    and ANALYSIS_VERSION (the analysis takes minutes on a large model; every local case of a run
    shares its reference). ``cache`` None: no cache."""
    if cache is None:
        return load_reference(path, components, zones, l_ref)
    h = hashlib.sha256(Path(path).read_bytes())
    h.update(json.dumps([components, zones, l_ref, ANALYSIS_VERSION, FINE_DEFLECTION_FRACTION, FINE_ANGLE_DEG,
                         SPLIT_FRACTION, CHORD_SECTIONS, TRAILING_EDGE_SECTIONS], sort_keys=True).encode())
    target = Path(cache) / f"{h.hexdigest()[:24]}.pickle"
    if target.is_file():
        try:
            with open(target, "rb") as fh:
                return pickle.load(fh)
        except Exception:  # a damaged or incompatible cache entry is recomputed
            target.unlink(missing_ok=True)
    ref = load_reference(path, components, zones, l_ref)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(ref, fh)
    tmp.replace(target)
    return ref
