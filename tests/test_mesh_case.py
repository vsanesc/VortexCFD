"""Tests for the meshing case files, the checkMesh parser and an end-to-end coarse meshing run."""

import threading
from pathlib import Path

import pytest
import pyvista as pv

from vortexcfd.core.model import Domain, Mesh
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.mesh_case import (
    MARKER_NAME,
    TRI_SURFACE,
    CaseDirectoryNotOursError,
    MeshCaseInput,
    base_cell_size,
    block_cells,
    build_mesh_files,
    location_in_mesh,
    prepare_case_dir,
    safe_part_names,
)
from vortexcfd.foam.mesh_report import parse_check_mesh
from vortexcfd.foam.mesh_run import MeshRun
from vortexcfd.geometry.domain import compute_domain

DATA = Path(__file__).parent / "data"
TUTORIAL = Path("/usr/lib/openfoam/openfoam2606/tutorials/incompressible/simpleFoam/motorBike/system")


def sphere_input(mesh: Mesh | None = None, domain: Domain | None = None, symmetric: bool = False) -> MeshCaseInput:
    sphere = pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24)
    dom = domain or Domain(upstream=2, downstream=4, lateral=2, vertical=2,
                           symmetry="y_min" if symmetric else "none")
    box = compute_domain([tuple(sphere.bounds)], dom)
    return MeshCaseInput(box.bounds, symmetric, tuple(safe_part_names(["Sphere"])),
                         tuple(sphere.bounds), box.reference_length, mesh or Mesh(base_size=0.5))


# -- names, sizes, locationInMesh -------------------------------------------------------------


def test_safe_part_names_are_unique_and_never_reserved() -> None:
    names = safe_part_names(["Wing 1", "Wing 1", "inlet", "3d part", "ünï", "a/b"])
    assert names == ["Wing_1", "Wing_1_2", "inlet_2", "part_3d_part", "n", "a_b"]
    assert len(set(names)) == len(names)


def test_base_size_defaults_to_l_over_20_and_cells_are_at_least_one() -> None:
    assert base_cell_size(Mesh(), 10.0) == 0.5
    assert base_cell_size(Mesh(base_size=0.2), 10.0) == 0.2
    assert block_cells((0, 10, 0, 5, 0, 1), 0.5) == (20, 10, 2)
    assert block_cells((0, 1, 0, 1, 0, 1), 100.0) == (1, 1, 1)


@pytest.mark.parametrize("symmetric", [False, True])
def test_location_in_mesh_is_inside_domain_and_outside_parts(symmetric: bool) -> None:
    inp = sphere_input(symmetric=symmetric)
    cells = block_cells(inp.domain_bounds, base_cell_size(inp.mesh, inp.reference_length))
    x, y, z = location_in_mesh(inp.domain_bounds, inp.parts_bounds, cells)
    d, p = inp.domain_bounds, inp.parts_bounds
    assert d[0] < x < d[1] and d[2] < y < d[3] and d[4] < z < d[5]  # inside the domain
    assert not (p[0] <= x <= p[1] and p[2] <= y <= p[3] and p[4] <= z <= p[5])  # outside parts
    for axis, value in enumerate((x, y, z)):  # away from every background and refined cell face
        step = (d[2 * axis + 1] - d[2 * axis]) / cells[axis]
        frac = ((value - d[2 * axis]) / step) % 1.0
        assert min(abs(frac - k / 16) for k in range(17)) > 0.02


def test_location_in_mesh_with_two_parts_stays_outside_the_union() -> None:
    a, b = (0, 1, 0, 1, 0, 1), (3, 4, 0, 1, 0, 1)
    box = compute_domain([a, b], Domain())
    union = (0, 4, 0, 1, 0, 1)
    cells = block_cells(box.bounds, box.reference_length / 20)
    x, y, z = location_in_mesh(box.bounds, union, cells)
    assert x < 0  # upstream of both parts


# -- dictionaries ------------------------------------------------------------------------------


def test_block_mesh_dict_structure() -> None:
    inp = sphere_input()
    spec = build_mesh_files(inp)["system/blockMeshDict"].content
    assert len(spec["vertices"]) == 8 and spec["blocks"][0] == "hex" and spec["blocks"][3] == "simpleGrading"
    assert spec["blocks"][2] == list(block_cells(inp.domain_bounds, 0.5))
    names = [name for name, _ in spec["boundary"]]
    assert names == ["inlet", "outlet", "sides", "top", "bottom"]
    assert all(body["type"] == "patch" for _, body in spec["boundary"])
    assert dict(spec["boundary"])["sides"]["faces"].__len__() == 2


