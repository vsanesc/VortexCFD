"""Prism layers counted from the mesh itself, for any mesher (phase 5.3, D-102; in foam/ since task 5.4b,
where the app measures the achieved first cell after meshing, D-109). No Qt.

snappyHexMesh writes its layer fields (nSurfaceLayers, thickness, thicknessFraction; D-082) but cfMesh
writes none, so the cfMesh evaluation counts the layers from constant/polyMesh: from every wall face
the column of cells above it is walked outwards. A cell belongs to the stack while it is a prism on the
current face (it has a face with no point in common with the current face, at least as many points as
the wall face and a normal within about 45 degrees of the wall normal, the "top" face; the most parallel
one when a split side face also qualifies) and is thin: its height (the top face centre's distance from the current face
along the wall face normal) is at most ``MAX_ASPECT`` times the square root of the current face's area
and at most ``MAX_GROWTH`` times the height of the layer below it. The walk stops at the first cell that is not, at a boundary, or after ``max_layers`` cells. The same
walk is applied to both meshers' meshes; on snappyHexMesh meshes it is checked against the layer fields.

[NUMERICS-REVIEW] the aspect limit separates layer cells (the y+ stack ends near half a surface cell,
foam/yplus.plan_layers) from the near-cubic core cells above them, and the growth limit (layers grow by
the expansion ratio, 1.2 by default) stops at a refined core cell that is thin only relative to its own
face; a squashed snapped core cell next to the wall still counts as one layer.
"""

import numpy as np

from vortexcfd.foam.polymesh import PolyMesh, face_geometry  # noqa: F401 (PolyMesh: re-exported)

MAX_ASPECT = 0.6
MAX_GROWTH = 3.0
MIN_TOP_COS = 0.7  # the top face's normal within about 45 degrees of the wall normal


