"""Tests for the solver case files, the inlet turbulence formulas and the y+ estimator."""

import math
import shutil
from pathlib import Path

import pytest

from vortexcfd.core.model import Inflow, Mesh, Physics, Solvers
from vortexcfd.foam.case_writer import write_case
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.mesh_case import MeshCaseInput, build_mesh_files, snappy_hex_mesh_dict
from vortexcfd.foam.physics_case import (
    SolverCaseInput,
    build_solver_files,
    flow_direction,
    inlet_turbulence,
)
from vortexcfd.foam.yplus import first_layer_thickness, friction_velocity, skin_friction, yplus_of_first_cell

TUTORIAL = Path("/usr/lib/openfoam/openfoam2606/tutorials/incompressible/simpleFoam/motorBike")
BOUNDS = (0.0, 2.0, -1.0, 1.0, 0.0, 0.5)


def make(inflow: Inflow | None = None, symmetric: bool = False, physics: Physics | None = None,
         solvers: Solvers | None = None) -> SolverCaseInput:
    return SolverCaseInput(physics or Physics(), inflow or Inflow(), solvers or Solvers(),
                           ("Wing", "Tail"), BOUNDS, symmetric)


# -- inlet turbulence --------------------------------------------------------------------------------


def test_inlet_turbulence_formulas() -> None:
    k, omega = inlet_turbulence(speed=20.0, intensity=0.01, nu=1.5e-5, viscosity_ratio=10.0)
    assert k == pytest.approx(1.5 * (20 * 0.01) ** 2) == pytest.approx(0.06)
    assert omega == pytest.approx(k / (1.5e-5 * 10.0)) == pytest.approx(400.0)
    # nut = k / omega recovers the viscosity ratio
    assert k / omega / 1.5e-5 == pytest.approx(10.0)
    k2, _ = inlet_turbulence(40.0, 0.01, 1.5e-5, 10.0)
    assert k2 == pytest.approx(4 * k)  # k scales with V^2


def test_flow_direction() -> None:
    assert flow_direction(0.0) == pytest.approx((1.0, 0.0, 0.0))
    d = flow_direction(90.0)
    assert d == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)
    d = flow_direction(30.0)
    assert d == pytest.approx((math.cos(math.radians(30)), 0.0, 0.5))
    assert flow_direction(-10.0)[2] < 0


# -- files ---------------------------------------------------------------------------------------------


def test_all_expected_files_are_generated() -> None:
    files = build_solver_files(make())
    assert set(files) == {
        "system/controlDict", "system/fvSchemes", "system/fvSolution",
        "constant/transportProperties", "constant/turbulenceProperties",
        "0/U", "0/p", "0/k", "0/omega", "0/nut",
    }
    assert files["0/U"].class_name == "volVectorField" and files["0/p"].class_name == "volScalarField"


def test_transport_and_turbulence_properties_use_the_v2606_keywords() -> None:
    files = build_solver_files(make(physics=Physics(nu=2e-5)))
    assert files["constant/transportProperties"].content == {"transportModel": "Newtonian", "nu": 2e-5}
    t = files["constant/turbulenceProperties"].content
    assert t["simulationType"] == "RAS" and t["RAS"]["RASModel"] == "kOmegaSST"
    assert t["RAS"]["turbulence"] is True and t["RAS"]["printCoeffs"] is True


