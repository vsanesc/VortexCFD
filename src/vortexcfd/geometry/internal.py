"""Internal-flow geometry (D-129): the fluid is the inside of the closed geometry (no Qt).

The closure check, the enclosed volume, a point inside the fluid for snappyHexMesh's locationInMesh, a patch's
area, perimeter and hydraulic diameter, and the 2D section of a part with each segment's patch.
"""

from collections.abc import Sequence

import numpy as np
import pyvista as pv

Bounds = tuple[float, float, float, float, float, float]

CLOSURE_ADVICE = ("the fluid of an internal-flow analysis is the inside of the geometry: close it with Surface "
                  "Preparation or Repair (Geometry), or add the missing inlet or outlet faces")


def merged_surface(meshes: Sequence[pv.PolyData]) -> pv.PolyData:
    """Every part's surface in one triangulated mesh with coincident points merged (parts that meet along an edge,
    e.g. a separate inlet cap, then close each other)."""
    merged = pv.merge([m.triangulate() for m in meshes], merge_points=False) if len(meshes) > 1 else meshes[0]
    return merged.triangulate().clean(tolerance=1e-9, absolute=False)


def open_edge_count(meshes: Sequence[pv.PolyData]) -> tuple[int, int]:
    """(open edges, non-manifold edges) of the parts' surfaces taken together."""
    surface = merged_surface(meshes)
    open_edges = surface.extract_feature_edges(boundary_edges=True, non_manifold_edges=False,
                                               feature_edges=False, manifold_edges=False)
    non_manifold = surface.extract_feature_edges(boundary_edges=False, non_manifold_edges=True,
                                                 feature_edges=False, manifold_edges=False)
    return open_edges.n_cells, non_manifold.n_cells


def closure_problem(meshes: Sequence[pv.PolyData]) -> str | None:
    """Why the parts do not enclose a fluid volume (open or non-manifold edges), or None."""
    if not meshes:
        return "Import at least one part."
    n_open, n_non_manifold = open_edge_count(meshes)
    if n_open or n_non_manifold:
        found = ", ".join(t for t in (f"{n_open} open edges" if n_open else "",
                                      f"{n_non_manifold} non-manifold edges" if n_non_manifold else "") if t)
        return f"The geometry is not closed ({found}): {CLOSURE_ADVICE}."
    return None


def enclosed_volume(meshes: Sequence[pv.PolyData]) -> float:
    """The volume inside the closed geometry (m3)."""
    return abs(float(merged_surface(meshes).volume))


def inside_point(meshes: Sequence[pv.PolyData], background: Bounds, cells: tuple[int, int, int],
                 offset: tuple[float, float, float], max_candidates: int = 20_000) -> tuple[float, float, float] | None:
    """A point inside the fluid for locationInMesh: among the points at the fraction ``offset`` of the background
    cells (so on no cell face of any refinement level up to 4, mesh_case.LOCATION_OFFSET), the one inside the closed
    geometry farthest from its surface; None when no candidate is inside. At most ``max_candidates`` points are
    tested (every n-th background cell along each axis)."""
    surface = merged_surface(meshes)
    total = cells[0] * cells[1] * cells[2]
    stride = max(1, int(np.ceil((total / max_candidates) ** (1.0 / 3.0))))
    axes = []
    for axis in range(3):
        lo, hi, n = background[2 * axis], background[2 * axis + 1], cells[axis]
        step = (hi - lo) / n
        index = np.arange(0, n, stride if n > stride else 1)
        axes.append(lo + (index + offset[axis]) * step)
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    points = pv.PolyData(grid)
    inside = points.select_interior_points(surface, method="cell_locator", check_surface=False)["selected_points"].astype(bool)
    if not inside.any():
        return None
    candidates = pv.PolyData(grid[inside])
    distance = np.abs(candidates.compute_implicit_distance(surface)["implicit_distance"])
    best = grid[inside][int(np.argmax(distance))]
    return float(best[0]), float(best[1]), float(best[2])


