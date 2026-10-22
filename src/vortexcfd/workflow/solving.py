"""Solver orchestration: project -> solver case files in <project dir>/case (Qt-free).

Lives in workflow/ for the same reason as workflow/meshing.py: it joins core, geometry (part bounds) and
foam (solver files).
"""

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

from pydantic import ValidationError

from vortexcfd.core.model import AsymptoticCriterion, Simulation
from vortexcfd.core.reports import missing_reference, report_label
from vortexcfd.core.project import Project
from vortexcfd.foam.case_writer import enable_clean_stop
from vortexcfd.foam.dictfile import write_foam_file
from vortexcfd.foam.mesh_case import MARKER_NAME, part_force_groups, remove_results
from vortexcfd.foam.mesh_report import lost_part_message
from vortexcfd.geometry.domain import ground_wall_start
from vortexcfd.foam.parallel import physical_cores
from vortexcfd.foam.physics_case import (
    InternalInlet,
    InternalOutlet,
    InternalSetup,
    SolverCaseInput,
    build_solver_files,
    far_field_patches,
    internal_turbulence,
    reference_values,
)
from vortexcfd.workflow import internal
from vortexcfd.workflow.meshing import (
    MeshingNotReady,
    _body_parts,
    case_dir_for,
    inputs_hash,
    parts_layout,
    project_estimate,
)


class SolvingNotReady(Exception):
    """The project cannot be solved yet; the message says why."""


def physics_problem(project: Project) -> str | None:
    """Why the physics cannot be run, or None.

    The model is validated again (a project edited outside the Project API may hold invalid
    values) and the reference values used by forceCoeffs must be positive.
    """
    try:
        Simulation.model_validate(project.sim.model_dump())
    except ValidationError as exc:
        err = exc.errors()[0]
        where = ".".join(str(p) for p in err["loc"])
        return f"Invalid physics: {where}: {err['msg']}"
    cores, available = project.sim.solvers.cores, physical_cores()
    if cores > available:
        return f"{cores} cores requested; this machine has {available} physical cores."
    try:
        _box, _names, bounds = parts_layout(project)
    except MeshingNotReady as exc:
        return str(exc)
    if bounds is None:
        return "Import at least one part."
    sim = project.sim
    probes = [p.name for p in sim.reports.probes]
    locations, drops = report_locations(project)
    for i, c in enumerate(sim.solvers.stopping.criteria, start=1):
        if isinstance(c, AsymptoticCriterion):
            why = missing_reference(c.quantity, _names, probes, locations, drops, sim.internal)
            if why is not None:
                return f"Stopping criterion {i} watches {report_label(c.quantity)}: {why}."
    if sim.internal:  # no force coefficients: no reference values to check (D-129)
        return internal_problem(project)
    ref = reference_values(bounds, project.sim.reports, section_span(project) if project.sim.dimension == "2d" else None)
    if ref.l_ref <= 0:
        return "The reference length is zero (the parts have no extent along x): set l_ref."
    if ref.a_ref <= 0:
        return "The reference area is zero (the parts have no extent along x or y): set A_ref."
    return None


def report_locations(project: Project) -> tuple[list[str], list[str]]:
    """(the internal-flow report locations: "patch:<inlet or outlet>" by mesh patch name and "plane:<name>"; the
    pressure-drop names); both empty for external flow (D-129)."""
    sim = project.sim
    if not sim.internal:
        return [], []
    locations = [f"patch:{patch}" for patch, _role in internal.open_patches(project)]
    locations += [f"plane:{plane.name}" for plane in sim.reports.planes]
    return locations, [d.name for d in sim.reports.pressure_drops]


def report_scope(project: Project) -> dict:
    """The keyword arguments of core/reports.available_reports, criterion_quantities and missing_reference for
    ``project``: the force-report patches, the probes and, in internal flow, the locations and pressure drops (D-129)."""
    from vortexcfd.foam.mesh_case import force_report_keys

    sim = project.sim
    locations, drops = report_locations(project)
    return {"patches": list(force_report_keys(sim.geometry.parts)), "probes": [p.name for p in sim.reports.probes],
            "locations": locations, "drops": drops, "internal": sim.internal}


def internal_problem(project: Project) -> str | None:
    """Why an internal-flow project cannot be solved (D-129): the roles, a pressure drop between unknown
    locations."""
    problem = internal.role_problem(project)
    if problem is not None:
        return problem
    locations, _drops = report_locations(project)
    for drop in project.sim.reports.pressure_drops:
        for where in (drop.upstream, drop.downstream):
            if where not in locations:
                return f"Pressure drop {drop.name}: no inlet, outlet or plane {where.partition(':')[2]!r}."
    return None


