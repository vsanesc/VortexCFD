"""cfMesh evaluation case (phase 5.3, benchmark only): availability, dictionaries, combined surface."""

from pathlib import Path

import pytest

from vortexcfd.foam.cfmesh_case import CFMESH_EXECUTABLES, cfmesh_executables
from vortexcfd.foam.runner import OPENFOAM_BASHRC

needs_openfoam = pytest.mark.skipif(not Path(OPENFOAM_BASHRC).is_file(), reason="OpenFOAM v2606 not installed")


@needs_openfoam
def test_cfmesh_executables_are_in_the_v2606_installation():
    found = cfmesh_executables()
    assert set(found) == set(CFMESH_EXECUTABLES)
    missing = [name for name, path in found.items() if path is None]
    assert not missing
    assert "/openfoam2606/" in found["cartesianMesh"]


def test_a_missing_executable_is_none():
    assert cfmesh_executables(("cartesianMesh_does_not_exist",)) == {"cartesianMesh_does_not_exist": None}


# -- the evaluation case (D-102) --------------------------------------------------------------------

import numpy as np  # noqa: E402
import pyvista as pv  # noqa: E402

from vortexcfd.bench.layer_walk import walk_layers  # noqa: E402
from vortexcfd.core.model import Part  # noqa: E402
from vortexcfd.core.project import Project  # noqa: E402
from vortexcfd.foam.cfmesh_case import (  # noqa: E402
    COMBINED_FMS,
    COMBINED_STL,
    build_cfmesh_files,
    cfmesh_commands,
    level_size,
    mesh_dict,
)
from vortexcfd.foam.dictfile import read_foam_file  # noqa: E402
from vortexcfd.foam.polymesh import PolyMesh  # noqa: E402
from vortexcfd.foam.postprocessing import patch_face_counts  # noqa: E402
from vortexcfd.geometry.loader import clear_cache  # noqa: E402
from vortexcfd.workflow import meshing  # noqa: E402
from vortexcfd.workflow.cfmesh import combined_surface, flatten_symmetry, prepare_cfmesh_job  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def project_with(tmp_path: Path, surface: pv.PolyData, name: str, symmetric: bool = False, **mesh) -> Project:
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True, exist_ok=True)
    surface.save(str(folder / "geometry" / f"{name}.stl"))
    project = Project.new("m")
    project.add_part(Part(name=name, source_file=f"geometry/{name}.stl", units="m"))
    if symmetric:
        project.update_domain(symmetry="y_min")
    if mesh:
        project.update_mesh(**mesh)
    project.save(folder / "p.json")
    return project


def ball(tmp_path: Path, **mesh) -> Project:
    return project_with(tmp_path, pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24), "Ball 1", **mesh)


def half_block(tmp_path: Path) -> Project:
    """A block 1 x 0.5 x 0.2 m whose y_min face lies on the symmetry plane."""
    return project_with(tmp_path, pv.Box(bounds=(0, 1, 0, 0.5, -0.1, 0.1)).triangulate(), "blk", symmetric=True)


def test_mesh_dict_maps_the_snappy_settings(tmp_path: Path) -> None:
    project = ball(tmp_path)
    inputs, _box, _meshes = meshing.mesh_inputs(project)
    est = inputs.estimate()
    d = mesh_dict(inputs).content
    assert d["surfaceFile"] == f'"{COMBINED_FMS}"'
    assert d["maxCellSize"] == pytest.approx(est.base_size)
    assert "minCellSize" not in d and "boundaryCellSize" not in d
    assert d["localRefinement"] == {"Ball_1": {"cellSize": pytest.approx(level_size(est.base_size, est.level_min))}}
    edge = d["edgeMeshRefinement"]["Ball_1"]
    assert edge["edgeFile"] == '"constant/triSurface/Ball_1.eMesh"'
    assert edge["cellSize"] == pytest.approx(level_size(est.base_size, est.level_max))
    layers = d["boundaryLayers"]["patchBoundaryLayers"]["Ball_1"]  # the y+ stack of the snappy case
    assert layers["nLayers"] == inputs.layer_count
    assert layers["thicknessRatio"] == project.sim.mesh.expansion_ratio
    assert layers["maxFirstLayerThickness"] == pytest.approx(inputs.first_layer_thickness)
    assert d["boundaryLayers"]["optimiseLayer"] == 1
    names = d["renameBoundary"]["newPatchNames"]
    assert set(names) == {"Ball_1", "inlet", "outlet", "sides", "top", "bottom"}
    assert names["Ball_1"] == {"newName": "Ball_1", "type": "wall"}
    assert names["inlet"]["type"] == "patch"


def test_relative_layers_have_no_first_layer_cap_and_one_layer_none(tmp_path: Path) -> None:
    inputs, _, _ = meshing.mesh_inputs(ball(tmp_path, layer_sizing="relative", layers=3))
    layers = mesh_dict(inputs).content["boundaryLayers"]["patchBoundaryLayers"]["Ball_1"]
    assert layers["nLayers"] == 3 and "maxFirstLayerThickness" not in layers
    inputs, _, _ = meshing.mesh_inputs(ball(tmp_path / "one", layer_sizing="relative", layers=1))
    assert "boundaryLayers" not in mesh_dict(inputs).content