def test_symmetry_patch_is_a_symmetry_plane() -> None:
    spec = build_mesh_files(sphere_input(symmetric=True))["system/blockMeshDict"].content
    boundary = dict(spec["boundary"])
    assert boundary["symmetry"]["type"] == "symmetryPlane"
    assert len(boundary["sides"]["faces"]) == 1
    assert [n for n, _ in spec["boundary"]][-1] == "symmetry"


def test_snappy_dict_has_the_tutorial_keywords() -> None:
    files = build_mesh_files(sphere_input(Mesh(base_size=0.5, surface_level_min=1, surface_level_max=2, layers=2)))
    d = files["system/snappyHexMeshDict"].content
    assert d["castellatedMesh"] and d["snap"] and d["addLayers"]
    assert d["geometry"]["Sphere.stl"] == {"type": "triSurfaceMesh", "name": "Sphere"}
    c = d["castellatedMeshControls"]
    for key in ("maxLocalCells", "maxGlobalCells", "minRefinementCells", "maxLoadUnbalance",
                "nCellsBetweenLevels", "features", "refinementSurfaces", "resolveFeatureAngle",
                "refinementRegions", "locationInMesh", "allowFreeStandingZoneFaces"):
        assert key in c, key
    surf = c["refinementSurfaces"]["Sphere"]
    assert surf["level"] == [1, 2] and surf["patchInfo"]["type"] == "wall"
    assert c["features"][0]["level"] == 2 and "Sphere.eMesh" in c["features"][0]["file"]
    layers = d["addLayersControls"]
    assert layers["layers"]['"Sphere.*"'] == {"nSurfaceLayers": 2}
    for key in ("relativeSizes", "expansionRatio", "finalLayerThickness", "minThickness", "nGrow",
                "featureAngle", "slipFeatureAngle", "nRelaxIter", "nLayerIter", "nSmoothThickness"):
        assert key in layers, key
    for key in ("nSmoothPatch", "tolerance", "nSolveIter", "nRelaxIter", "nFeatureSnapIter",
                "implicitFeatureSnap", "explicitFeatureSnap", "multiRegionFeatureSnap"):
        assert key in d["snapControls"], key
    assert "maxNonOrtho" in d["meshQualityControls"] and "mergeTolerance" in d


def test_layers_off_when_zero() -> None:
    d = build_mesh_files(sphere_input(Mesh(base_size=0.5, layers=0)))["system/snappyHexMeshDict"].content
    assert d["addLayers"] is False and d["addLayersControls"]["layers"] == {}


def test_surface_feature_extract_dict() -> None:
    mesh = Mesh(base_size=0.5, feature_angle=40.0)
    d = build_mesh_files(sphere_input(mesh))["system/surfaceFeatureExtractDict"].content
    entry = d["Sphere.stl"]
    assert entry["extractionMethod"] == "extractFromSurface"
    assert entry["includedAngle"] == 140.0  # 180 - feature angle
    assert entry["subsetFeatures"]["openEdges"] is True


@pytest.mark.skipif(not TUTORIAL.is_dir(), reason="OpenFOAM tutorials not installed")
def test_keywords_cover_the_motorbike_tutorial() -> None:
    """Every top-level and section keyword of the tutorial dict (except output flags) is ours."""
    tut = read_foam_file(TUTORIAL / "snappyHexMeshDict")
    ours = build_mesh_files(sphere_input())["system/snappyHexMeshDict"].content
    skipped = {"writeFlags", "debug"}
    assert set(tut) - skipped <= set(ours)
    for section in ("castellatedMeshControls", "snapControls", "addLayersControls"):
        assert set(tut[section]) <= set(ours[section]) | {"layers"}, section


def test_written_files_are_valid_openfoam_dictionaries(tmp_path: Path) -> None:
    inp = sphere_input()
    files = build_mesh_files(inp)
    prepare_case_dir(tmp_path / "case", files)
    d = read_foam_file(tmp_path / "case" / "system" / "snappyHexMeshDict")
    assert list(d["castellatedMeshControls"]["locationInMesh"]) == pytest.approx(
        files["system/snappyHexMeshDict"].content["castellatedMeshControls"]["locationInMesh"])
    assert (tmp_path / "case" / "case.foam").is_file()
    assert (tmp_path / "case" / TRI_SURFACE).is_dir()