FAILED_CHECKS_ADVICE = ("the solver must not run on invalid cells: change the mesh settings (refinement, "
                        "layers) and generate the mesh again")


def failed_checks_reason(failed_checks: str | None) -> str | None:
    """The Run Solver reason for a mesh with hard checkMesh failures (MeshReport.failed_checks_message,
    D-096, D-100); soft quality warnings do not block."""
    return None if failed_checks is None else f"The mesh failed checkMesh ({failed_checks}): {FAILED_CHECKS_ADVICE}."


def readiness(project: Project, *, has_mesh: bool, mesh_stale: bool, meshing: bool,
              lost_parts: tuple[str, ...] = (), failed_checks: str | None = None) -> str | None:
    """Why Run Solver is disabled, or None when the solver can run. ``failed_checks``: the mesh's
    MeshReport.failed_checks_message() (a mesh that failed checkMesh blocks the solver, D-096)."""
    if project.path is None:
        return "Save the project first."
    if meshing:
        return "Meshing is running."
    if not has_mesh:
        return "Generate the mesh first."
    if lost_parts:
        return lost_part_message(lost_parts[0]) + ": raise its refinement and generate the mesh again."
    if mesh_stale:
        return "The mesh is out of date: generate it again."
    if failed_checks is not None:
        return failed_checks_reason(failed_checks)
    return physics_problem(project)


def section_span(project: Project, box=None) -> float | None:
    """The span of a 2D section's mesh (D-121; the surface cell size of the meshing estimate), None in 3D."""
    if project.sim.dimension != "2d":
        return None
    box = box if box is not None else parts_layout(project)[0]
    return project_estimate(project, box).span


def case_span(case_dir: Path) -> float | None:
    """The span of a meshed 2D case (D-121): the extrusion thickness in its system/extrudeMeshDict (the mesh in that
    case was made with it); None when the case has none (3D)."""
    from vortexcfd.foam.dictfile import read_foam_file
    from vortexcfd.foam.mesh_case import EXTRUDE_DICT

    path = Path(case_dir) / EXTRUDE_DICT
    if not path.is_file():
        return None
    try:
        return float(read_foam_file(path)["linearDirectionCoeffs"]["thickness"])
    except (KeyError, TypeError, ValueError):
        return None


def for_case(inp: SolverCaseInput, case_dir: Path) -> SolverCaseInput:
    """``inp`` with the span of the 2D mesh in ``case_dir`` (a mesh study level or a sweep point has its own span:
    the reference area chord x span must be that mesh's, D-121); unchanged in 3D."""
    if inp.span is None:
        return inp
    span = case_span(case_dir)
    return dataclasses.replace(inp, span=span) if span is not None else inp


def two_stage_turbulence(project: Project) -> bool:
    """The wall-resolved mode (chosen or automatic, D-123) solves k and omega in two stages (D-126)."""
    mesh = project.sim.mesh
    return mesh.effective_layer_controls == "wall_resolved" and mesh.layer_sizing == "absolute_yplus"


def internal_setup(project: Project) -> InternalSetup:
    """The internal-flow boundaries and planes of ``project`` for the solver files (D-129) [NUMERICS-REVIEW]: the mass
    flow over the reference density (m3/s), pressures over the reference density (kinematic), each inlet's length
    scale (set, else 0.07 D_h of its patch); the initial k and omega from the reference inlet's bulk speed (the
    inflow speed when it has none).

    Raises:
        MeshingNotReady: a part cannot be loaded.
    """
    sim = project.sim
    rho = sim.physics.rho_ref
    _names, meshes = _body_parts(project)
    measures = internal.inlet_measures(project, meshes)
    inlets, outlets = [], []
    for p in internal.patches(project):
        entry = sim.boundary(p.name)
        if p.role == "inlet":
            spec = entry.inlet
            inlets.append(InternalInlet(p.safe, spec.kind, spec.turbulence_intensity,
                                        internal.length_scale(spec, measures[p.safe].hydraulic_diameter),
                                        speed=spec.speed, flow_rate=spec.mass_flow / rho,
                                        total_pressure=spec.total_pressure / rho))
        elif p.role == "outlet":
            outlets.append(InternalOutlet(p.safe, entry.outlet.pressure / rho))
    ref = internal.reference_inlet(project, meshes)
    speed = ref.speed if ref is not None and ref.speed else sim.inflow.speed
    first = inlets[0] if inlets else None
    k0, omega0 = internal_turbulence(speed, first.intensity if first else 0.05,
                                     first.length_scale if first else 0.07 * max(ref.hydraulic_diameter if ref else 1.0, 1e-9))
    planes = []
    for plane in sim.reports.planes:
        n = plane.normal
        length = sum(c * c for c in n) ** 0.5
        planes.append((plane.name, tuple(plane.point), tuple(c / length for c in n)))
    return InternalSetup(tuple(inlets), tuple(outlets), k0, omega0, tuple(planes))