def test_boundary_conditions_inlet_outlet_far_field_walls() -> None:
    f = build_solver_files(make())
    bc = {name: spec.content["boundaryField"] for name, spec in f.items() if name.startswith("0/")}
    k, omega = inlet_turbulence(20, 0.01, 1.5e-5, 10)
    assert bc["0/U"]["inlet"] == {"type": "fixedValue", "value": [20.0, 0.0, 0.0]}
    assert bc["0/p"]["inlet"] == {"type": "zeroGradient"}
    assert bc["0/k"]["inlet"] == {"type": "fixedValue", "value": pytest.approx(k)}
    assert bc["0/omega"]["inlet"] == {"type": "fixedValue", "value": pytest.approx(omega)}
    assert bc["0/nut"]["inlet"]["type"] == "calculated"
    assert bc["0/p"]["outlet"] == {"type": "fixedValue", "value": 0.0}
    assert bc["0/U"]["outlet"]["type"] == "inletOutlet" and bc["0/U"]["outlet"]["inletValue"] == [0.0, 0.0, 0.0]
    assert bc["0/k"]["outlet"]["type"] == "inletOutlet" and bc["0/omega"]["outlet"]["type"] == "inletOutlet"
    for field in ("0/U", "0/p", "0/k", "0/omega"):
        for patch in ("sides", "top", "bottom"):
            assert bc[field][patch] == {"type": "slip"}, (field, patch)
        assert "symmetry" not in bc[field]
    for patch in ("Wing", "Tail"):
        assert bc["0/U"][patch] == {"type": "noSlip"} and bc["0/p"][patch] == {"type": "zeroGradient"}
        assert bc["0/k"][patch]["type"] == "kqRWallFunction"
        assert bc["0/omega"][patch]["type"] == "omegaWallFunction"
        assert bc["0/nut"][patch]["type"] == "nutUSpaldingWallFunction"


def test_symmetry_plane_patch_is_present_only_with_symmetry() -> None:
    f = build_solver_files(make(symmetric=True))
    for name in ("0/U", "0/p", "0/k", "0/omega", "0/nut"):
        assert f[name].content["boundaryField"]["symmetry"] == {"type": "symmetryPlane"}


def test_angle_of_attack_sets_inlet_velocity_and_force_directions() -> None:
    a = 8.0
    f = build_solver_files(make(Inflow(speed=30.0, alpha_deg=a)))
    ra = math.radians(a)
    v = [30 * math.cos(ra), 0.0, 30 * math.sin(ra)]
    assert f["0/U"].content["boundaryField"]["inlet"]["value"] == pytest.approx(v)
    assert f["0/U"].content["internalField"] == pytest.approx(v)
    fc = f["system/controlDict"].content["functions"]["forceCoeffs1"]
    assert fc["liftDir"] == pytest.approx([-math.sin(ra), 0.0, math.cos(ra)])
    assert fc["dragDir"] == pytest.approx([math.cos(ra), 0.0, math.sin(ra)])
    assert fc["pitchAxis"] == [0.0, 1.0, 0.0] and fc["magUInf"] == 30.0
    # lift is perpendicular to drag and to the pitch axis
    assert sum(x * y for x, y in zip(fc["liftDir"], fc["dragDir"])) == pytest.approx(0.0, abs=1e-12)


def test_control_dict_force_coeffs_and_yplus() -> None:
    f = build_solver_files(make(solvers=Solvers(iterations=321, write_interval=40), physics=Physics(rho_ref=1.0)))
    c = f["system/controlDict"].content
    assert c["application"] == "simpleFoam" and c["endTime"] == 321 and c["writeInterval"] == 40
    assert c["deltaT"] == 1 and c["startTime"] == 0
    fc = c["functions"]["forceCoeffs1"]
    assert fc["type"] == "forceCoeffs" and fc["libs"] == ["forces"] and fc["patches"] == ["Wing", "Tail"]
    assert fc["rho"] == "rhoInf" and fc["rhoInf"] == 1.0
    assert fc["CofR"] == [1.0, 0.0, 0.25]  # the parts' bounding-box centre
    assert fc["lRef"] == 2.0 and fc["Aref"] == 4.0  # x extent, x extent * y extent
    assert c["functions"]["yPlus1"]["type"] == "yPlus"
    assert c["functions"]["yPlus1"]["libs"] == ["fieldFunctionObjects"]


