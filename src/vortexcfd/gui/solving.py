"""Solver orchestration: project -> solver case files in <project dir>/case (Qt-free).

Lives in gui/ for the same reason as gui/meshing.py: it joins core, geometry (part bounds) and
foam (solver files).
"""

import hashlib
import json
import shutil
from pathlib import Path

from pydantic import ValidationError

from vortexcfd.core.model import Simulation
from vortexcfd.core.project import Project
from vortexcfd.foam.case_writer import enable_clean_stop
from vortexcfd.foam.dictfile import write_foam_file
from vortexcfd.foam.mesh_case import MARKER_NAME
from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files, reference_values
from vortexcfd.foam.run_record import remove_run_record
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
    try:
        _box, _names, bounds = parts_layout(project)
    except MeshingNotReady as exc:
        return str(exc)
    if bounds is None:
        return "Import at least one part."
    ref = reference_values(bounds, project.sim.reports)
    if ref.l_ref <= 0:
        return "The reference length is zero (the parts have no extent along x): set l_ref."
    if ref.a_ref <= 0:
        return "The reference area is zero (the parts have no extent along x or y): set A_ref."
    return None


def readiness(project: Project, *, has_mesh: bool, mesh_stale: bool, meshing: bool) -> str | None:
    """Why Run Solver is disabled, or None when the solver can run."""
    if project.path is None:
        return "Save the project first."
    if meshing:
        return "Meshing is running."
    if not has_mesh:
        return "Generate the mesh first."
    if mesh_stale:
        return "The mesh is out of date: generate it again."
    return physics_problem(project)


def solver_input(project: Project) -> SolverCaseInput:
    _box, names, bounds = parts_layout(project)
    sim = project.sim
    return SolverCaseInput(sim.physics, sim.inflow, sim.solvers, names, bounds,
                           sim.domain.symmetry == "y_min", sim.reports)


def _is_result_time(name: str) -> bool:
    try:
        return float(name) > 0
    except ValueError:
        return False


def clear_results(case_dir: Path) -> None:
    """Remove the previous run's outputs: time directories after 0, postProcessing/, the 0/
    directory (rewritten), the solver log and the run record. constant/polyMesh is never touched."""
    for child in case_dir.iterdir():
        if child.is_dir() and (_is_result_time(child.name) or child.name in ("postProcessing", "0")):
            shutil.rmtree(child)
    (case_dir / "log.simpleFoam").unlink(missing_ok=True)
    remove_run_record(case_dir)


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
    and report settings. Saved results whose hash differs are out of date."""
    sim = project.sim
    payload = {
        "mesh": inputs_hash(project),
        "physics": sim.physics.model_dump(),
        "inflow": sim.inflow.model_dump(),
        "solvers": sim.solvers.model_dump(),
        "reports": sim.reports.model_dump(exclude={"slots"}),  # slot choice does not change results
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
