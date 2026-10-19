"""Domain shapes (D-078): box, bullet and C-type surfaces, their meshing dictionaries, the domain guard,
and real coarse meshes of a sphere in each shape (marker slow)."""

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

from vortexcfd.core.model import Domain, Mesh
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_case import (
    BACKGROUND_PATCH,
    DOMAIN_GUARD_FILE,
    TRI_SURFACE,
    MeshCaseInput,
    build_mesh_files,
    prepare_case_dir,
    write_domain_guard,
)
from vortexcfd.foam.mesh_estimate import BACKGROUND_MARGIN_CELLS, estimate_mesh
from vortexcfd.foam.mesh_run import MeshRun, domain_problems
from vortexcfd.foam.physics_case import FAR_FIELD_BY_SHAPE, SolverCaseInput, build_solver_files
from vortexcfd.core.model import Inflow, Physics, Solvers
from vortexcfd.foam.postprocessing import patch_face_counts
from vortexcfd.geometry.checks import check_surface
from vortexcfd.geometry.domain import compute_domain
from vortexcfd.geometry.domain_surface import ROLE_ARRAY, domain_surface, meshing_surface, role_names
from vortexcfd.workflow.meshing import domain_fields, estimate_for, write_domain_surface

PART = (-0.5, 0.5, -0.5, 0.5, -0.5, 0.5)  # L = 1 m, centred on the origin
SHAPES = ("box", "bullet", "c_type")
SYMMETRY = ("none", "y_min")


def _box(shape: str, symmetry: str = "none", **kw):
    return compute_domain([PART], Domain(shape=shape, symmetry=symmetry, **kw))


@pytest.mark.parametrize("symmetry", SYMMETRY)
@pytest.mark.parametrize("shape", SHAPES)
def test_surfaces_are_watertight_with_all_roles(shape: str, symmetry: str) -> None:
    box = _box(shape, symmetry)
    surface = domain_surface(box)
    report = check_surface(surface)
    assert report.watertight and report.open_edges == 0 and report.non_manifold_edges == 0
    assert report.degenerate_triangles == 0 and report.duplicate_faces == 0 and report.inconsistent_orientation == 0
    assert surface.volume > 0 and not report.normals_inward  # outward normals
    assert set(role_names(box, surface)) == set(box.roles)
    expected = {"box": {"inlet", "outlet", "sides", "top", "bottom"}, "bullet": {"inlet", "outlet", "farfield"},
                "c_type": {"inlet", "outlet", "farfield", "sides"}}[shape]
    assert set(box.roles) == expected | ({"symmetry"} if symmetry == "y_min" else set())


@pytest.mark.parametrize("symmetry", SYMMETRY)
@pytest.mark.parametrize("shape", ["bullet", "c_type"])
def test_enclosed_volume_matches_the_analytic_value(shape: str, symmetry: str) -> None:
    box = _box(shape, symmetry, radius=4.0, downstream=7.0, lateral=3.0)
    r, length = 4.0, 0.5 + 7.0  # from the centre (axis) to the outlet
    if shape == "bullet":
        analytic = 2 / 3 * math.pi * r ** 3 + math.pi * r ** 2 * length
        analytic /= 2 if symmetry == "y_min" else 1
    else:
        span = 3.0 if symmetry == "y_min" else 6.0
        analytic = (math.pi * r ** 2 / 2 + 2 * r * length) * span
    assert box.volume == pytest.approx(analytic, rel=1e-12)
    assert domain_surface(box).volume == pytest.approx(analytic, rel=0.01)


def test_shape_geometry() -> None:
    bullet = _box("bullet")
    assert bullet.axis == (0.0, 0.0, 0.0) and bullet.radius_m == 5.0 and bullet.x_rear == 10.5
    assert bullet.bounds == (-5.0, 10.5, -5.0, 5.0, -5.0, 5.0) and bullet.inlet_x == -5.0
    half = _box("bullet", "y_min")
    assert half.axis == (0.0, -0.5, 0.0) and half.bounds[2:4] == (-0.5, 4.5)  # cut through the axis
    c = _box("c_type", "y_min", lateral=2.0)
    assert c.y_span == (-0.5, 1.5) and c.bounds == (-5.0, 10.5, -0.5, 1.5, -5.0, 5.0)
    assert _box("c_type").y_span == (-5.0, 5.0)
    assert not _box("bullet").warnings
    assert "does not enclose" in compute_domain([PART], Domain(shape="bullet", radius=0.4)).warnings[0]
    # the domain is sized around the listed parts only
    small, big = (0, 1, 0, 1, 0, 1), (5, 30, 0, 1, 0, 1)
    both = compute_domain([small, big], Domain(shape="bullet"), ["small", "big"])
    one = compute_domain([small, big], Domain(shape="bullet", parts=["small"]), ["small", "big"])
    assert both.reference_length == 30 and one.reference_length == 1 and one.axis == (0.5, 0.5, 0.5)
    assert "big" in one.warnings[0]  # the other part is outside the small domain