def test_schemes_and_solution_follow_the_motorbike_tutorial() -> None:
    f = build_solver_files(make())
    s = f["system/fvSchemes"].content
    assert s["ddtSchemes"]["default"] == "steadyState"
    assert s["divSchemes"]["div(phi,U)"] == ("bounded", "Gauss", "linearUpwindV", "grad(U)")
    assert s["divSchemes"]["div(phi,k)"] == ("bounded", "Gauss", "upwind")
    assert s["gradSchemes"]["grad(U)"] == ("cellLimited", "Gauss", "linear", 1)
    sol = f["system/fvSolution"].content
    assert sol["SIMPLE"] == {
        "nNonOrthogonalCorrectors": 0, "consistent": True,
        "residualControl": {"p": 1e-4, "U": 1e-5, "k": 1e-5, "omega": 1e-5},
    }
    assert sol["relaxationFactors"]["equations"] == {"U": 0.9, "k": 0.7, "omega": 0.7}
    assert sol["solvers"]["p"]["solver"] == "GAMG" and sol["solvers"]["p"]["relTol"] == 0.01
    assert sol["solvers"]["U"]["solver"] == "smoothSolver" and sol["solvers"]["omega"]["nSweeps"] == 1


@pytest.mark.skipif(not TUTORIAL.is_dir(), reason="OpenFOAM tutorials not installed")
def test_keywords_cover_the_motorbike_tutorial_files(tmp_path: Path) -> None:
    write_case(tmp_path / "case", build_solver_files(make()))
    case = tmp_path / "case"
    for name in ("fvSchemes", "fvSolution"):
        ours = read_foam_file(case / "system" / name)
        tut = read_foam_file(TUTORIAL / "system" / name)
        assert set(tut) - {"cache", "turbulence"} <= set(ours), (name, set(tut) - set(ours))
    ours_s, tut_s = read_foam_file(case / "system" / "fvSchemes"), read_foam_file(TUTORIAL / "system" / "fvSchemes")
    assert {k for k in tut_s["divSchemes"] if k != "turbulence"} <= set(ours_s["divSchemes"])
    for name in ("transportProperties", "turbulenceProperties"):
        assert set(read_foam_file(TUTORIAL / "constant" / name)) <= set(read_foam_file(case / "constant" / name))
    wall = {"U": "noSlip", "p": "zeroGradient", "k": "kqRWallFunction", "omega": "omegaWallFunction"}
    for field, wall_type in wall.items():  # the tutorial uses the same outlet and wall types
        tut_types = {v["type"] for v in read_foam_file(TUTORIAL / "0.orig" / field)["boundaryField"].values()
                     if isinstance(v, dict) and "type" in v}
        ours_types = {v["type"] for v in read_foam_file(case / "0" / field)["boundaryField"].values()}
        assert wall_type in tut_types and wall_type in ours_types, (field, wall_type)
        if field != "p":
            assert "inletOutlet" in tut_types and "inletOutlet" in ours_types, field
        assert "slip" in ours_types


def test_written_scheme_lines_are_bare_token_sequences(tmp_path: Path) -> None:
    write_case(tmp_path / "c", build_solver_files(make()))
    text = (tmp_path / "c" / "system" / "fvSchemes").read_text()
    assert "div(phi,U) bounded Gauss linearUpwindV grad(U);" in text
    assert "(bounded" not in text  # OpenFOAM would not read a parenthesised scheme


# -- y+ estimator ------------------------------------------------------------------------------------------


def test_skin_friction_and_friction_velocity_hand_values() -> None:
    # Re = 10 * 2 / 1.5e-5 = 1.3333e6: Re^(1/7) = 7.4999, Cf = 0.026 / 7.4999 = 3.4667e-3
    re = 10.0 * 2.0 / 1.5e-5
    assert skin_friction(re) == pytest.approx(3.4667e-3, rel=1e-3)
    # u* = V sqrt(Cf / 2) = 10 * sqrt(1.7333e-3) = 0.41633 m/s
    assert friction_velocity(10.0, 1.5e-5, 2.0) == pytest.approx(0.41633, rel=1e-3)


