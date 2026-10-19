"""Polar sweep orchestration: project -> <project dir>/case_sweep (Qt-free). (D-067)

Every point uses the current mesh of case/ (copied once into case_sweep/mesh/polyMesh) and the
project's physics with its own angle of attack; case/ is never written.
"""

import dataclasses
import shutil
from pathlib import Path

from vortexcfd.core.project import Project
from vortexcfd.foam.case_writer import enable_clean_stop
from vortexcfd.foam.dictfile import write_foam_file
from vortexcfd.foam.physics_case import build_solver_files
from vortexcfd.foam.polar_sweep import SWEEP_DIR_NAME, SweepRecord, copy_mesh, new_record
from vortexcfd.workflow.meshing import case_dir_for
from vortexcfd.workflow.solving import physics_problem, solver_input


def sweep_dir_for(project: Project) -> Path | None:
    return project.path.parent / SWEEP_DIR_NAME if project.path is not None else None


def sweep_readiness(project: Project, *, has_mesh: bool, mesh_stale: bool, lost_parts: tuple[str, ...] = (),
                    busy: str | None = None, failed_checks: str | None = None) -> str | None:
    """Why the polar sweep cannot start, or None."""
    if project.path is None:
        return "Save the project first."
    if busy:
        return busy
    if not has_mesh:
        return "Generate the mesh first: every point uses the current mesh."
    if lost_parts:
        return "The mesh lost a part: generate it again."
    if mesh_stale:
        return "The mesh is out of date: generate it again."
    if failed_checks is not None:  # D-096
        from vortexcfd.workflow.solving import failed_checks_reason

        return failed_checks_reason(failed_checks)
    if not project.sim.studies.polar.alphas():
        return "The sweep has no angle of attack."
    return physics_problem(project)


def prepare_sweep(project: Project) -> tuple[Path, SweepRecord]:
    """Copy the current mesh into case_sweep/mesh/ (removing the previous sweep's points) and
    return (sweep dir, the initial record)."""
    sweep = sweep_dir_for(project)
    if sweep is None:
        raise ValueError("Save the project first.")
    if sweep.is_dir():
        for child in sweep.glob("point_*"):
            shutil.rmtree(child, ignore_errors=True)
    copy_mesh(case_dir_for(project), sweep)
    settings = project.sim.studies.polar
    return sweep, new_record(settings.alphas(), settings.cores, settings.init_from_previous)


def point_writer(project: Project):
    """A callable writing a point's solver files at an angle of attack (plain data captured here,
    run on the sweep's worker thread)."""
    inp = solver_input(project)
    cores = project.sim.studies.polar.cores
    solvers = inp.solvers.model_copy(update={"cores": cores})

    def write(case: Path, alpha: float) -> None:
        point = dataclasses.replace(inp, inflow=inp.inflow.model_copy(update={"alpha_deg": alpha}), solvers=solvers)
        for rel, spec in enable_clean_stop(build_solver_files(point)).items():
            write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)

    return write
