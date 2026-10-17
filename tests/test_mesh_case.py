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
    block_cells,
    build_mesh_files,
    location_in_mesh,
    prepare_case_dir,
    safe_part_names,
)
from vortexcfd.foam.mesh_estimate import MAX_BACKGROUND_CELLS, estimate_mesh
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
    assert names == ["Wing_1", "Wing_1_1", "inlet_1", "part_3d_part", "n", "a_b"]
    assert len(set(names)) == len(names)


def test_block_cells_are_at_least_one() -> None:
    assert block_cells((0, 10, 0, 5, 0, 1), 0.5) == (20, 10, 2)
    assert block_cells((0, 1, 0, 1, 0, 1), 100.0) == (1, 1, 1)


def default_box_1m():
    """The default domain (5/10/5/5) around a 1 m cube: 16 x 11 x 11 m."""
    return compute_domain([(0.0, 1.0, 0.0, 1.0, 0.0, 1.0)], Domain())


def test_estimate_default_domain_hits_the_cell_target() -> None:
    box = default_box_1m()
    est = estimate_mesh(box.bounds, box.reference_length, Mesh())
    assert est.base_size == pytest.approx((16 * 11 * 11 / 100_000) ** (1 / 3))
    assert est.cells == (60, 41, 41)
    assert est.total_cells == 60 * 41 * 41
    assert abs(est.total_cells - 100_000) <= 0.2 * 100_000
    # base 0.2686 m, target surface size 0.01 m: ceil(log2(26.9)) = 5 levels, min = 4
    assert (est.level_max, est.level_min) == (5, 4)
    assert est.surface_size == pytest.approx(est.base_size / 32)
    assert not est.base_size_overridden and not est.levels_overridden and not est.too_many_cells


def test_estimate_scales_with_the_target_and_respects_overrides() -> None:
    box = default_box_1m()
    coarse = estimate_mesh(box.bounds, box.reference_length, Mesh(background_cells_target=10_000))
    assert abs(coarse.total_cells - 10_000) <= 2_000
    assert (coarse.level_max, coarse.level_min) == (6, 5)  # base 0.579 m: ceil(log2(57.9)) = 6
    explicit = estimate_mesh(box.bounds, box.reference_length,
                             Mesh(base_size=0.5, surface_level_min=1, surface_level_max=3))
    assert explicit.base_size == 0.5 and explicit.base_size_overridden and explicit.levels_overridden
    assert (explicit.level_min, explicit.level_max) == (1, 3)
    assert explicit.cells == (32, 22, 22)
    only_max = estimate_mesh(box.bounds, box.reference_length, Mesh(surface_level_max=2))
    assert (only_max.level_min, only_max.level_max) == (1, 2)  # min follows max - 1
    coarse_surface = estimate_mesh(box.bounds, box.reference_length, Mesh(target_surface_size=10.0))
    assert coarse_surface.level_max == 0 and coarse_surface.level_min == 0  # never negative


def test_estimate_flags_too_many_background_cells() -> None:
    box = default_box_1m()
    huge = estimate_mesh(box.bounds, box.reference_length, Mesh(background_cells_target=15_500_000))
    assert huge.too_many_cells and huge.total_cells > MAX_BACKGROUND_CELLS
    assert "limit 2,000,000" in huge.limit_message()
    ok = estimate_mesh(box.bounds, box.reference_length, Mesh(background_cells_target=1_900_000))
    assert ok.total_cells <= MAX_BACKGROUND_CELLS and ok.limit_message() is None


@pytest.mark.parametrize("symmetric", [False, True])
def test_location_in_mesh_is_inside_domain_and_outside_parts(symmetric: bool) -> None:
    inp = sphere_input(symmetric=symmetric)
    cells = estimate_mesh(inp.domain_bounds, inp.reference_length, inp.mesh).cells
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
    cells = estimate_mesh(box.bounds, box.reference_length, Mesh()).cells
    x, y, z = location_in_mesh(box.bounds, union, cells)
    assert x < 0  # upstream of both parts


# -- dictionaries ------------------------------------------------------------------------------