def test_first_layer_thickness_hand_values() -> None:
    # y = y+ nu / u* = 1 * 1.5e-5 / 0.41633 = 3.603e-5 m
    assert first_layer_thickness(1.0, 10.0, 1.5e-5, 2.0) == pytest.approx(3.603e-5, rel=1e-3)
    assert first_layer_thickness(30.0, 10.0, 1.5e-5, 2.0) == pytest.approx(30 * 3.603e-5, rel=1e-3)
    # a second hand case: V = 50 m/s, nu = 1.5e-5, L = 1 m -> Re = 3.3333e6, Re^(1/7) = 8.5475
    # Cf = 0.026 / 8.5475 = 3.0418e-3, u* = 50 sqrt(1.5209e-3) = 1.9500 m/s, y(y+=1) = 7.693e-6 m
    assert first_layer_thickness(1.0, 50.0, 1.5e-5, 1.0) == pytest.approx(7.693e-6, rel=1e-3)
    # thinner for a higher speed and for a smaller viscosity
    assert first_layer_thickness(1.0, 20.0, 1.5e-5, 1.0) > first_layer_thickness(1.0, 40.0, 1.5e-5, 1.0)


def test_yplus_of_first_cell_is_half_the_cell_height_convention() -> None:
    h = first_layer_thickness(1.0, 10.0, 1.5e-5, 2.0)
    # At x = L the cell-centre y+ is exactly half of the target (the cell CENTRE is at h / 2).
    assert yplus_of_first_cell(h, 10.0, 1.5e-5, 2.0) == pytest.approx(0.5, rel=1e-9)
    # Closer to the leading edge u* is larger, so y+ grows.
    assert yplus_of_first_cell(h, 10.0, 1.5e-5, 0.5) > 0.5


# -- absolute layers in the mesh dictionaries -----------------------------------------------------------------


def _mesh_input(mesh: Mesh, first: float | None) -> MeshCaseInput:
    return MeshCaseInput((-5, 10, -5, 5, -5, 5), False, ("Wing",), (0.0, 1.0, -0.5, 0.5, 0.0, 0.3), 1.0, mesh, first)


def test_relative_layers_are_the_default() -> None:
    content = snappy_hex_mesh_dict(_mesh_input(Mesh(), None)).content
    assert content["meshQualityControls"]["minTetQuality"] == 1e-15  # the default quality limits
    layers = content["addLayersControls"]
    assert layers["relativeSizes"] is True and "firstLayerThickness" not in layers
    assert layers["finalLayerThickness"] == 0.5 and layers["minThickness"] == 0.1


def test_absolute_yplus_layers_use_the_first_layer_thickness() -> None:
    mesh = Mesh(layer_sizing="absolute_yplus", target_yplus=1.0, expansion_ratio=1.3, min_thickness=0.2)
    layers = snappy_hex_mesh_dict(_mesh_input(mesh, 4e-5)).content["addLayersControls"]
    assert layers["relativeSizes"] is False
    assert snappy_hex_mesh_dict(_mesh_input(mesh, 4e-5)).content["meshQualityControls"]["minTetQuality"] == -1e30
    assert layers["firstLayerThickness"] == 4e-5 and layers["expansionRatio"] == 1.3  # reused
    assert layers["minThickness"] == pytest.approx(0.2 * 4e-5)
    assert "finalLayerThickness" not in layers
    with pytest.raises(ValueError, match="first_layer_thickness"):
        snappy_hex_mesh_dict(_mesh_input(mesh, None))


# -- real OpenFOAM acceptance -----------------------------------------------------------------------------------


@pytest.mark.slow
def test_solver_files_are_accepted_by_simpleFoam_on_the_session_mesh(sphere_mesh, tmp_path: Path) -> None:
    """A few simpleFoam iterations on the real sphere mesh: every BC type exists for its patch."""
    from vortexcfd.foam.runner import FoamRun

    case = tmp_path / "case"
    shutil.copytree(sphere_mesh.case_dir, case)  # the shared mesh is read only
    inputs = sphere_mesh.inputs
    inp = SolverCaseInput(Physics(), Inflow(alpha_deg=5.0), Solvers(iterations=3, write_interval=3),
                          inputs.parts, inputs.parts_bounds, False)
    write_case_over = build_solver_files(inp)
    from vortexcfd.foam.dictfile import write_foam_file

    for rel, spec in write_case_over.items():
        write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    run = FoamRun()
    run.start(["simpleFoam"], case, case / "log.simpleFoam", timeout_s=100)
    run.wait(110)
    result = run.result()
    text = (case / "log.simpleFoam").read_text()
    assert result.exit_code == 0, text[-1500:]
    assert "FOAM FATAL" not in text and "\nEnd" in text
    assert (case / "postProcessing" / "forceCoeffs1" / "0" / "coefficient.dat").is_file() or \
        any((case / "postProcessing").glob("forceCoeffs1/*/*")), "forceCoeffs wrote nothing"
    assert (case / "3" / "yPlus").is_file()


