"""Surface regions of a Part: per-triangle base ids, region labels and the angle split (no Qt).

A Part's triangles each carry a base id (an STL solid, a CAD face or an angle-split patch); the
ids live in a .npy file next to the geometry (Part.region_ids) whose name holds a hash of its
content, so every edit writes a new file and undo only points the Part back (D-071).
"""

import hashlib
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.core.model import Part

# Label of a triangle outside every region (it stays on the part's own patch).
NO_REGION = -1
# An angle split giving more regions than this is refused (a noisy scan would give thousands).
MAX_SPLIT_REGIONS = 500


class RegionError(Exception):
    """A region operation cannot be applied; the message says why."""


def triangles(mesh: pv.PolyData) -> np.ndarray:
    return np.asarray(mesh.faces).reshape(-1, 4)[:, 1:]


def read_ids(path: Path, n_triangles: int) -> np.ndarray:
    """The base ids stored in ``path``; RegionError when the file does not fit the surface."""
    try:
        ids = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise RegionError(f"Cannot read the region file {Path(path).name}: {exc}") from exc
    if ids.ndim != 1 or len(ids) != n_triangles:
        raise RegionError(f"The region file {Path(path).name} has {len(ids)} entries for a surface "
                          f"of {n_triangles} triangles (the surface file changed)")
    return ids.astype(np.int64)


def write_ids(folder: Path, stem: str, ids: np.ndarray) -> Path:
    """Write ``ids`` as <folder>/<stem>_regions_<hash>.npy (an existing identical file is reused)."""
    ids = np.ascontiguousarray(ids, dtype=np.int32)
    digest = hashlib.sha256(ids.tobytes()).hexdigest()[:12]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}_regions_{digest}.npy"
    if not path.exists():
        np.save(path, ids, allow_pickle=False)
    return path


def base_ids(part: Part, mesh: pv.PolyData, project_dir: Path | None) -> np.ndarray:
    """Base id of every triangle of ``mesh`` (the part's loaded surface): its region file, else 0."""
    if part.region_ids and project_dir is not None:
        return read_ids(Path(project_dir) / part.region_ids, mesh.n_cells)
    return np.zeros(mesh.n_cells, dtype=np.int64)


def region_labels(part: Part, ids: np.ndarray) -> np.ndarray:
    """Index of the region of every triangle (into part.regions), NO_REGION outside all of them."""
    labels = np.full(len(ids), NO_REGION, dtype=np.int64)
    for index, region in enumerate(part.regions):
        if region.members:
            labels[np.isin(ids, region.members)] = index
    return labels


def patch_labels(part: Part, ids: np.ndarray, patches: list[str]) -> np.ndarray:
    """Index into ``patches`` (part.patch_names() order) of every triangle's patch."""
    labels = region_labels(part, ids)
    index_of = {name: i for i, name in enumerate(patches)}
    out = np.full(len(ids), index_of.get(part.name, 0), dtype=np.int64)  # NO_REGION: part's patch
    for index, region in enumerate(part.regions):
        out[labels == index] = index_of[part.region_patch(region)]
    return out


def _edge_neighbours(tris: np.ndarray, n_points: int) -> tuple[np.ndarray, np.ndarray]:
    """Pairs of triangles sharing an edge (manifold edges only: exactly two triangles)."""
    n = len(tris)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    edges.sort(axis=1)
    owner = np.tile(np.arange(n), 3)
    key = edges[:, 0].astype(np.int64) * n_points + edges[:, 1]
    order = np.argsort(key, kind="stable")
    key, owner = key[order], owner[order]
    same = key[1:] == key[:-1]
    first = np.flatnonzero(same)
    # Keep edges shared by exactly two triangles.
    lone = np.ones(len(first), dtype=bool)
    lone &= (first + 2 >= len(key)) | (key[np.minimum(first + 2, len(key) - 1)] != key[first])
    lone &= (first == 0) | (key[np.maximum(first - 1, 0)] != key[first])
    first = first[lone]
    return owner[first], owner[first + 1]


