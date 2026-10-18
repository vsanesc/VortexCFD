"""Force projection check (D-050): forceCoeffs' Cd and Cl equal the total force of the `forces` function
object projected by hand onto dragDir = (cos a, 0, sin a) and liftDir = (-sin a, 0, cos a) and divided
by 0.5 rho U^2 A_ref, i.e. v2606 reads liftDir/dragDir (it ignores only pitchAxis).

Fixtures (tests/data/projection_run/, tests/data/README.md): a real run of a flattened ellipsoid at
alpha = 10 deg (non-zero lift), 150 iterations.
"""

import math
from pathlib import Path

import pytest

from vortexcfd.foam.postprocessing import ForceCoeffsTail, ForcesTail, project_coefficients

RUN = Path(__file__).parent / "data" / "projection_run"
ALPHA, RHO, SPEED = 10.0, 1.225, 20.0
TOLERANCE = 0.005  # 0.5 %


def _header(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        if line.startswith("#") and ":" in line:
            key, value = line[1:].split(":", 1)
            out[key.strip()] = value.strip()
    return out


def _vector(text: str) -> tuple[float, ...]:
    return tuple(float(x) for x in text.strip("()").split())


def compare(coeff_file: Path, force_file: Path, alpha: float) -> list[tuple[float, float, float, float, float]]:
    """(time, Cd forceCoeffs, Cd manual, Cl forceCoeffs, Cl manual) for every common iteration."""
    header = _header(coeff_file)
    area = float(header["Aref"])
    assert float(header["magUInf"]) == pytest.approx(SPEED)
    a = math.radians(alpha)
    assert _vector(header["dragDir"]) == pytest.approx((math.cos(a), 0.0, math.sin(a)), abs=1e-6)
    assert _vector(header["liftDir"]) == pytest.approx((-math.sin(a), 0.0, math.cos(a)), abs=1e-6)
    coeffs = ForceCoeffsTail(coeff_file)
    coeffs.poll()
    forces = ForcesTail(force_file)
    forces.poll()
    cd, cl = dict(coeffs.series["Cd"]), dict(coeffs.series["Cl"])
    rows = []
    for t, force in forces.total:
        if t in cd:
            md, ml = project_coefficients(force, alpha, RHO, SPEED, area)
            rows.append((t, cd[t], md, cl[t], ml))
    return rows


def _assert_agree(rows) -> None:
    assert rows
    for t, cd, md, cl, ml in rows:
        assert abs(cd - md) <= TOLERANCE * abs(md), (t, cd, md)
        assert abs(cl - ml) <= TOLERANCE * abs(ml), (t, cl, ml)


def test_projection_agrees_on_the_real_fixture() -> None:
    rows = compare(RUN / "coefficient.dat", RUN / "force.dat", ALPHA)
    assert len(rows) == 150
    _assert_agree(rows)
    t, cd, md, cl, ml = rows[-1]
    assert t == 150.0 and cl > 0.03 and cd > 0.03  # the lift is not trivial
    print(f"\niteration 150: Cd forceCoeffs {cd:.7g} manual {md:.7g} ({100 * (cd - md) / md:+.4f} %); "
          f"Cl forceCoeffs {cl:.7g} manual {ml:.7g} ({100 * (cl - ml) / ml:+.4f} %)")


def test_projection_helper_hand_values() -> None:
    # a force along the flow at 10 deg is pure drag
    a = math.radians(10)
    cd, cl = project_coefficients((math.cos(a) * 245.0, 0.0, math.sin(a) * 245.0), 10.0, 1.225, 20.0, 1.0)
    assert cd == pytest.approx(1.0) and cl == pytest.approx(0.0, abs=1e-12)
    cd, cl = project_coefficients((0.0, 0.0, 245.0), 0.0, 1.225, 20.0, 1.0)  # q A = 245 N
    assert (cd, cl) == pytest.approx((0.0, 1.0))


def test_forces_function_object_is_written_next_to_force_coeffs() -> None:
    from vortexcfd.core.model import Inflow, Physics, Reports, Solvers
    from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files

    inp = SolverCaseInput(Physics(rho_ref=1.1), Inflow(alpha_deg=10.0), Solvers(), ("Wing",),
                          (0.0, 2.0, -1.0, 1.0, 0.0, 0.5), False, Reports(center_of_rotation=(0.5, 0, 0)))
    functions = build_solver_files(inp)["system/controlDict"].content["functions"]
    forces = functions["forces1"]
    assert forces["type"] == "forces" and forces["libs"] == ["forces"] and forces["patches"] == ["Wing"]
    assert forces["rho"] == "rhoInf" and forces["rhoInf"] == 1.1 and forces["CofR"] == [0.5, 0, 0]
    assert "liftDir" not in forces and "dragDir" not in forces  # global axes
    assert forces["writeControl"] == "timeStep" and forces["writeInterval"] == 1


@pytest.mark.slow
@pytest.mark.long  # real run above 60 s (D-043)
def test_projection_agrees_on_a_real_run(tmp_path: Path) -> None:
    """Mesh the flattened ellipsoid and run 40 iterations at alpha = 10 deg with the app's files."""
    import pyvista as pv

    from vortexcfd.core.model import Domain, Inflow, Mesh, Physics, Solvers
    from vortexcfd.foam.case_writer import enable_clean_stop
    from vortexcfd.foam.dictfile import write_foam_file
    from vortexcfd.foam.mesh_case import TRI_SURFACE, MeshCaseInput, build_mesh_files, prepare_case_dir
    from vortexcfd.foam.mesh_run import MeshRun
    from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files
    from vortexcfd.foam.runner import FoamRun
    from vortexcfd.geometry.domain import compute_domain

    body = pv.ParametricEllipsoid(0.5, 0.5, 0.15, u_res=48, v_res=24, w_res=24).triangulate().clean()
    box = compute_domain([tuple(body.bounds)], Domain())
    inputs = MeshCaseInput(box.bounds, False, ("Body",), tuple(body.bounds), box.reference_length, Mesh())
    case = tmp_path / "case"
    prepare_case_dir(case, build_mesh_files(inputs))
    body.save(str(case / TRI_SURFACE / "Body.stl"))
    mesh = MeshRun(case, step_timeout_s=240)  # generous: the suite runs meshes in parallel
    mesh.start()
    result = mesh.wait(600)
    assert result is not None and result.success, result
    inp = SolverCaseInput(Physics(rho_ref=RHO), Inflow(speed=SPEED, alpha_deg=ALPHA),
                          Solvers(iterations=40, write_interval=40), inputs.parts, inputs.parts_bounds, False)
    for rel, spec in enable_clean_stop(build_solver_files(inp)).items():
        write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    run = FoamRun()
    run.start(["simpleFoam"], case, case / "log.simpleFoam", timeout_s=240, clean_stop=True)
    try:
        assert run.wait(250)
    finally:
        if run.is_running():
            run.stop(grace_s=5)
    assert run.result().exit_code == 0, (case / "log.simpleFoam").read_text()[-1500:]
    post = case / "postProcessing"
    rows = compare(post / "forceCoeffs1" / "0" / "coefficient.dat", post / "forces1" / "0" / "force.dat", ALPHA)
    assert len(rows) == 40
    _assert_agree(rows)
