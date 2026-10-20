"""cfMesh evaluation case from a project (phase 5.3, benchmark only; Qt-free).

The app meshes with snappyHexMesh (workflow/meshing.prepare_job). ``prepare_cfmesh_job`` writes a
cartesianMesh case into the same <project>/case folder from the same MeshCaseInput (meshing.mesh_inputs),
so the benchmark's evaluation switch can compare the two meshers (benchmarks/RESULT_5.3.md, D-102). The
GUI never calls it.

cartesianMesh meshes the region a closed surface encloses, so its input is one combined surface: the
domain surface (geometry/domain_surface: box, bullet or C-type) plus every part (prepared by the surface
preparation when one is current), one STL solid per patch named as the snappyHexMesh patches. With a
symmetry plane the parts' faces on the plane are left out and the plane is triangulated with holes where
the parts meet it, so the surface stays closed.
"""

import json
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.core.project import Project
from vortexcfd.foam.cfmesh_case import COMBINED_STL, build_cfmesh_files
from vortexcfd.foam.mesh_case import DOMAIN_GUARD_FILE, MeshCaseInput, prepare_case_dir
from vortexcfd.foam.polymesh import PolyMesh
from vortexcfd.geometry import regions
from vortexcfd.geometry.domain import DomainBox
from vortexcfd.geometry.domain_surface import ROLE_ARRAY, domain_surface
from vortexcfd.workflow import meshing

# Points closer than this fraction of the domain's diagonal to the symmetry plane lie on it.
PLANE_TOLERANCE = 1e-7


class CombinedSurfaceError(ValueError):
    """The combined surface cannot be built (e.g. the symmetry plane cannot be triangulated)."""


def _edges_used_once(tris: np.ndarray) -> np.ndarray:
    """(n, 2) edges (vertex ids, in the triangles' own direction) used by exactly one triangle."""
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    key = np.sort(e, axis=1)
    _, inverse, counts = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return e[counts[inverse.ravel()] == 1]


def _loops(edges: np.ndarray) -> list[list[int]]:
    """Chain directed boundary edges into closed loops of vertex ids.

    Raises:
        CombinedSurfaceError: an edge does not close into a simple loop."""
    nxt: dict[int, int] = {}
    for a, b in edges:
        if int(a) in nxt:
            raise CombinedSurfaceError("a boundary vertex on the symmetry plane has two outgoing edges")
        nxt[int(a)] = int(b)
    loops, seen = [], set()
    for start in nxt:
        if start in seen:
            continue
        loop, v = [], start
        while v not in seen:
            seen.add(v)
            loop.append(v)
            if v not in nxt:
                raise CombinedSurfaceError("a boundary loop on the symmetry plane is not closed")
            v = nxt[v]
        if v != start:
            raise CombinedSurfaceError("boundary loops on the symmetry plane cross each other")
        loops.append(loop)
    return loops