def test_symmetry_patch_type_and_steps(tmp_path: Path) -> None:
    inputs, _, _ = meshing.mesh_inputs(half_block(tmp_path))
    names = mesh_dict(inputs).content["renameBoundary"]["newPatchNames"]
    assert names["symmetry"]["type"] == "symmetryPlane"
    steps = [name for name, _ in cfmesh_commands(inputs, (0, 2))]
    assert steps == ["surfaceFeatureExtract", "surfaceFeatureEdges", "cartesianMesh", "improveSymmetryPlanes", "checkMesh"]
    assert dict(cfmesh_commands(inputs, (0, 2)))["cartesianMesh"] == ["taskset", "-c", "0,2", "cartesianMesh"]
    assert "system/surfaceFeatureExtractDict" in build_cfmesh_files(inputs)


def _closed(surface: pv.PolyData) -> tuple[int, int]:
    edges = surface.extract_feature_edges(boundary_edges=True, feature_edges=False, manifold_edges=False,
                                          non_manifold_edges=True)
    return edges.n_cells, surface.n_cells


def test_combined_surface_is_closed_with_one_region_per_patch(tmp_path: Path) -> None:
    project = ball(tmp_path)
    inputs, box, meshes = meshing.mesh_inputs(project)
    surface, names = combined_surface(box, inputs, meshes, [np.zeros(meshes[0].n_cells, dtype=int)])
    assert _closed(surface)[0] == 0
    assert set(names) == {"Ball_1", "inlet", "outlet", "sides", "top", "bottom"}
    labels = np.asarray(surface.cell_data["patch"])
    assert set(np.unique(labels)) == set(range(len(names)))
    assert (labels == names.index("Ball_1")).sum() == meshes[0].n_cells


def test_combined_surface_cuts_the_part_out_of_the_symmetry_plane(tmp_path: Path) -> None:
    project = half_block(tmp_path)
    inputs, box, meshes = meshing.mesh_inputs(project)
    surface, names = combined_surface(box, inputs, meshes, [np.zeros(meshes[0].n_cells, dtype=int)])
    assert _closed(surface)[0] == 0
    labels = np.asarray(surface.cell_data["patch"])
    sym = surface.extract_cells(np.flatnonzero(labels == names.index("symmetry")))
    b = box.bounds
    assert sym.area == pytest.approx((b[1] - b[0]) * (b[5] - b[4]) - 1.0 * 0.2, rel=1e-9)
    assert np.allclose(np.asarray(sym.points)[:, 1], b[2])
    part = surface.extract_cells(np.flatnonzero(labels == names.index("blk")))
    assert part.area == pytest.approx(1.4, rel=1e-6)  # the box without its 1 x 0.2 m root face (float32 points)


def test_prepare_cfmesh_job_writes_the_case(tmp_path: Path) -> None:
    job = prepare_cfmesh_job(ball(tmp_path))
    case = job.case_dir
    assert (case / "system" / "meshDict").is_file() and (case / COMBINED_STL).is_file()
    assert (case / "constant" / "triSurface" / "Ball_1.stl").is_file()  # surfaceFeatureExtract's input
    assert not (case / "system" / "snappyHexMeshDict").exists()
    assert read_foam_file(case / "system" / "meshDict")["maxCellSize"] > 0


# -- layers counted from the mesh, symmetry flattening ------------------------------------------------


def write_column(case: Path, heights: list[float], width: float = 1.0) -> None:
    """A polyMesh of one column of hexahedra over a 'wall' face at z = 0 (cell k has height heights[k]),
    its sides in the patch 'symmetry' (y = 0) and 'sides', its top in 'top'."""
    z = np.concatenate([[0.0], np.cumsum(heights)])
    pts = [(x, y, zz) for zz in z for (x, y) in ((0, 0), (width, 0), (width, width), (0, width))]
    n = len(heights)

    def v(level, corner):
        return 4 * level + corner

    internal = [[v(k + 1, 0), v(k + 1, 1), v(k + 1, 2), v(k + 1, 3)] for k in range(n - 1)]
    owner = list(range(n - 1))
    neighbour = list(range(1, n))
    patches = {"wall": [[v(0, 0), v(0, 3), v(0, 2), v(0, 1)]], "symmetry": [], "sides": [],
               "top": [[v(n, 0), v(n, 1), v(n, 2), v(n, 3)]]}
    owners = {"wall": [0], "symmetry": [], "sides": [], "top": [n - 1]}
    for k in range(n):
        for a, b, patch in ((0, 1, "symmetry"), (1, 2, "sides"), (2, 3, "sides"), (3, 0, "sides")):
            patches[patch].append([v(k, a), v(k, b), v(k + 1, b), v(k + 1, a)])
            owners[patch].append(k)
    faces, own = list(internal), list(owner)
    boundary, start = [], len(internal)
    for name in ("wall", "symmetry", "sides", "top"):
        faces += patches[name]
        own += owners[name]
        boundary.append(f"{name} {{ type patch; nFaces {len(patches[name])}; startFace {start}; }}")
        start += len(patches[name])
    d = case / "constant" / "polyMesh"
    d.mkdir(parents=True, exist_ok=True)

    def header(cls, obj):
        return f"FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class {cls};\n    object {obj};\n}}\n\n"

    (d / "points").write_text(header("vectorField", "points") + f"{len(pts)}\n(\n"
                              + "\n".join(f"({a} {b} {c})" for a, b, c in pts) + "\n)\n")
    (d / "faces").write_text(header("faceList", "faces") + f"{len(faces)}\n(\n"
                             + "\n".join(f"4({' '.join(map(str, f))})" for f in faces) + "\n)\n")
    (d / "owner").write_text(header("labelList", "owner") + f"{len(own)}\n(\n" + "\n".join(map(str, own)) + "\n)\n")
    (d / "neighbour").write_text(header("labelList", "neighbour") + f"{len(neighbour)}\n(\n"
                                 + "\n".join(map(str, neighbour)) + "\n)\n")
    (d / "boundary").write_text(header("polyBoundaryMesh", "boundary") + f"{len(boundary)}\n(\n"
                                + "\n".join(boundary) + "\n)\n")


