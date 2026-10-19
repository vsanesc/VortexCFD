"""Self-intersection detection for triangulated surfaces (numpy only).

Two triangles that share no vertex intersect when an edge of one crosses the other. Candidate pairs
come from a uniform grid (each triangle is binned into the cells its bounding box overlaps); the
exact test is Moller-Trumbore on the 6 edges of every pair. Coplanar overlaps are not detected
(duplicate faces are reported by the surface checks).

pymeshfix's ``PyTMesh.select_intersecting_triangles`` was tried first: in pymeshfix 0.18.1 it
returns uninitialised indices, so the triangles cannot be highlighted (Task 3.1).
"""

import numpy as np

# Above this many triangles the check is skipped (measured: docs/STATUS.md, D-069).
MAX_TRIANGLES = 2_000_000
# Grid cell edge in multiples of the mean triangle bounding-box diagonal.
CELL_FACTOR = 1.0
# Candidate pairs tested per chunk (memory: about 0.5 kB per pair).
PAIR_CHUNK = 500_000
# Relative tolerance of the barycentric test: crossings at an edge's end points are not counted.
EPS = 1e-9


def _cell_pairs(tris: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Candidate pairs (i < j) of triangles sharing a grid cell, unique, as an (n, 2) array."""
    corners = pts[tris]  # (n, 3, 3)
    lo, hi = corners.min(axis=1), corners.max(axis=1)
    diag = np.linalg.norm(hi - lo, axis=1)
    h = max(float(diag.mean()) * CELL_FACTOR, 1e-300)
    origin = lo.min(axis=0)
    ilo = np.floor((lo - origin) / h).astype(np.int64)
    ihi = np.floor((hi - origin) / h).astype(np.int64)
    dims = ihi.max(axis=0) + 1
    span = ihi - ilo + 1
    counts = span.prod(axis=1)
    owner = np.repeat(np.arange(len(tris)), counts)
    # Offset of each (triangle, cell) entry inside its triangle's box of cells.
    start = np.repeat(np.cumsum(counts) - counts, counts)
    local = np.arange(len(owner)) - start
    sp = span[owner]
    cx = ilo[owner, 0] + local % sp[:, 0]
    cy = ilo[owner, 1] + (local // sp[:, 0]) % sp[:, 1]
    cz = ilo[owner, 2] + local // (sp[:, 0] * sp[:, 1])
    key = (cx * dims[1] + cy) * dims[2] + cz
    order = np.argsort(key, kind="stable")
    key, owner = key[order], owner[order]
    bounds = np.flatnonzero(np.diff(key)) + 1
    starts = np.concatenate([[0], bounds])
    sizes = np.diff(np.concatenate([starts, [len(key)]]))
    pairs = []
    for size in range(2, int(sizes.max()) + 1 if len(sizes) else 0):
        group_starts = starts[sizes == size]
        if not len(group_starts):
            continue
        a, b = np.triu_indices(size, k=1)
        members = owner[group_starts[:, None] + np.arange(size)]  # (groups, size)
        i, j = members[:, a].ravel(), members[:, b].ravel()
        cell = np.repeat(key[group_starts], len(a))
        # Each pair is kept once: in the cell holding the lower corner of the overlap of the two
        # boxes (boxes that do not overlap have no such cell and are dropped).
        corner = np.maximum(ilo[i], ilo[j])
        overlap = (corner <= np.minimum(ihi[i], ihi[j])).all(axis=1)
        home = (corner[:, 0] * dims[1] + corner[:, 1]) * dims[2] + corner[:, 2]
        keep = overlap & (home == cell)
        pairs.append(np.stack([i[keep], j[keep]], axis=1))
    if not pairs:
        return np.empty((0, 2), dtype=np.int64)
    return np.concatenate(pairs)


def _edges_cross(p0: np.ndarray, p1: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Segment p0-p1 crosses triangle tri (Moller-Trumbore), strictly inside both, per row."""
    v0, v1, v2 = tri[:, 0], tri[:, 1], tri[:, 2]
    e1, e2 = v1 - v0, v2 - v0
    d = p1 - p0
    pv = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, pv)
    scale = np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1) * np.linalg.norm(d, axis=1)
    ok = np.abs(det) > 1e-12 * np.maximum(scale, 1e-300)  # not parallel (coplanar pairs: not found)
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    tv = p0 - v0
    u = np.einsum("ij,ij->i", tv, pv) * inv
    qv = np.cross(tv, e1)
    v = np.einsum("ij,ij->i", d, qv) * inv
    t = np.einsum("ij,ij->i", e2, qv) * inv
    return ok & (u > EPS) & (v > EPS) & (u + v < 1 - EPS) & (t > EPS) & (t < 1 - EPS)