def test_block_mesh_dict_structure() -> None:
    inp = sphere_input()
    spec = build_mesh_files(inp)["system/blockMeshDict"].content
    assert len(spec["vertices"]) == 8 and spec["blocks"][0] == "hex" and spec["blocks"][3] == "simpleGrading"
    assert spec["blocks"][2] == list(estimate_mesh(inp.domain_bounds, inp.reference_length, inp.mesh).cells)
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


@pytest.mark.slow
def test_end_to_end_coarse_sphere_meshing(sphere_mesh) -> None:
    """The shared session mesh: the NEW defaults only, nothing tuned by hand."""
    est, result = sphere_mesh.estimate, sphere_mesh.result
    assert abs(est.total_cells - 100_000) <= 20_000
    assert result.exit_codes == {"blockMesh": 0, "surfaceFeatureExtract": 0, "snappyHexMesh": 0, "checkMesh": 0}
    assert result.success and result.report is not None
    assert result.report.mesh_ok and result.report.failed_checks == 0 and result.report.cells > 0
    assert sphere_mesh.steps == ["blockMesh", "surfaceFeatureExtract", "snappyHexMesh", "checkMesh"]
    assert any("Mesh OK" in line for line in sphere_mesh.lines)
    boundary = (sphere_mesh.case_dir / "constant" / "polyMesh" / "boundary").read_text()
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


# -- layer table and persisted record ------------------------------------------------------------------

from vortexcfd.foam.mesh_record import MeshRecord, read_mesh_record, write_mesh_record
from vortexcfd.foam.mesh_report import LAYER_WARN_PERCENT, LayerCoverage, MeshReport, parse_layer_table


def test_parse_layer_table_from_the_real_snappy_log() -> None:
    """tests/data/snappyHexMesh_sphere_default.log: real log of the default-settings sphere run."""
    layers, extruded = parse_layer_table((DATA / "snappyHexMesh_sphere_default.log").read_text())
    assert layers == (LayerCoverage("Sphere", 9460, 3, 3.0, 0.0211, 100.0),)  # the FINAL table
    assert layers[0].basis == "thickness" and layers[0].coverage_percent == 100.0
    assert layers[0].layers_percent == 100.0 and layers[0].description() == "3 / 3 (100 %), thickness 100 %"
    assert not layers[0].below_threshold
    assert extruded == 100.0  # "Extruding 9460 out of 9460 faces (100%)"


def test_layer_table_with_several_patches_and_poor_coverage() -> None:
    text = """
patch  faces    layers avg thickness[m]
                       near-wall overall
-----  -----    ------ --------- -------
old    10       3      0.1       0.2

Extruding 90 out of 100 faces (90%). Removed extrusion at 5 faces.
Mesh with layers : cells:1  faces:1  points:1

patch  faces        layers        overall thickness
                target   mesh     [m]       [%]
-----  -----    -----    ----     ---       ---
wing   60       3        2.5      0.01      55.5
tail   40       3        3        0.02      100

Layer mesh : cells:1
"""
    layers, extruded = parse_layer_table(text)
    assert [c.patch for c in layers] == ["wing", "tail"]
    assert layers[0].below_threshold and layers[0].thickness_percent == 55.5 and layers[0].mesh_layers == 2.5
    assert not layers[1].below_threshold and LAYER_WARN_PERCENT == 80.0
    assert layers[0].description() == "2.5 / 3 (83 %), thickness 55.5 %"
    assert extruded == 90.0
    assert parse_layer_table("no table here") == ((), None)


@pytest.mark.slow
def test_mesh_run_report_carries_the_layer_coverage_end_to_end(sphere_mesh) -> None:
    result, est = sphere_mesh.result, sphere_mesh.estimate
    layers = result.report.layers
    assert [c.patch for c in layers] == ["Sphere"] and layers[0].target_layers == 3
    assert result.report.extruded_percent is not None and layers[0].coverage_percent > 0
    print(
        f"\nDEFAULT SPHERE: background {est.cells} = {est.total_cells} cells (target 100000), "
        f"levels {est.level_min}-{est.level_max}, surface cells {est.surface_size:.4g} m; "
        f"total {result.report.cells} cells; layers "
        + "; ".join(f"{c.patch}: {c.coverage_percent:g}% thickness ({c.mesh_layers:g}/{c.target_layers})"
                    for c in layers)
        + f"; extruded faces {result.report.extruded_percent:g}%; {result.report.summary()}"
    )
    assert abs(est.total_cells - 100_000) <= 20_000 and result.report.mesh_ok