def test_layer_walk_counts_the_thin_prisms_of_a_stack(tmp_path: Path) -> None:
    stack = [0.01 * 1.2 ** k for k in range(5)]
    write_column(tmp_path, stack + [1.0, 1.0])  # five layers, then two cubic core cells
    walked = walk_layers(PolyMesh.read(tmp_path), ("wall",), 10)["wall"]
    assert walked["layers"].tolist() == [5]
    assert walked["thickness"][0] == pytest.approx(sum(stack))
    assert walked["first"][0] == pytest.approx(0.01)
    assert walked["first_cell"][0] == pytest.approx(0.01)  # the wall-adjacent cell's height
    assert walked["area"][0] == pytest.approx(1.0)


def test_layer_walk_stops_at_a_jump_in_height_and_at_the_limit(tmp_path: Path) -> None:
    write_column(tmp_path / "jump", [0.01, 0.012, 0.1, 0.12])  # 0.1 is more than 3 x 0.012
    assert walk_layers(PolyMesh.read(tmp_path / "jump"), ("wall",), 10)["wall"]["layers"].tolist() == [2]
    write_column(tmp_path / "cube", [1.0, 1.0])  # no layer: the first cell is not thin
    cube = walk_layers(PolyMesh.read(tmp_path / "cube"), ("wall",), 10)["wall"]
    assert cube["layers"].tolist() == [0] and cube["first_cell"][0] == pytest.approx(1.0)  # its height all the same
    write_column(tmp_path / "many", [0.01] * 8)
    assert walk_layers(PolyMesh.read(tmp_path / "many"), ("wall",), 3)["wall"]["layers"].tolist() == [3]


def test_flatten_symmetry_moves_only_the_patch_points_onto_the_plane(tmp_path: Path) -> None:
    write_column(tmp_path, [0.5, 0.5])
    points = PolyMesh.read(tmp_path).points
    points[4, 1] = 0.003  # a point of the symmetry patch, off the plane y = 0
    path = tmp_path / "constant" / "polyMesh" / "points"
    text = path.read_text()
    path.write_text(text[:text.index("}") + 1] + f"\n\n{len(points)}\n(\n"
                    + "\n".join(f"({a:.17g} {b:.17g} {c:.17g})" for a, b, c in points) + "\n)\n")
    moved = flatten_symmetry(tmp_path, "symmetry", 0.0)
    assert moved["moved"] == 1 and moved["max_m"] == pytest.approx(0.003)
    after = PolyMesh.read(tmp_path).points
    assert after[4, 1] == 0.0
    assert np.array_equal(np.delete(after, 4, axis=0), np.delete(points, 4, axis=0))
    assert patch_face_counts(tmp_path)["symmetry"] == 2


@needs_openfoam
@pytest.mark.slow
def test_a_real_cfmesh_run_has_the_snappy_patch_names(tmp_path: Path) -> None:
    """A coarse sphere meshed by cartesianMesh: every patch of the snappyHexMesh case, each with faces."""
    from vortexcfd.foam.mesh_run import MeshRun

    project = ball(tmp_path, background_cells_target=5000, layer_sizing="relative", layers=3)
    snappy_inputs, _, _ = meshing.mesh_inputs(project)
    expected = set(snappy_inputs.patches) | set(snappy_inputs.expected_domain_patches())
    job = prepare_cfmesh_job(project)
    run = MeshRun(job.case_dir, steps=cfmesh_commands(job.inputs), parts=job.inputs.patches, step_timeout_s=60)
    run.start()
    result = run.wait(90)
    assert result is not None and result.success, result
    counts = patch_face_counts(job.case_dir)
    assert set(counts) == expected and all(counts[p] > 0 for p in expected)
    assert result.report.valid