def solver_input(project: Project) -> SolverCaseInput:
    box, names, bounds = parts_layout(project)
    sim = project.sim
    if sim.internal:  # walls only; no far field, symmetry or force groups (D-129)
        two_d = sim.dimension == "2d"
        return SolverCaseInput(sim.physics, sim.inflow, sim.solvers, internal.wall_patches(project), bounds,
                               False, sim.reports, (), (), span=section_span(project, box) if two_d else None,
                               two_stage=two_stage_turbulence(project), internal=internal_setup(project))
    ground = sim.domain.ground.enabled and sim.domain.shape == "box"
    strip = ground_wall_start(sim.domain, box.bounds) is not None  # the slip strip (D-118)
    two_d = sim.dimension == "2d"
    return SolverCaseInput(sim.physics, sim.inflow, sim.solvers, names, bounds,
                           sim.domain.symmetry == "y_min", sim.reports,
                           part_force_groups(sim.geometry.parts),
                           far_field_patches(sim.domain.shape, ground, strip, two_d),
                           ground=sim.domain.ground.motion if ground else None,
                           span=section_span(project, box) if two_d else None,
                           two_stage=two_stage_turbulence(project))


def clear_results(case_dir: Path) -> list[str]:
    """Remove the previous run's outputs before a run: the results (mesh_case.remove_results: time
    directories after 0, postProcessing/, processor* directories, the run record), plus 0/
    (rewritten), the decomposeParDict of an earlier parallel run and the solver, decomposePar and
    reconstructPar logs. constant/polyMesh is never touched."""
    removed = remove_results(case_dir)
    if (case_dir / "0").is_dir():
        shutil.rmtree(case_dir / "0")
    for name in ("log.simpleFoam", "log.decomposePar", "log.reconstructPar", "system/decomposeParDict"):
        (case_dir / name).unlink(missing_ok=True)
    return removed


def prepare_solver_case(project: Project) -> Path:
    """Write the solver files (clean stop enabled) into the meshed case and return its path.

    Raises:
        SolvingNotReady: the project is not saved, or the case directory has no mesh.
    """
    case_dir = case_dir_for(project)
    if case_dir is None:
        raise SolvingNotReady("Save the project first.")
    if not (case_dir / MARKER_NAME).is_file() or not (case_dir / "constant" / "polyMesh").is_dir():
        raise SolvingNotReady(f"No generated mesh in {case_dir}: generate the mesh first.")
    reason = physics_problem(project)
    if reason is not None:
        raise SolvingNotReady(reason)
    files = enable_clean_stop(build_solver_files(for_case(solver_input(project), case_dir)))
    clear_results(case_dir)
    for rel, spec in files.items():
        write_foam_file(case_dir / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    return case_dir


def results_hash(project: Project) -> str:
    """Hash of everything the results depend on: the mesh inputs plus the physics, inflow, solver
    and report settings. Saved results whose hash differs are out of date. The number of cores is
    left out: a parallel run solves the same case (the results agree to solver tolerance, D-063)."""
    sim = project.sim
    payload = {
        "mesh": inputs_hash(project),
        "physics": sim.physics.model_dump(),
        "inflow": sim.inflow.model_dump(),
        "solvers": sim.solvers.model_dump(exclude={"cores"}),
        "reports": sim.reports.model_dump(exclude={"slots"}),  # slot choice does not change results
    }
    if sim.domain.ground.enabled:  # the ground's motion is a solver input only (D-116)
        payload["ground_motion"] = sim.domain.ground.motion
    if two_stage_turbulence(project):  # D-126; single-stage projects keep their hash
        payload["turbulence_stages"] = 2
    if sim.internal:  # the boundaries (D-129); external projects keep their hash
        payload["boundaries"] = [b.model_dump() for b in sim.boundaries]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
