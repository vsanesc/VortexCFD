"""The vectorised layer walk gives the same bits as the face-by-face walk it replaced (docs/REVIEW.md R-25).
[NUMERICS-REVIEW] the walk measures the achieved first cell (D-109); its results must not change."""

from pathlib import Path

import numpy as np
import pytest

from tests.test_cfmesh_case import write_column
from vortexcfd.foam.layer_walk import MAX_ASPECT, MAX_GROWTH, MIN_TOP_COS, walk_layers
from vortexcfd.foam.polymesh import PolyMesh, face_geometry

DATA = Path(__file__).parent / "data"


def reference_walk(mesh: PolyMesh, patches: tuple[str, ...], max_layers: int,
                max_aspect: float = MAX_ASPECT, max_growth: float = MAX_GROWTH) -> dict[str, dict[str, np.ndarray]]:
    """walk_layers as it was before the vectorised walk (docs/REVIEW.md R-25), unchanged: face by face."""
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
        first_cell = np.zeros(count)
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
                if n == 0:
                    first_cell[k] = h  # a prism on the wall face: its height, a layer or not
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
            if first_cell[k] == 0.0:  # not a prism on the wall face (a snapped polyhedron): twice the centre distance
                c0 = int(mesh.owner[f0])
                own = cell_faces[first[c0]:first[c0 + 1]]
                cc = (centre[own] * area[own, None]).sum(axis=0) / max(float(area[own].sum()), 1e-300)
                first_cell[k] = 2.0 * abs(float(np.dot(cc - centre[f0], normal)))
        out[name] = {"layers": layers, "thickness": thick, "first": first_h, "first_cell": first_cell,
                     "area": area[start:start + count].copy(), "centre": centre[start:start + count].copy()}
    return out


def _same(mesh: PolyMesh, max_layers: int) -> None:
    patches = tuple(mesh.boundary)
    a, b = reference_walk(mesh, patches, max_layers), walk_layers(mesh, patches, max_layers)
    assert a.keys() == b.keys()
    for patch in a:
        for key in a[patch]:
            assert a[patch][key].dtype == b[patch][key].dtype and a[patch][key].tobytes() == b[patch][key].tobytes()


COLUMNS = {"stack": [0.01 * 1.2 ** k for k in range(5)] + [1.0, 1.0], "jump": [0.01, 0.012, 0.1, 0.12],
           "cube": [1.0, 1.0], "many": [0.01] * 8, "collapsed": [0.05, 0.05], "fine": [1e-5 * 1.3 ** k for k in range(14)]}


@pytest.mark.parametrize("max_layers", [0, 1, 3, 12])
@pytest.mark.parametrize("column", list(COLUMNS))
def test_columns_walk_to_the_same_bits(tmp_path: Path, column: str, max_layers: int) -> None:
    write_column(tmp_path, COLUMNS[column], width=0.37)
    _same(PolyMesh.read(tmp_path), max_layers)


@pytest.mark.parametrize("max_layers", [0, 1, 12])
def test_the_results_case_walks_to_the_same_bits(max_layers: int) -> None:
    _same(PolyMesh.read(DATA / "results_case"), max_layers)


def test_a_neighbour_list_padded_with_minus_one_walks_to_the_same_bits(tmp_path: Path) -> None:
    """cfMesh writes neighbour with one entry per face, -1 for the boundary faces."""
    write_column(tmp_path, COLUMNS["stack"])
    mesh = PolyMesh.read(tmp_path)
    padded = np.full(len(mesh.faces), -1, dtype=np.int64)
    padded[:len(mesh.neighbour)] = mesh.neighbour
    mesh.neighbour = padded
    for max_layers in (0, 3, 12):
        _same(mesh, max_layers)