def test_meshing_surface_leaves_the_symmetry_plane_to_the_background() -> None:
    box = _box("bullet", "y_min")
    surface = meshing_surface(box, 0.3)
    assert "symmetry" not in role_names(box, surface)
    assert surface.bounds[2] == pytest.approx(-0.8)  # extended 0.3 m through the plane
    assert check_surface(surface).open_edges > 0  # open below the plane, closed by nothing (outside the mesh)
    assert meshing_surface(_box("bullet"), 0.3).n_cells == domain_surface(_box("bullet")).n_cells


def test_estimate_uses_the_actual_volume_and_a_background_margin() -> None:
    mesh = Mesh(background_cells_target=50_000)
    box, bullet = _box("box"), _box("bullet")
    est_box, est_bullet = estimate_for(box, mesh), estimate_for(bullet, mesh)
    assert est_box.base_size == pytest.approx((box.volume / 50_000) ** (1 / 3))
    assert est_bullet.base_size == pytest.approx((bullet.volume / 50_000) ** (1 / 3))
    assert est_box.background_bounds == box.bounds
    m = BACKGROUND_MARGIN_CELLS * est_bullet.base_size
    assert est_bullet.background_bounds == pytest.approx(
        (bullet.bounds[0] - m, bullet.bounds[1] + m, bullet.bounds[2] - m, bullet.bounds[3] + m,
         bullet.bounds[4] - m, bullet.bounds[5] + m))
    half = _box("bullet", "y_min")
    assert estimate_for(half, mesh).background_bounds[2] == half.bounds[2]  # flush with the symmetry plane
    assert estimate_mesh(box.bounds, 1.0, mesh) == est_box


def _inputs(shape: str, symmetry: str = "none", mesh: Mesh = Mesh(base_size=0.5, surface_level_min=1,
                                                                  surface_level_max=2, layers=0,
                                                                  layer_sizing="relative")):
    box = _box(shape, symmetry)
    return box, MeshCaseInput(box.bounds, symmetry == "y_min", ("Sphere",), PART, box.reference_length, mesh,
                              **domain_fields(box))


def test_rounded_dictionaries() -> None:
    box, inp = _inputs("c_type", "y_min")
    assert inp.domain_patches == ("inlet", "outlet", "farfield", "sides")
    assert inp.expected_domain_patches() == ("inlet", "outlet", "farfield", "sides", "symmetry")
    files = build_mesh_files(inp)
    block = files["system/blockMeshDict"].content
    assert [name for name, _ in block["boundary"]] == [BACKGROUND_PATCH, "symmetry"]
    assert dict(block["boundary"])["symmetry"]["type"] == "symmetryPlane"
    snappy = files["system/snappyHexMeshDict"].content
    assert snappy["geometry"]["domain.stl"]["regions"] == {p: {"name": p} for p in inp.domain_patches}
    assert snappy["castellatedMeshControls"]["refinementSurfaces"]["domain"]["level"] == [0, 0]
    assert {"file": '"domain.eMesh"', "level": 0} in snappy["castellatedMeshControls"]["features"]
    assert "domain" not in snappy["addLayersControls"]["layers"]
    location = snappy["castellatedMeshControls"]["locationInMesh"]
    assert box.contains(location) and not (-0.5 <= location[0] <= 0.5)  # in the fluid, upstream of the part
    assert files["system/createPatchDict"].content == {"pointSync": False, "patches": []}
    assert "domain.stl" in files["system/surfaceFeatureExtractDict"].content
    _box_, plain = _inputs("box")
    plain_files = build_mesh_files(plain)
    assert "system/createPatchDict" not in plain_files
    assert [n for n, _ in plain_files["system/blockMeshDict"].content["boundary"]] == [
        "inlet", "outlet", "sides", "top", "bottom"]


def test_switching_back_to_a_box_drops_the_create_patch_dict(tmp_path: Path) -> None:
    _b, rounded = _inputs("bullet")
    prepare_case_dir(tmp_path / "case", build_mesh_files(rounded))
    assert (tmp_path / "case" / "system" / "createPatchDict").is_file()
    _b, plain = _inputs("box")
    prepare_case_dir(tmp_path / "case", build_mesh_files(plain))
    assert not (tmp_path / "case" / "system" / "createPatchDict").exists()


def _boundary(case: Path, counts: dict[str, int]) -> None:
    rows = "".join(f"    {name}\n    {{\n        type patch;\n        nFaces {n};\n        startFace 0;\n    }}\n"
                   for name, n in counts.items())
    path = case / "constant" / "polyMesh" / "boundary"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class polyBoundaryMesh;\n"
                    f"    object boundary;\n}}\n{len(counts)}\n(\n{rows})\n")