@pytest.mark.slow
def test_snappy_accepts_absolute_layers_and_first_layer_is_the_first_cell(tmp_path: Path) -> None:
    """A real coarse mesh with absolute layer sizes: snappyHexMesh builds layers whose total
    thickness is h (1 + r + r^2), i.e. firstLayerThickness is the height of the first CELL.

    h is given explicitly (10 mm): on this coarse surface mesh (60 mm cells) much thinner y+ layers
    collapse (0 % extruded), see docs/QUESTIONS.md.
    """
    import pyvista as pv

    from vortexcfd.core.model import Domain
    from vortexcfd.foam.mesh_case import TRI_SURFACE, prepare_case_dir, safe_part_names
    from vortexcfd.foam.mesh_run import MeshRun
    from vortexcfd.geometry.domain import compute_domain

    sphere = pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24)
    box = compute_domain([tuple(sphere.bounds)], Domain(upstream=2, downstream=3, lateral=2, vertical=2))
    mesh = Mesh(base_size=0.25, surface_level_min=1, surface_level_max=2, layers=3,
                layer_sizing="absolute_yplus", target_yplus=1.0, expansion_ratio=1.2)
    h = 0.01
    inp = MeshCaseInput(box.bounds, False, tuple(safe_part_names(["Sphere"])), tuple(sphere.bounds),
                        box.reference_length, mesh, h)
    case = tmp_path / "case"
    prepare_case_dir(case, build_mesh_files(inp))
    sphere.save(str(case / TRI_SURFACE / "Sphere.stl"))
    run = MeshRun(case, step_timeout_s=100)
    run.start()
    result = run.wait(110)
    assert result is not None and result.success, result
    cov = result.report.layers[0]
    assert cov.target_layers == 3 and cov.mesh_layers == 3.0
    assert cov.thickness_m == pytest.approx(h * (1 + 1.2 + 1.2**2), rel=0.02)
    assert result.report.extruded_percent == 100.0


def test_residual_targets_are_written_as_simple_residual_control() -> None:
    solvers = Solvers(residual_p=1e-6, residual_u=2e-6, residual_k=3e-6, residual_omega=4e-6)
    f = build_solver_files(make(solvers=solvers))
    assert f["system/fvSolution"].content["SIMPLE"]["residualControl"] == {
        "p": 1e-6, "U": 2e-6, "k": 3e-6, "omega": 4e-6}


# -- layer count from y+ ----------------------------------------------------------------------------------------

from vortexcfd.foam.yplus import MAX_LAYERS, WARNING_HINT, plan_layers


def test_plan_layers_hand_values() -> None:
    # t1 = 1 mm, r = 1.2, surface cell 8.4 mm: 0.5 h / t1 = 4.2, ln 4.2 / ln 1.2 = 7.87 -> n = 8 + 1 = 9
    plan = plan_layers(1e-3, 1.2, 8.4e-3)
    assert plan.count == 9 and plan.warning is None
    assert plan.needed == pytest.approx(4.2)
    assert plan.total == pytest.approx(1e-3 * (1.2**9 - 1) / 0.2)  # 20.8 mm
    assert plan.final == pytest.approx(1e-3 * 1.2**8)  # 4.30 mm, about half a surface cell (4.2 mm)
    assert 0.5 * 8.4e-3 <= plan.final <= 1.2 * 0.5 * 8.4e-3


