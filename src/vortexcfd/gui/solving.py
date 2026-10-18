"""Solver orchestration: project -> solver case files in <project dir>/case (Qt-free).

Lives in gui/ for the same reason as gui/meshing.py: it joins core, geometry (part bounds) and
foam (solver files).
"""

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
from vortexcfd.foam.mesh_case import MARKER_NAME, remove_results
from vortexcfd.foam.mesh_report import lost_part_message
from vortexcfd.foam.parallel import physical_cores
from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files, reference_values
from vortexcfd.gui.meshing import MeshingNotReady, case_dir_for, inputs_hash, parts_layout


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
    for i, c in enumerate(sim.solvers.stopping.criteria, start=1):
        if isinstance(c, AsymptoticCriterion):
            why = missing_reference(c.quantity, _names, probes)
            if why is not None:
                return f"Stopping criterion {i} watches {report_label(c.quantity)}: {why}."
    ref = reference_values(bounds, project.sim.reports)
    if ref.l_ref <= 0:
        return "The reference length is zero (the parts have no extent along x): set l_ref."
    if ref.a_ref <= 0:
        return "The reference area is zero (the parts have no extent along x or y): set A_ref."
    return None


def readiness(project: Project, *, has_mesh: bool, mesh_stale: bool, meshing: bool,
              lost_parts: tuple[str, ...] = ()) -> str | None:
    """Why Run Solver is disabled, or None when the solver can run."""
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
    return physics_problem(project)


def solver_input(project: Project) -> SolverCaseInput:
    _box, names, bounds = parts_layout(project)
    sim = project.sim
    return SolverCaseInput(sim.physics, sim.inflow, sim.solvers, names, bounds,
                           sim.domain.symmetry == "y_min", sim.reports)


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
    files = enable_clean_stop(build_solver_files(solver_input(project)))
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
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