def test_mesh_record_round_trip_and_bad_files(tmp_path: Path) -> None:
    report = parse_check_mesh((DATA / "checkMesh_sphere_snappy.log").read_text())
    layers, extruded = parse_layer_table((DATA / "snappyHexMesh_sphere_default.log").read_text())
    from dataclasses import replace

    report = replace(report, layers=layers, extruded_percent=extruded)
    record = MeshRecord(report, "abc123", ("Sphere",))
    write_mesh_record(tmp_path, record)
    assert (tmp_path / "vortexcfd_mesh.json").is_file()
    assert read_mesh_record(tmp_path) == record
    assert read_mesh_record(tmp_path / "missing") is None
    (tmp_path / "vortexcfd_mesh.json").write_text("{not json")
    assert read_mesh_record(tmp_path) is None


def test_patch_names_never_collide_with_boundaries_or_each_other() -> None:
    names = safe_part_names(["inlet", "outlet", "sides", "top", "bottom", "symmetry", "Inlet", "wing", "wing", "wing_1"])
    assert names == ["inlet_1", "outlet_1", "sides_1", "top_1", "bottom_1", "symmetry_1",
                     "Inlet", "wing", "wing_1", "wing_1_1"]
    assert len(set(names)) == len(names)
    assert not set(names) & {"inlet", "outlet", "sides", "top", "bottom", "symmetry"}
    assert safe_part_names(["inlet", "inlet"]) == ["inlet_1", "inlet_2"]  # deterministic suffixes
    assert safe_part_names(["inlet", "inlet"]) == safe_part_names(["inlet", "inlet"])


def test_layer_warning_uses_either_metric() -> None:
    ok = LayerCoverage("a", 10, 3, 3.0, 0.01, 95.0)
    few_layers = LayerCoverage("b", 10, 3, 2.1, 0.01, 95.0)  # 70 % of the layers, thickness fine
    thin = LayerCoverage("c", 10, 3, 3.0, 0.01, 64.0)  # all layers, only 64 % of the thickness
    assert not ok.below_threshold
    assert few_layers.layers_percent == pytest.approx(70.0) and few_layers.below_threshold
    assert thin.below_threshold and not thin.layers_percent < 80
    assert few_layers.description() == "2.1 / 3 (70 %), thickness 95 %"
    report = MeshReport(1, 1, 1, 1.0, 1.0, 0.1, 0, True, layers=(few_layers, thin))
    assert "b 2.1 / 3 (70 %), thickness 95 %" in report.layer_summary()


# -- results removed by a new mesh (D-051) ------------------------------------------------------------------


def test_remove_results_deletes_only_results_in_a_marked_case(tmp_path: Path) -> None:
    from vortexcfd.foam.mesh_case import MARKER_NAME, MARKER_TEXT, RUN_RECORD_FILE, remove_results
    from vortexcfd.foam.run_record import RUN_RECORD_NAME

    assert RUN_RECORD_FILE == RUN_RECORD_NAME
    case = tmp_path / "case"
    for d in ("0", "30", "60", "1e-05", "postProcessing/forceCoeffs1/0", "constant/polyMesh", "system", "logs",
              "constant/triSurface", "notes"):
        (case / d).mkdir(parents=True)
    (case / "60" / "U").write_text("u")
    (case / "0" / "U").write_text("u0")
    (case / RUN_RECORD_NAME).write_text("{}")
    (case / "vortexcfd_mesh.json").write_text("{}")
    (case / "log.simpleFoam").write_text("log")
    with pytest.raises(CaseDirectoryNotOursError):
        remove_results(case)  # no marker: nothing is deleted
    assert (case / "60" / "U").is_file()
    (case / MARKER_NAME).write_text(MARKER_TEXT)
    assert remove_results(case) == ["1e-05", "30", "60", "postProcessing", RUN_RECORD_NAME]
    left = sorted(p.name for p in case.iterdir())
    assert left == sorted([MARKER_NAME, "0", "constant", "system", "logs", "notes", "vortexcfd_mesh.json",
                           "log.simpleFoam"])
    assert (case / "0" / "U").read_text() == "u0" and (case / "constant" / "polyMesh").is_dir()
    assert remove_results(case) == []  # nothing left to remove