# -- case directory safety ---------------------------------------------------------------------


def test_new_case_dir_gets_a_marker_and_regeneration_only_replaces_polymesh(tmp_path: Path) -> None:
    case = tmp_path / "case"
    files = build_mesh_files(sphere_input())
    prepare_case_dir(case, files)
    assert (case / MARKER_NAME).is_file()
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "constant" / "polyMesh" / "points").write_text("old")
    (case / "constant" / "keep.txt").write_text("mine")
    (case / "0").mkdir()
    prepare_case_dir(case, files)
    assert not (case / "constant" / "polyMesh").exists()  # replaced
    assert (case / "constant" / "keep.txt").read_text() == "mine"  # nothing else deleted
    assert (case / "0").is_dir()


def test_foreign_case_dir_is_refused_and_left_untouched(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "constant" / "polyMesh" / "points").write_text("user data")
    with pytest.raises(CaseDirectoryNotOursError, match="not generated by VortexCFD"):
        prepare_case_dir(case, build_mesh_files(sphere_input()))
    assert (case / "constant" / "polyMesh" / "points").read_text() == "user data"
    assert not (case / MARKER_NAME).exists()


def test_empty_existing_dir_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "case").mkdir()
    prepare_case_dir(tmp_path / "case", build_mesh_files(sphere_input()))
    assert (tmp_path / "case" / MARKER_NAME).is_file()


# -- checkMesh parser (real log fixture) ---------------------------------------------------------


def test_parse_real_check_mesh_log() -> None:
    report = parse_check_mesh((DATA / "checkMesh_sphere_snappy.log").read_text())
    assert (report.points, report.faces, report.cells) == (5243, 12951, 3910)
    assert report.max_non_orthogonality == pytest.approx(28.943653)
    assert report.avg_non_orthogonality == pytest.approx(10.907735)
    assert report.max_skewness == pytest.approx(0.4556289)
    assert report.mesh_ok and report.failed_checks == 0
    assert "3910 cells" in report.summary() and "Mesh OK" in report.summary()


def test_parse_failed_checks_and_truncated_logs() -> None:
    text = (DATA / "checkMesh_sphere_snappy.log").read_text().replace("Mesh OK.", "Failed 2 mesh checks.")
    r = parse_check_mesh(text)
    assert not r.mesh_ok and r.failed_checks == 2 and "2 failed checks" in r.summary()
    r = parse_check_mesh("FOAM FATAL ERROR: something")  # checkMesh never finished
    assert not r.mesh_ok and r.failed_checks == 1 and r.cells is None


# -- end to end ------------------------------------------------------------------------------------


def test_end_to_end_coarse_sphere_meshing(tmp_path: Path) -> None:
    case = tmp_path / "case"
    inp = sphere_input(Mesh(base_size=0.5, surface_level_min=1, surface_level_max=2, layers=1))
    prepare_case_dir(case, build_mesh_files(inp))
    pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24).save(str(case / TRI_SURFACE / "Sphere.stl"))
    lines: list[str] = []
    steps: list[str] = []
    run = MeshRun(case, on_line=lines.append, on_step=steps.append, step_timeout_s=100)
    run.start()
    result = run.wait(115)
    assert result is not None and not run.is_running()
    assert result.exit_codes == {"blockMesh": 0, "surfaceFeatureExtract": 0, "snappyHexMesh": 0, "checkMesh": 0}
    assert result.success and result.report is not None
    assert result.report.mesh_ok and result.report.failed_checks == 0 and result.report.cells > 0
    assert steps == ["blockMesh", "surfaceFeatureExtract", "snappyHexMesh", "checkMesh"]
    assert any("Mesh OK" in line for line in lines)
    boundary = (case / "constant" / "polyMesh" / "boundary").read_text()
    for patch in ("inlet", "outlet", "sides", "top", "bottom", "Sphere"):
        assert patch in boundary
    print(f"\nE2E checkMesh: {result.report.summary()}")


def test_mesh_run_stop_request(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    run = MeshRun(case, steps=(("sleeper", ["sleep", "30"]),), step_timeout_s=50)
    run.start()
    threading.Event().wait(1.0)
    run.request_stop()
    result = run.wait(30)
    assert result is not None and result.stopped and not result.success
    assert not run.is_running()