def _signed_area(xy: np.ndarray) -> float:
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def triangulate_with_holes(outer: np.ndarray, holes: list[np.ndarray], spacing: float) -> tuple[np.ndarray, np.ndarray]:
    """Constrained Delaunay triangulation (VTK) of the 2D polygon ``outer`` minus ``holes``, with
    interior points on a grid of ``spacing`` (kept half a spacing away from every boundary) so the
    triangles are not all slivers. Returns (points (n, 2), triangles (m, 3)); the boundary points come
    first, in the order given (outer, then each hole), and are never moved or merged.

    Raises:
        CombinedSurfaceError: the triangulation does not cover the polygon (area check)."""
    loops = [outer if _signed_area(outer) > 0 else outer[::-1]]
    loops += [h if _signed_area(h) < 0 else h[::-1] for h in holes]
    boundary = np.concatenate(loops)
    lo, hi = outer.min(axis=0), outer.max(axis=0)
    gx = np.arange(lo[0] + spacing / 2, hi[0], spacing)
    gy = np.arange(lo[1] + spacing / 2, hi[1], spacing)
    grid = np.array([(x, y) for x in gx for y in gy]) if len(gx) and len(gy) else np.zeros((0, 2))
    if len(grid):
        segs = np.concatenate([np.stack([lp, np.roll(lp, -1, axis=0)], axis=1) for lp in loops])
        keep = np.ones(len(grid), dtype=bool)
        for chunk in np.array_split(np.arange(len(grid)), max(1, len(grid) // 2000)):
            p = grid[chunk][:, None, :]
            a, b = segs[None, :, 0, :], segs[None, :, 1, :]
            ab = b - a
            t = np.clip(((p - a) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-300), 0, 1)
            d = np.linalg.norm(p - (a + t[..., None] * ab), axis=-1).min(axis=1)
            keep[chunk] = d > 0.5 * spacing
        grid = grid[keep]
    pts2 = np.concatenate([boundary, grid])
    cloud = pv.PolyData(np.column_stack([pts2, np.zeros(len(pts2))]))
    offsets, faces = 0, []
    for lp in loops:
        faces.append(np.concatenate([[len(lp)], np.arange(offsets, offsets + len(lp))]))
        offsets += len(lp)
    source = pv.PolyData(cloud.points[:len(boundary)].copy(), np.concatenate(faces))
    tri = cloud.delaunay_2d(edge_source=source)
    tris = np.asarray(tri.faces).reshape(-1, 4)[:, 1:]
    xy = np.asarray(tri.points)[:, :2]
    if not np.allclose(xy[:len(boundary)], boundary):
        raise CombinedSurfaceError("the symmetry plane triangulation reordered the boundary points")
    a, b, c = xy[tris[:, 0]], xy[tris[:, 1]], xy[tris[:, 2]]
    area = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    expected = _signed_area(loops[0]) + sum(_signed_area(h) for h in loops[1:])
    if abs(area.sum() - expected) > 1e-6 * abs(expected):
        raise CombinedSurfaceError(f"the symmetry plane triangulation covers {area.sum():.6g} m2 of {expected:.6g} m2")
    return xy, tris


def combined_surface(box: DomainBox, inputs: MeshCaseInput, meshes: list, labels: list[np.ndarray]) -> tuple[pv.PolyData, list[str]]:
    """(the closed combined surface with the cell array "patch", the patch names it indexes): the domain
    surface's roles, then every part's patches (``labels[i]`` indexes inputs.patches_of(i)).

    Raises:
        CombinedSurfaceError: the symmetry plane cannot be triangulated around the parts."""
    names = [r for r in box.roles]
    dom = domain_surface(box)
    d_pts = np.asarray(dom.points, dtype=float)
    d_tris = np.asarray(dom.faces).reshape(-1, 4)[:, 1:]
    d_lab = np.asarray(dom.cell_data[ROLE_ARRAY], dtype=int)
    blocks = []  # (points, triangles, patch index)
    part_blocks = []
    for i, mesh in enumerate(meshes):
        tri = mesh.triangulate() if not mesh.is_all_triangles else mesh
        pts = np.asarray(tri.points, dtype=float)
        tris = np.asarray(tri.faces).reshape(-1, 4)[:, 1:]
        offset = len(names)
        names += list(inputs.patches_of(i))
        part_blocks.append((pts, tris, np.asarray(labels[i], dtype=int) + offset))
    if box.symmetric:
        sym = box.roles.index("symmetry")
        plane = box.bounds[2]
        tol = PLANE_TOLERANCE * float(np.linalg.norm(np.asarray(box.size)))
        on_dom = d_lab == sym
        outer_edges = _edges_used_once(d_tris[on_dom])
        holes_xy, cut_blocks = [], []
        for pts, tris, lab in part_blocks:
            on = np.abs(pts[:, 1] - plane) < tol
            pts = pts.copy()
            pts[on, 1] = plane
            flat = on[tris].all(axis=1)
            tris, lab = tris[~flat], lab[~flat]
            edges = _edges_used_once(tris)
            on_plane = edges[on[edges].all(axis=1)]
            if len(on_plane):
                # the remaining part faces go one way round the hole; the plane's own faces must go the
                # other way, so the hole loops are taken reversed
                for loop in _loops(on_plane[:, ::-1]):
                    holes_xy.append(pts[loop][:, [0, 2]])
            cut_blocks.append((pts, tris, lab))
        part_blocks = cut_blocks
        outer = _loops(outer_edges)
        if len(outer) != 1:
            raise CombinedSurfaceError(f"the domain's symmetry face has {len(outer)} boundary loops")
        outer_xy = d_pts[outer[0]][:, [0, 2]]
        spacing = inputs.estimate().base_size
        xy, s_tris = triangulate_with_holes(outer_xy, holes_xy, spacing)
        s_pts = np.column_stack([xy[:, 0], np.full(len(xy), plane), xy[:, 1]])
        # outward from the fluid: -y
        n_y = np.cross(s_pts[s_tris[:, 1]] - s_pts[s_tris[:, 0]], s_pts[s_tris[:, 2]] - s_pts[s_tris[:, 0]])[:, 1]
        s_tris = np.where((n_y > 0)[:, None], s_tris[:, ::-1], s_tris)
        blocks.append((d_pts, d_tris[~on_dom], d_lab[~on_dom]))
        blocks.append((s_pts, s_tris, np.full(len(s_tris), sym)))
    else:
        blocks.append((d_pts, d_tris, d_lab))
    blocks += part_blocks
    all_pts = np.concatenate([b[0] for b in blocks])
    offsets = np.cumsum([0] + [len(b[0]) for b in blocks[:-1]])
    all_tris = np.concatenate([b[1] + o for b, o in zip(blocks, offsets)])
    all_lab = np.concatenate([b[2] for b in blocks])
    # shared points are bit-identical copies (the plane's boundary loops come from the domain and the
    # parts): merge exact duplicates only
    unique, inverse = np.unique(all_pts, axis=0, return_inverse=True)
    all_tris = inverse.ravel()[all_tris]
    faces = np.hstack([np.full((len(all_tris), 1), 3), all_tris]).ravel()
    out = pv.PolyData(unique, faces)
    out.cell_data["patch"] = all_lab
    return out, names


def write_domain_guard(case_dir: Path, inputs: MeshCaseInput) -> None:
    """case/vortexcfd_domain.json for foam/mesh_run.domain_problems: every domain patch must have faces;
    a cfMesh case has no background box."""
    data = {"shape": inputs.domain_shape, "expected": list(inputs.expected_domain_patches()), "background": []}
    (Path(case_dir) / DOMAIN_GUARD_FILE).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def prepare_cfmesh_job(project: Project) -> meshing.MeshJob:
    """Write the cfMesh evaluation case for ``project`` into <project dir>/case (replacing a snappyHexMesh
    case there) and return the job; the same inputs as meshing.prepare_job.

    Raises:
        MeshingNotReady, CaseDirectoryNotOursError: as meshing.prepare_job.
        CombinedSurfaceError: see combined_surface.
    """
    inputs, box, meshes = meshing.mesh_inputs(project)
    case_dir = meshing.case_dir_for(project)
    prepare_case_dir(case_dir, build_cfmesh_files(inputs))
    meshing.write_junction_features(case_dir, project, inputs)
    meshing.write_part_surfaces(case_dir, project, inputs, meshes)  # surfaceFeatureExtract's input
    labels = [meshing.part_patch_labels(project, i, m) for i, m in enumerate(meshes)]
    surface, names = combined_surface(box, inputs, meshes, labels)
    regions.write_patch_stl(case_dir / COMBINED_STL, surface, np.asarray(surface.cell_data["patch"]), names)
    write_domain_guard(case_dir, inputs)
    return meshing.MeshJob(case_dir, inputs, box)


def flatten_symmetry(case_dir: Path, patch: str, plane_y: float) -> dict:
    """Move the points of the symmetry patch exactly onto the plane y = ``plane_y`` (constant/polyMesh/
    points rewritten, ascii). OpenFOAM's symmetryPlane needs an exactly planar patch; cartesianMesh's
    result is not (the 5.3 half wing: one point 3.5 mm off the plane at the trailing edge's root), and
    improveSymmetryPlanes skips a patch whose deviation it finds large. Returns the largest and the
    root-mean-square displacement (m) and the number of points moved; checkMesh judges the cells after.
    Evaluation only. [NUMERICS-REVIEW]"""
    mesh = PolyMesh.read(case_dir)
    if patch not in mesh.boundary:
        return {"moved": 0, "max_m": 0.0, "rms_m": 0.0}
    start, count = mesh.boundary[patch]
    rows = mesh.faces[start:start + count]
    ids = np.unique(rows[rows >= 0])
    d = mesh.points[ids, 1] - plane_y
    moved = ids[d != 0.0]
    path = Path(case_dir) / "constant" / "polyMesh" / "points"
    text = path.read_text(encoding="utf-8")
    head = text[:text.index("}", text.index("FoamFile")) + 1]
    points = mesh.points.copy()
    points[ids, 1] = plane_y
    body = "\n".join(f"({x:.10g} {y:.10g} {z:.10g})" for x, y, z in points)
    path.write_text(f"{head}\n\n{len(points)}\n(\n{body}\n)\n", encoding="utf-8")
    return {"moved": int(len(moved)), "max_m": float(np.abs(d).max(initial=0.0)),
            "rms_m": float(np.sqrt(np.mean(d ** 2))) if len(d) else 0.0}