def test_domain_guard(tmp_path: Path) -> None:
    _b, inp = _inputs("bullet")
    write_domain_guard(tmp_path, inp)
    assert json.loads((tmp_path / DOMAIN_GUARD_FILE).read_text()) == {
        "shape": "bullet", "expected": ["inlet", "outlet", "farfield"], "background": [BACKGROUND_PATCH]}
    _boundary(tmp_path, {"inlet": 10, "outlet": 5, "farfield": 20, "Sphere": 3})
    assert domain_problems(tmp_path) == ()
    _boundary(tmp_path, {"inlet": 10, "outlet": 0, "farfield": 20, BACKGROUND_PATCH: 7})
    problems = domain_problems(tmp_path)
    assert len(problems) == 2 and "background" in problems[0] and "outlet has no faces" in problems[1]
    _boundary(tmp_path, {"inlet": 10, "farfield": 20})  # createPatch removed the empty outlet
    assert domain_problems(tmp_path) == ("Domain patch outlet has no faces",)
    (tmp_path / DOMAIN_GUARD_FILE).unlink()
    assert domain_problems(tmp_path) == ()  # cases before D-078


@pytest.mark.parametrize("shape", SHAPES)
def test_solver_files_cover_every_domain_patch(shape: str) -> None:
    inp = SolverCaseInput(Physics(), Inflow(), Solvers(), ("Sphere",), PART, True, far_field=FAR_FIELD_BY_SHAPE[shape])
    files = build_solver_files(inp)
    expected = set(_box(shape, "y_min").roles) | {"Sphere"}
    for name in ("0/U", "0/p", "0/k", "0/omega", "0/nut"):
        assert set(files[name].content["boundaryField"]) == expected, name
    far = FAR_FIELD_BY_SHAPE[shape]
    assert all(files["0/U"].content["boundaryField"][p] == {"type": "slip"} for p in far)


def test_domain_parts_follow_renames_and_removals() -> None:
    from vortexcfd.core.model import Part

    project = Project.new("P")
    project.add_parts([Part(name="a", source_file="a.stl"), Part(name="b", source_file="b.stl")])
    project.update_domain(parts=["a", "b"])
    project.update_part(0, name="wing")
    assert project.sim.domain.parts == ["wing", "b"]
    project.remove_part(1)
    assert project.sim.domain.parts == ["wing"]
    project.remove_part(0)
    assert project.sim.domain.parts is None  # back to every part
    with pytest.raises(ValueError):
        Domain(parts=["a", "a"])
    with pytest.raises(ValueError):
        Domain(shape="sphere")


# -- real coarse meshes (snappyHexMesh, under 2 minutes each) ----------------------------------------


def _real_mesh(tmp_path: Path, shape: str):
    sphere = pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24)
    box = compute_domain([tuple(sphere.bounds)], Domain(shape=shape))
    mesh = Mesh(base_size=0.5, surface_level_min=1, surface_level_max=2, layers=0,
                layer_sizing="relative")  # the same base size
    inp = MeshCaseInput(box.bounds, False, ("Sphere",), tuple(sphere.bounds), box.reference_length, mesh,
                        **domain_fields(box))
    case = tmp_path / shape
    prepare_case_dir(case, build_mesh_files(inp))
    sphere.save(str(case / TRI_SURFACE / "Sphere.stl"))
    write_domain_surface(case, box, inp)
    write_domain_guard(case, inp)
    run = MeshRun(case, step_timeout_s=110, parts=inp.parts)
    run.start()
    result = run.wait(118)
    return box, inp, case, result


@pytest.mark.slow
@pytest.mark.openfoam
@pytest.mark.parametrize("shape", SHAPES)
def test_real_coarse_mesh_of_a_sphere(tmp_path: Path, shape: str) -> None:
    box, inp, case, result = _real_mesh(tmp_path, shape)
    assert result is not None and result.success, result
    report = result.report
    counts = patch_face_counts(case)
    print(f"\n{shape}: domain volume {box.volume:.4g} m3, cells {report.cells}, "
          f"checkMesh {'OK' if report.mesh_ok else 'FAILED'}, patches {counts}")
    assert report.mesh_ok and report.valid and not report.lost_parts and not report.domain_errors
    assert BACKGROUND_PATCH not in counts  # createPatch removed the emptied background box patch
    for patch in (*inp.expected_domain_patches(), "Sphere"):
        assert counts.get(patch, 0) > 0, patch
    assert set(counts) == {*inp.expected_domain_patches(), "Sphere"}
    if shape != "box":
        assert result.exit_codes["createPatch"] == 0
        # the rounded domain is smaller than its bounding box: fewer cells than the box at the same size
        assert box.volume < np.prod(box.size)