def _dot3(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Row-wise dot products of (m, 3) arrays, summed in np.dot's order for 3-vectors
    ((a0 b0 + a1 b1) + a2 b2), so every value is the one the per-face walk computed with np.dot."""
    return (a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1]) + a[:, 2] * b[:, 2]


def _padded_rows(values: np.ndarray, first: np.ndarray) -> np.ndarray:
    """CSR rows (``values[first[i]:first[i + 1]]``) as a -1 padded (rows, width) array, order kept.
    ``first[0]`` may be above 0 (cfMesh pads neighbour with -1: those entries sort first)."""
    sizes = np.diff(first)
    out = np.full((len(sizes), max(int(sizes.max(initial=0)), 1)), -1, dtype=np.int64)
    rows = np.repeat(np.arange(len(sizes)), sizes)
    out[rows, np.arange(first[0], first[-1]) - np.repeat(first[:-1], sizes)] = values[first[0]:first[-1]]
    return out


def walk_layers(mesh: PolyMesh, patches: tuple[str, ...], max_layers: int,
                max_aspect: float = MAX_ASPECT, max_growth: float = MAX_GROWTH) -> dict[str, dict[str, np.ndarray]]:
    """Per wall patch: the layer count, the stack thickness (m), the first layer's height (m; 0 without a
    layer), the wall-adjacent cell's height (m, ``first_cell``, every face: see ``first_cell_height``),
    the face area and centre of every face (in the patch's face order).

    All faces of a patch are walked together, one layer per step (docs/REVIEW.md R-25); each step makes,
    per face, the decisions and the floating-point operations of the face-by-face walk, in its order."""
    n_faces = len(mesh.faces)
    n_internal = len(mesh.neighbour)
    n_cells = int(max(mesh.owner.max(initial=-1), mesh.neighbour.max(initial=-1))) + 1
    n_points = len(mesh.points)
    cell_of = np.concatenate([mesh.owner, mesh.neighbour])
    face_of = np.concatenate([np.arange(n_faces), np.arange(n_internal)])
    order = np.argsort(cell_of, kind="stable")
    cell_faces = face_of[order]
    first = np.searchsorted(cell_of[order], np.arange(n_cells + 1))
    faces_of_cell = _padded_rows(cell_faces, first)  # in the order the per-face walk tried them
    centre, vec, area = face_geometry(mesh.points, mesh.faces)
    owner = np.asarray(mesh.owner, dtype=np.int64)
    neighbour = np.asarray(mesh.neighbour, dtype=np.int64)
    sorted_pts = np.sort(mesh.faces, axis=1)
    distinct = (sorted_pts >= 0) & np.concatenate(
        [np.ones((n_faces, 1), dtype=bool), sorted_pts[:, 1:] != sorted_pts[:, :-1]], axis=1)
    n_distinct = distinct.sum(axis=1)  # points per face (the size of its point set)

    out = {}
    for name in patches:
        if name not in mesh.boundary:
            continue
        start, count = mesh.boundary[name]
        layers = np.zeros(count, dtype=np.int64)
        thick = np.zeros(count)
        first_h = np.zeros(count)
        first_cell = np.zeros(count)
        last = np.zeros(count)
        f0 = start + np.arange(count)
        normal = vec[f0] / np.maximum(area[f0], 1e-300)[:, None]
        size0 = n_distinct[f0]
        k = np.arange(count)  # the faces still walking
        f, c = f0.copy(), owner[f0]
        n = 0
        while n < max_layers and len(k):
            # candidate tops: the cell's faces other than the current one with no point in common with it
            # (cell -1: a -1 entry of a padded neighbour list, which has no faces: the walk ends)
            cand = np.where((c >= 0)[:, None], faces_of_cell[np.maximum(c, 0)], -1)
            valid = (cand >= 0) & (cand != f[:, None])
            row, slot = np.nonzero(valid)
            g_pts = mesh.faces[cand[row, slot]]
            f_pts = mesh.faces[f]
            fr, fc = np.nonzero(f_pts >= 0)
            f_keys = fr * n_points + f_pts[fr, fc]
            gr, gc = np.nonzero(g_pts >= 0)
            shared = np.zeros(len(row), dtype=bool)
            shared[gr[np.isin(row[gr] * n_points + g_pts[gr, gc], f_keys)]] = True
            tops = valid.copy()
            tops[row[shared], slot[shared]] = False
            has = tops.any(axis=1)
            # the top is the candidate most parallel to the wall (a split side face can also qualify)
            cos = np.full(cand.shape, -np.inf)
            tr, ts = np.nonzero(tops)
            g_all = cand[tr, ts]
            cos[tr, ts] = np.abs(_dot3(vec[g_all], normal[k[tr]])) / np.maximum(area[g_all], 1e-300)
            pick = np.argmax(cos, axis=1)
            g = cand[np.arange(len(k)), pick]
            best = cos[np.arange(len(k)), pick]
            go = has & ~(best < MIN_TOP_COS) & ~(n_distinct[np.where(has, g, 0)] < size0[k])
            k, f, c, g = k[go], f[go], c[go], g[go]
            h = np.abs(_dot3(centre[g] - centre[f], normal[k]))
            if n == 0:
                first_cell[k] = h  # a prism on the wall face: its height, a layer or not
            thin = ~(h > max_aspect * np.sqrt(area[f]))
            if n > 0:
                thin &= ~(h > max_growth * last[k])
            k, f, c, g, h = k[thin], f[thin], c[thin], g[thin], h[thin]
            last[k] = h
            n += 1
            layers[k] = n
            thick[k] += h
            if n == 1:
                first_h[k] = h
            inside = g < n_internal
            k, c, g = k[inside], c[inside], g[inside]
            c = np.where(owner[g] == c, neighbour[np.minimum(g, n_internal - 1)], owner[g])
            f = g
        for j in np.flatnonzero(first_cell == 0.0):  # not a prism on the wall face (a snapped polyhedron): twice the centre distance
            c0 = int(mesh.owner[start + j])
            own = cell_faces[first[c0]:first[c0 + 1]]
            cc = (centre[own] * area[own, None]).sum(axis=0) / max(float(area[own].sum()), 1e-300)
            first_cell[j] = 2.0 * abs(float(np.dot(cc - centre[start + j], normal[j])))
        out[name] = {"layers": layers, "thickness": thick, "first": first_h, "first_cell": first_cell,
                     "area": area[start:start + count].copy(), "centre": centre[start:start + count].copy()}
    return out


def weighted_percentile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """The area-weighted ``q`` percentile (0-100) of ``values``: the smallest value whose cumulative
    weight reaches q % of the total."""
    order = np.argsort(values)
    cum = np.cumsum(weights[order])
    k = int(np.searchsorted(cum, q / 100.0 * cum[-1]))
    return float(values[order][min(k, len(values) - 1)])


def first_cell_stats(area: np.ndarray, first_cell: np.ndarray, layers: np.ndarray) -> dict:
    """The wall-adjacent cell height over the wall: the area-weighted mean and 95th percentile over every
    face, and the maximum over the faces with at least one layer (m; None without faces).

    [NUMERICS-REVIEW] the height is what OpenFOAM's y+ follows (it evaluates y+ at the cell centre, half
    this height; D-107): on a face without a layer it is the snapped core cell's."""
    if len(area) == 0 or float(area.sum()) <= 0:
        return {"mean_m": None, "p95_m": None, "max_extruded_m": None}
    has = layers > 0
    return {"mean_m": float((area * first_cell).sum() / area.sum()),
            "p95_m": weighted_percentile(first_cell, area, 95.0),
            "max_extruded_m": float(first_cell[has].max()) if has.any() else None}