def patch_measures(mesh: pv.PolyData, labels: np.ndarray, label: int, two_d: bool = False) -> tuple[float, float, float]:
    """(area m2, perimeter m, hydraulic diameter m) of the triangles of ``mesh`` with ``labels`` == ``label``.

    3D: D_h = 4 A / P with P the length of the patch's boundary edges (the edges used by one of its triangles).
    2D (D-121): the patch is a strip of the extruded section, its width w = A / (its y extent); a channel of
    height w between two planes has D_h = 2 w (4 w s / 2 s for a span s much larger than w). [NUMERICS-REVIEW]"""
    tri = mesh.triangulate()
    selected = np.flatnonzero(np.asarray(labels) == label)
    if selected.size == 0:
        return 0.0, 0.0, 0.0
    patch = tri.extract_cells(selected).extract_surface(algorithm="dataset_surface").clean(tolerance=1e-9, absolute=False)
    area = float(patch.area)
    if two_d:
        y0, y1 = patch.bounds[2], patch.bounds[3]
        width = area / (y1 - y0) if y1 > y0 else 0.0
        return area, 2.0 * width, 2.0 * width
    edges = patch.extract_feature_edges(boundary_edges=True, non_manifold_edges=False, feature_edges=False,
                                        manifold_edges=False)
    perimeter = float(edges.compute_cell_sizes(length=True, area=False, volume=False)["Length"].sum()) if edges.n_cells else 0.0
    return area, perimeter, (4.0 * area / perimeter if perimeter > 0 else 0.0)


def labelled_section(mesh: pv.PolyData, labels: np.ndarray, loops: list[np.ndarray], y: float) -> list[np.ndarray]:
    """Per section loop ((n, 2) in x-z, from geometry/section.section_loops at ``y``), the label of each segment i
    (from point i to point i + 1): the label of the triangle of ``mesh`` nearest to the segment's midpoint."""
    tri = mesh.triangulate()
    labels = np.asarray(labels)
    out = []
    for loop in loops:
        mid = 0.5 * (loop + np.roll(loop, -1, axis=0))
        points = np.column_stack([mid[:, 0], np.full(len(mid), y), mid[:, 1]])
        cells = tri.find_closest_cell(points)
        out.append(labels[np.asarray(cells)])
    return out


def labelled_slab(loops: list[np.ndarray], segment_labels: list[np.ndarray], y0: float, y1: float,
                  cap_label: int) -> tuple[pv.PolyData, np.ndarray]:
    """The loops extruded from y0 to y1 (geometry/section.slab without its normal orientation step, which may
    reorder cells) with a label per triangle: each side quad's two triangles take their segment's label, the caps
    ``cap_label`` (in the 2D mode they lie outside the one-cell slab mesh)."""
    points, faces, labels, base = [], [], [], 0
    for loop, seg in zip(loops, segment_labels):
        loop = np.asarray(loop, dtype=float)
        n = len(loop)
        p0 = np.column_stack([loop[:, 0], np.full(n, y0), loop[:, 1]])
        p1 = np.column_stack([loop[:, 0], np.full(n, y1), loop[:, 1]])
        points += [p0, p1]
        for i in range(n):
            j = (i + 1) % n
            faces += [3, base + i, base + j, base + n + j, 3, base + i, base + n + j, base + n + i]
            labels += [int(seg[i])] * 2
        for cap in (0, n):  # fan triangulation of each cap (the section loops of a channel are simple polygons)
            cap_ids = np.arange(n) + base + cap
            capped = pv.PolyData(np.vstack([p0, p1])[cap_ids - base], np.hstack([[n], np.arange(n)])).triangulate()
            tris = capped.faces.reshape(-1, 4)[:, 1:] + base + cap
            for t in tris:
                faces += [3, *map(int, t)]
                labels.append(cap_label)
        base += 2 * n
    surface = pv.PolyData(np.vstack(points), np.array(faces))
    return surface, np.asarray(labels, dtype=int)
