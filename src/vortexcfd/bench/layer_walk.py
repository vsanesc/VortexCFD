"""Prism layers counted from the mesh itself, for any mesher (phase 5.3, D-102). No Qt.

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


def walk_layers(mesh: PolyMesh, patches: tuple[str, ...], max_layers: int,
                max_aspect: float = MAX_ASPECT, max_growth: float = MAX_GROWTH) -> dict[str, dict[str, np.ndarray]]:
    """Per wall patch: the layer count, the stack thickness (m), the first layer's height (m; 0 without a
    layer), the face area and centre of every face (in the patch's face order)."""
    n_faces = len(mesh.faces)
    n_internal = len(mesh.neighbour)
    n_cells = int(max(mesh.owner.max(initial=-1), mesh.neighbour.max(initial=-1))) + 1
    cell_of = np.concatenate([mesh.owner, mesh.neighbour])
    face_of = np.concatenate([np.arange(n_faces), np.arange(n_internal)])
    order = np.argsort(cell_of, kind="stable")
    cell_faces = face_of[order]
    first = np.searchsorted(cell_of[order], np.arange(n_cells + 1))
    centre, vec, area = face_geometry(mesh.points, mesh.faces)
    face_sets = {}

    def pts(f: int) -> frozenset:
        s = face_sets.get(f)
        if s is None:
            row = mesh.faces[f]
            s = face_sets[f] = frozenset(int(v) for v in row[row >= 0])
        return s

    out = {}
    for name in patches:
        if name not in mesh.boundary:
            continue
        start, count = mesh.boundary[name]
        layers = np.zeros(count, dtype=np.int64)
        thick = np.zeros(count)
        first_h = np.zeros(count)
        for k in range(count):
            f0 = start + k
            normal = vec[f0] / max(area[f0], 1e-300)
            f, c, n, total, last = f0, int(mesh.owner[f0]), 0, 0.0, 0.0
            while n < max_layers:
                fp = pts(f)
                tops = [int(g) for g in cell_faces[first[c]:first[c + 1]] if g != f and pts(int(g)).isdisjoint(fp)]
                if not tops:
                    break
                # a split side face (hanging points of a refinement step) can also miss the bottom face:
                # the top is the candidate most parallel to the wall
                cos = [abs(float(np.dot(vec[g], normal))) / max(area[g], 1e-300) for g in tops]
                g = tops[int(np.argmax(cos))]
                if max(cos) < MIN_TOP_COS or len(pts(g)) < len(pts(f0)):
                    break
                h = abs(float(np.dot(centre[g] - centre[f], normal)))
                if h > max_aspect * np.sqrt(area[f]) or (n > 0 and h > max_growth * last):
                    break
                last = h
                n += 1
                total += h
                if n == 1:
                    first_h[k] = h
                if g >= n_internal:
                    break
                c = int(mesh.neighbour[g]) if int(mesh.owner[g]) == c else int(mesh.owner[g])
                f = g
            layers[k], thick[k] = n, total
        out[name] = {"layers": layers, "thickness": thick, "first": first_h,
                     "area": area[start:start + count].copy(), "centre": centre[start:start + count].copy()}
    return out
