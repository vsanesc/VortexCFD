"""Helpers for the tests that mesh and solve real OpenFOAM cases outside the GUI (no Qt).

``mesh_body`` meshes one closed surface with the app's meshing dictionaries (blockMesh,
surfaceFeatureExtract, snappyHexMesh, checkMesh through MeshRun); ``write_solver_case`` writes the
app's solver files (clean stop enabled) into a meshed case; ``run_solver`` runs SolverRun to the
end and always leaves no process behind.
"""

from dataclasses import dataclass, field
from pathlib import Path

from vortexcfd.core.model import Domain, Inflow, Mesh, Physics, Reports, Solvers
from vortexcfd.foam.case_writer import enable_clean_stop
from vortexcfd.foam.dictfile import write_foam_file
from vortexcfd.foam.mesh_case import TRI_SURFACE, MeshCaseInput, build_mesh_files, prepare_case_dir, safe_part_names
from vortexcfd.foam.mesh_run import MeshRun
from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files
from vortexcfd.foam.solver_run import SolverRun


def flattened_ellipsoid():
    """The flattened ellipsoid of the force projection check (D-050): semi-axes 0.5 x 0.5 x 0.15 m."""
    import pyvista as pv

    return pv.ParametricEllipsoid(0.5, 0.5, 0.15, u_res=48, v_res=24, w_res=24).triangulate().clean()


def sphere(radius: float = 0.5, resolution: int = 24):
    import pyvista as pv

    return pv.Sphere(radius=radius, theta_resolution=resolution, phi_resolution=resolution)


@dataclass
class MeshedCase:
    case_dir: Path
    inputs: MeshCaseInput
    cells: int | None = None
    ok: bool = False
    lines: list = field(default_factory=list)


def mesh_body(case: Path, surface, name: str, mesh: Mesh = Mesh(), domain: Domain = Domain(),
              step_timeout_s: float = 600, total_timeout_s: float = 1800) -> MeshedCase:
    """Mesh ``surface`` (one part ``name``) in ``case`` with the app's dictionaries."""
    from vortexcfd.geometry.domain import compute_domain

    bounds = tuple(float(b) for b in surface.bounds)
    box = compute_domain([bounds], domain)
    inputs = MeshCaseInput(box.bounds, False, tuple(safe_part_names([name])), bounds, box.reference_length, mesh,
                           part_bounds=(bounds,), part_levels=((None, None),))
    prepare_case_dir(case, build_mesh_files(inputs))
    surface.save(str(case / TRI_SURFACE / f"{inputs.parts[0]}.stl"))
    out = MeshedCase(case, inputs)
    run = MeshRun(case, on_line=out.lines.append, step_timeout_s=step_timeout_s, parts=inputs.parts)
    run.start()
    try:
        result = run.wait(total_timeout_s)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(60)
    out.ok = bool(result is not None and result.success and result.report.valid)
    out.cells = result.report.cells if result is not None and result.report is not None else None
    return out


def write_solver_case(meshed: MeshedCase, physics: Physics = Physics(), inflow: Inflow = Inflow(),
                      solvers: Solvers = Solvers(), reports: Reports = Reports()) -> None:
    inp = SolverCaseInput(physics, inflow, solvers, meshed.inputs.parts, meshed.inputs.parts_bounds, False, reports)
    for rel, spec in enable_clean_stop(build_solver_files(inp)).items():
        write_foam_file(meshed.case_dir / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)


def run_solver(case: Path, timeout_s: float, **kwargs):
    """Run SolverRun in ``case`` to the end (kwargs: stopping, cores, binding)."""
    run = SolverRun(case, timeout_s=timeout_s, **kwargs)
    run.start()
    try:
        return run.wait(timeout_s + 120)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(60)