def _components(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Connected components of n nodes joined by the pairs (a, b): label per node (0..k-1)."""
    parent = np.arange(n)

    def find(x: np.ndarray) -> np.ndarray:
        while True:
            up = parent[x]
            if np.array_equal(up, x):
                return x
            parent[x] = parent[up]  # path halving
            x = parent[x]

    a, b = np.asarray(a), np.asarray(b)
    while len(a):
        ra, rb = find(a), find(b)
        differ = ra != rb
        if not differ.any():
            break
        ra, rb = ra[differ], rb[differ]
        lo, hi = np.minimum(ra, rb), np.maximum(ra, rb)
        parent[hi] = lo  # some writes may be overwritten: loop until every pair agrees
        a, b = a[differ], b[differ]
    roots = find(np.arange(n))
    return np.unique(roots, return_inverse=True)[1]


def angle_split(mesh: pv.PolyData, feature_angle: float, selected: np.ndarray | None = None,
                groups: np.ndarray | None = None) -> np.ndarray:
    """Split triangles into patches separated by edges sharper than ``feature_angle`` (degrees).

    Two triangles sharing an edge stay together when their normals differ by less than the angle.
    ``selected`` (bool per triangle) limits the split to those triangles (others get -1);
    ``groups`` (an id per triangle, e.g. the CAD face) keeps each group whole. Returns a label per
    triangle, 0..k-1 in order of first appearance.
    """
    tris = triangles(mesh)
    n = len(tris)
    pts = np.asarray(mesh.points, dtype=float)
    normals = np.cross(pts[tris[:, 1]] - pts[tris[:, 0]], pts[tris[:, 2]] - pts[tris[:, 0]])
    length = np.linalg.norm(normals, axis=1)
    normals = normals / np.where(length > 0, length, 1.0)[:, None]
    a, b = _edge_neighbours(tris, len(pts))
    smooth = np.einsum("ij,ij->i", normals[a], normals[b]) >= np.cos(np.radians(feature_angle))
    a, b = a[smooth], b[smooth]
    if groups is not None:  # join every triangle of a group to the group's first triangle
        g = np.asarray(groups)
        first = np.unique(g, return_index=True)
        head = first[1][np.searchsorted(first[0], g)]
        a, b = np.concatenate([a, np.arange(n)]), np.concatenate([b, head])
    sel = np.ones(n, dtype=bool) if selected is None else np.asarray(selected, dtype=bool)
    keep = sel[a] & sel[b]
    labels = _components(n, a[keep], b[keep])
    out = np.full(n, -1, dtype=np.int64)
    idx = np.flatnonzero(sel)
    if len(idx):
        _, first_seen, inverse = np.unique(labels[idx], return_index=True, return_inverse=True)
        rank = np.argsort(np.argsort(first_seen))
        out[idx] = rank[inverse]
    return out


def transfer_ids(old_mesh: pv.PolyData, old_ids: np.ndarray, new_mesh: pv.PolyData) -> np.ndarray:
    """Base ids for a changed surface (e.g. repaired): each new triangle takes the id of the old
    triangle closest to its centre."""
    if new_mesh.n_cells == 0:
        return np.zeros(0, dtype=np.int64)
    centres = new_mesh.cell_centers().points
    closest = old_mesh.find_closest_cell(centres)
    return np.asarray(old_ids)[np.asarray(closest, dtype=np.int64)]


def write_patch_stl(path: Path, mesh: pv.PolyData, labels: np.ndarray, names: list[str]) -> None:
    """Write an ASCII STL with one `solid <name>` block per patch (labels index ``names``); a patch
    without triangles is left out."""
    tris = triangles(mesh)
    pts = np.asarray(mesh.points, dtype=float)
    a, b, c = pts[tris[:, 0]], pts[tris[:, 1]], pts[tris[:, 2]]
    normals = np.cross(b - a, c - a)
    length = np.linalg.norm(normals, axis=1)
    normals = normals / np.where(length > 0, length, 1.0)[:, None]
    with open(path, "w", encoding="ascii") as fh:
        for index, name in enumerate(names):
            sel = np.flatnonzero(labels == index)
            if not len(sel):
                continue
            fh.write(f"solid {name}\n")
            rows = np.hstack([normals[sel], a[sel], b[sel], c[sel]])
            fh.writelines(
                "facet normal %.9g %.9g %.9g\n outer loop\n  vertex %.9g %.9g %.9g\n  vertex %.9g %.9g %.9g\n"
                "  vertex %.9g %.9g %.9g\n endloop\nendfacet\n" % tuple(r) for r in rows)
            fh.write(f"endsolid {name}\n")