def _pairs_intersect(pts: np.ndarray, tris: np.ndarray, pairs: np.ndarray) -> np.ndarray:
    a, b = pts[tris[pairs[:, 0]]], pts[tris[pairs[:, 1]]]
    hit = np.zeros(len(pairs), dtype=bool)
    for first, second in ((a, b), (b, a)):
        for i, j in ((0, 1), (1, 2), (2, 0)):
            todo = ~hit
            if not todo.any():
                break
            hit[todo] |= _edges_cross(first[todo, i], first[todo, j], second[todo])
    return hit


def intersecting_triangles(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Sorted indices of the triangles that cross another triangle sharing none of their vertices.

    Args:
        points: (n, 3) point coordinates (coincident points merged, as load_surface does).
        triangles: (m, 3) point ids.
    """
    pts = np.asarray(points, dtype=float)
    tris = np.asarray(triangles, dtype=np.int64)
    if len(tris) < 2:
        return np.empty(0, dtype=np.int64)
    pairs = _cell_pairs(tris, pts)
    corners = pts[tris]
    lo, hi = corners.min(axis=1), corners.max(axis=1)
    found = []
    for s in range(0, len(pairs), PAIR_CHUNK):
        i, j = pairs[s:s + PAIR_CHUNK, 0], pairs[s:s + PAIR_CHUNK, 1]
        keep = np.ones(len(i), dtype=bool)
        for axis in range(3):  # real (not cell) bounding boxes overlap
            keep &= (lo[i, axis] <= hi[j, axis]) & (lo[j, axis] <= hi[i, axis])
        i, j = i[keep], j[keep]
        ta, tb = tris[i], tris[j]
        shared = np.zeros(len(i), dtype=bool)
        for x in range(3):
            for y in range(3):
                shared |= ta[:, x] == tb[:, y]
        chunk = np.stack([i[~shared], j[~shared]], axis=1)
        if len(chunk):
            found.append(chunk[_pairs_intersect(pts, tris, chunk)].ravel())
    if not found:
        return np.empty(0, dtype=np.int64)
    return np.unique(np.concatenate(found))


# -- intersection curves between surfaces (surface preparation, D-093) ----------------------------


def _candidate_pairs(pts: np.ndarray, tris: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Grid candidate pairs of triangles of DIFFERENT groups whose bounding boxes overlap."""
    pairs = _cell_pairs(tris, pts)
    if not len(pairs):
        return pairs
    pairs = pairs[groups[pairs[:, 0]] != groups[pairs[:, 1]]]
    corners = pts[tris]
    lo, hi = corners.min(axis=1), corners.max(axis=1)
    i, j = pairs[:, 0], pairs[:, 1]
    keep = np.ones(len(pairs), dtype=bool)
    for axis in range(3):
        keep &= (lo[i, axis] <= hi[j, axis]) & (lo[j, axis] <= hi[i, axis])
    return pairs[keep]


def _plane_cut(tri: np.ndarray, normal: np.ndarray, offset: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Where each triangle (n, 3, 3) crosses the plane normal . x = offset (one per row): the two
    crossing points and whether the triangle straddles the plane. A vertex exactly on the plane is
    moved to its positive side (a symbolic perturbation), so a straddling triangle always has exactly
    two crossing edges."""
    s = np.einsum("nkj,nj->nk", tri, normal) - offset[:, None]
    scale = np.abs(s).max(axis=1, keepdims=True)
    s = np.where(np.abs(s) <= 1e-12 * np.maximum(scale, 1e-300), 1e-12 * np.maximum(scale, 1e-300), s)
    straddle = (s.min(axis=1) < 0) & (s.max(axis=1) > 0)
    points = []
    crosses = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        sa, sb = s[:, a], s[:, b]
        c = (sa * sb) < 0
        t = np.where(c, sa / np.where(c, sa - sb, 1.0), 0.0)
        points.append(tri[:, a] + t[:, None] * (tri[:, b] - tri[:, a]))
        crosses.append(c)
    crosses = np.stack(crosses, axis=1)  # (n, 3)
    points = np.stack(points, axis=1)  # (n, 3, 3)
    order = np.argsort(~crosses, axis=1, kind="stable")  # crossing edges first
    rows = np.arange(len(tri))
    return points[rows, order[:, 0]], points[rows, order[:, 1]], straddle


def _segments_of_pairs(pts: np.ndarray, tris: np.ndarray, pairs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The intersection segment (2 points) of every crossing pair of triangles, and the mask of the
    pairs that cross. Coplanar pairs are not handled (no segment)."""
    a, b = pts[tris[pairs[:, 0]]], pts[tris[pairs[:, 1]]]
    na = np.cross(a[:, 1] - a[:, 0], a[:, 2] - a[:, 0])
    nb = np.cross(b[:, 1] - b[:, 0], b[:, 2] - b[:, 0])
    direction = np.cross(na, nb)
    dlen = np.linalg.norm(direction, axis=1)
    scale = np.linalg.norm(na, axis=1) * np.linalg.norm(nb, axis=1)
    ok = dlen > 1e-9 * np.maximum(scale, 1e-300)
    a0, a1, sa = _plane_cut(a, nb, np.einsum("ij,ij->i", nb, b[:, 0]))
    b0, b1, sb = _plane_cut(b, na, np.einsum("ij,ij->i", na, a[:, 0]))
    ok &= sa & sb
    unit = direction / np.where(dlen > 0, dlen, 1.0)[:, None]
    ta0, ta1 = np.einsum("ij,ij->i", a0, unit), np.einsum("ij,ij->i", a1, unit)
    tb0, tb1 = np.einsum("ij,ij->i", b0, unit), np.einsum("ij,ij->i", b1, unit)
    lo = np.maximum(np.minimum(ta0, ta1), np.minimum(tb0, tb1))
    hi = np.minimum(np.maximum(ta0, ta1), np.maximum(tb0, tb1))
    ok &= hi > lo
    p_lo = a0 + (lo - ta0)[:, None] * unit
    p_hi = a0 + (hi - ta0)[:, None] * unit
    return np.stack([p_lo, p_hi], axis=1), ok


def intersection_segments(points: np.ndarray, triangles: np.ndarray, groups: np.ndarray
                          ) -> tuple[np.ndarray, np.ndarray]:
    """The curves where triangles of different ``groups`` (one label per triangle, e.g. the
    component) cross each other, as segments.

    Returns (segments (n, 2, 3), group pairs (n, 2), the lower label first). Candidate pairs come
    from the same grid as the self-intersection check; the segment of a crossing pair is the overlap
    of the two triangles' cuts by each other's plane. Coplanar overlaps give no segment.
    """
    pts = np.asarray(points, dtype=float)
    tris = np.asarray(triangles, dtype=np.int64)
    groups = np.asarray(groups)
    empty = np.empty((0, 2, 3)), np.empty((0, 2), dtype=groups.dtype if len(groups) else np.int64)
    if len(tris) < 2:
        return empty
    pairs = _candidate_pairs(pts, tris, groups)
    out_s, out_g = [], []
    for s in range(0, len(pairs), PAIR_CHUNK):
        chunk = pairs[s:s + PAIR_CHUNK]
        segments, ok = _segments_of_pairs(pts, tris, chunk)
        if ok.any():
            g = np.sort(np.stack([groups[chunk[ok, 0]], groups[chunk[ok, 1]]], axis=1), axis=1)
            out_s.append(segments[ok])
            out_g.append(g)
    if not out_s:
        return empty
    return np.concatenate(out_s), np.concatenate(out_g)