def test_plan_layers_clamps_and_warns() -> None:
    assert plan_layers(0.01, 1.2, 0.01).count == 1  # the first layer is already thicker than needed
    assert plan_layers(0.01, 1.2, 0.01).warning is None
    thin = plan_layers(1.8e-5, 1.2, 8.4e-3)  # y+ 1 on a coarse surface: 0.5 h / t1 = 233 > 1.2^29 = 198
    assert thin.count == MAX_LAYERS == 30 and thin.warning and WARNING_HINT in thin.warning
    assert thin.needed > 1.2 ** 29
    ok = plan_layers(5.4e-4, 1.2, 8.4e-3)  # y+ 30: 7.8, n = 12 + 1 = 13
    assert ok.count == 13 and ok.warning is None
    # exactly at the limit: r^29 needed -> n = 30 without a warning, a hair more warns
    edge = plan_layers(1.0, 2.0, 2.0 * 2.0**29)
    assert edge.count == 30 and edge.warning is None
    assert plan_layers(1.0, 2.0, 2.0 * 2.0**29 * 1.01).warning


def test_snappy_uses_the_computed_layer_count_for_absolute_sizing() -> None:
    mesh = Mesh(layer_sizing="absolute_yplus", layers=3)
    inp = MeshCaseInput((-5, 10, -5, 5, -5, 5), False, ("Wing",), (0.0, 1.0, -0.5, 0.5, 0.0, 0.3), 1.0, mesh,
                        first_layer_thickness=1e-3, layer_count=9)
    d = snappy_hex_mesh_dict(inp).content
    assert d["addLayersControls"]["layers"]['"Wing.*"'] == {"nSurfaceLayers": 9} and d["addLayers"] is True
    rel = MeshCaseInput((-5, 10, -5, 5, -5, 5), False, ("Wing",), (0.0, 1.0, -0.5, 0.5, 0.0, 0.3), 1.0,
                        Mesh(layers=4), layer_count=9)
    assert snappy_hex_mesh_dict(rel).content["addLayersControls"]["layers"]['"Wing.*"'] == {"nSurfaceLayers": 4}


@pytest.mark.slow
def test_yplus_30_layer_count_gives_good_coverage_on_the_shared_sphere(sphere_mesh, tmp_path: Path) -> None:
    """Shared coarse sphere at 20 m/s with target y+ 30 and the computed layer count: layer coverage
    (average layers and thickness) of at least 80 %. The y+ 1 case is expected to warn instead."""
    import pyvista as pv

    from vortexcfd.foam.mesh_case import TRI_SURFACE, prepare_case_dir
    from vortexcfd.foam.mesh_run import MeshRun

    inputs, est = sphere_mesh.inputs, sphere_mesh.estimate
    mesh = Mesh(layer_sizing="absolute_yplus", target_yplus=30.0)
    first = first_layer_thickness(30.0, 20.0, 1.5e-5, inputs.reference_length)
    plan = plan_layers(first, mesh.expansion_ratio, est.surface_size)
    assert plan.warning is None and 5 <= plan.count <= 30
    thin = plan_layers(first_layer_thickness(1.0, 20.0, 1.5e-5, inputs.reference_length),
                       mesh.expansion_ratio, est.surface_size)
    assert thin.warning and thin.count == 30  # y+ 1 on this surface mesh warns
    case = tmp_path / "case"
    inp = MeshCaseInput(inputs.domain_bounds, False, inputs.parts, inputs.parts_bounds,
                        inputs.reference_length, mesh, plan.first, plan.count)
    prepare_case_dir(case, build_mesh_files(inp))
    pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24).save(str(case / TRI_SURFACE / "Sphere.stl"))
    run = MeshRun(case, step_timeout_s=100)
    run.start()
    result = run.wait(115)
    assert result is not None and result.success, result
    cov = result.report.layers[0]
    print(f"\ny+ 30 sphere: n={plan.count} first={plan.first:.3g} m total={plan.total:.3g} m "
          f"final={plan.final:.3g} m; coverage {cov.description()} ({cov.thickness_m:.3g} m), "
          f"extruded {result.report.extruded_percent}%")
    assert cov.target_layers == plan.count
    assert cov.layers_percent >= 80.0 and cov.thickness_percent >= 80.0, cov
    assert result.report.extruded_percent >= 80.0 and result.report.mesh_ok
