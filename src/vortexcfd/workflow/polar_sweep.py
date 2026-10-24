"""Polar sweep orchestration: project -> <project dir>/case_sweep (Qt-free). (D-067, D-120)

Every angle gets its own meshing case, case_sweep/point_<n>/, with the parts rotated to that angle (the
project's mesh settings, domain and refinement volumes), and the project's physics; case/ is never written.
The point cases are written on the sweep's worker thread just before each point is meshed, from a copy of
the project taken when the sweep starts.
"""

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

from vortexcfd.core.project import Project
from vortexcfd.foam.case_writer import enable_clean_stop
from vortexcfd.foam.dictfile import write_foam_file
from vortexcfd.foam.mesh_case import MARKER_NAME, build_mesh_files, prepare_case_dir, write_domain_guard, write_seed_edge_meshes
from vortexcfd.foam.physics_case import build_solver_files
from vortexcfd.foam.polar_sweep import SWEEP_DIR_NAME, SweepRecord, new_record, point_dir, read_record, resume_record
from vortexcfd.workflow.meshing import (
    mesh_cores,
    mesh_inputs,
    readiness,
    write_domain_surface,
    write_junction_features,
    write_part_surfaces,
)
from vortexcfd.workflow.solving import clear_results, for_case, physics_problem, results_hash, solver_input


def sweep_dir_for(project: Project) -> Path | None:
    return project.path.parent / SWEEP_DIR_NAME if project.path is not None else None


def at_angle(project: Project, alpha: float) -> Project:
    """A copy of ``project`` (same folder, no history) at the angle of attack ``alpha``."""
    sim = project.sim
    sim.inflow = sim.inflow.model_copy(update={"alpha_deg": float(alpha)})
    return Project(sim, project.path)


def sweep_readiness(project: Project, *, busy: str | None = None) -> str | None:
    """Why the polar sweep cannot start, or None: the project must be meshable at every angle (a rotated
    part must stay in the domain and above the ground, D-120) and its physics runnable."""
    if project.path is None:
        return "Save the project first."
    if busy:
        return busy
    if not project.sim.studies.polar.enabled:
        return "The polar sweep is off: enable it first (Reports & Monitors > Polar sweep)."
    alphas = project.sim.studies.polar.alphas()
    if not alphas:
        return "The sweep has no angle of attack."
    for alpha in alphas:
        reason = readiness(at_angle(project, alpha))
        if reason is not None:
            return f"At {alpha:g} deg: {reason}" if alpha != project.sim.inflow.alpha_deg else reason
    return physics_problem(project)


def sweep_hash(project: Project) -> str:
    """Hash of everything a point depends on but its angle (the mesh and results inputs at alpha 0 and the
    sweep's solver cores are in the record itself): a sweep resumes only while it is unchanged."""
    base = at_angle(project, 0.0)
    payload = {"results": results_hash(base), "rotation_centre": project.sim.reports.center_of_rotation,
               "volumes": [v.model_dump(mode="json") for v in project.sim.refinement_volumes if v.enabled]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def prepare_sweep(project: Project, resume: bool = True) -> tuple[Path, SweepRecord]:
    """(sweep dir, the record to run). With ``resume`` the finished points of the previous record of the
    same sweep (same angles, cores and inputs) are kept and only the others will run; otherwise, or when the
    sweep changed, every point runs and the point directories of the previous sweep are removed.

    Raises:
        ValueError: the project is not saved.
        MeshingNotReady: the project cannot be meshed.
    """
    sweep = sweep_dir_for(project)
    if sweep is None:
        raise ValueError("Save the project first.")
    settings = project.sim.studies.polar
    inputs, box, _meshes = mesh_inputs(project)
    first = (inputs.first_layer_thickness, inputs.layer_count or 1) if inputs.first_layer_thickness else None
    fresh = new_record(settings.alphas(), settings.cores, mesh_cores(project, box).used, sweep_hash(project), first)
    record = resume_record(read_record(sweep), fresh) if resume else fresh
    keep = {point_dir(sweep, p.index).name for p in record.points if p.finished and record is not fresh}
    if sweep.is_dir():
        for child in sweep.glob("point_*"):
            if child.name not in keep and child.is_dir():
                if (child / MARKER_NAME).is_file() or not any(child.iterdir()):
                    shutil.rmtree(child, ignore_errors=True)
    sweep.mkdir(parents=True, exist_ok=True)
    return sweep, record


def point_preparer(project: Project):
    """A callable writing a point's meshing case at an angle of attack (run on the sweep's worker thread;
    it works on a copy of the project taken here)."""
    base = Project(project.sim, project.path)

    def prepare(case: Path, alpha: float) -> None:
        rotated = at_angle(base, alpha)
        inputs, box, meshes = mesh_inputs(rotated)
        if (case / MARKER_NAME).is_file():  # a point run again (resumed): its earlier results go
            clear_results(case)
        prepare_case_dir(case, build_mesh_files(inputs))
        write_junction_features(case, rotated, inputs)
        write_part_surfaces(case, rotated, inputs, meshes)
        write_domain_surface(case, box, inputs)
        write_domain_guard(case, inputs)
        write_seed_edge_meshes(case, inputs)

    return prepare


def point_writer(project: Project):
    """A callable writing a point's solver files at an angle of attack (plain data captured here, run on
    the sweep's worker thread)."""
    inp = solver_input(project)
    cores = project.sim.studies.polar.cores
    solvers = inp.solvers.model_copy(update={"cores": cores})

    def write(case: Path, alpha: float) -> None:
        point = dataclasses.replace(inp, inflow=inp.inflow.model_copy(update={"alpha_deg": alpha}), solvers=solvers)
        if (case / "0").is_dir():
            shutil.rmtree(case / "0")
        for rel, spec in enable_clean_stop(build_solver_files(for_case(point, case))).items():
            write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)

    return write

