"""Mesh study orchestration: project -> level cases in <project dir>/case_study (Qt-free). (D-066)

Lives in gui/ for the same reason as gui/meshing.py: it joins core, geometry (surfaces, domain) and
foam (case files). case/ is never touched: every level is a marker-protected case directory of its
own, <project dir>/case_study/level_<n>/.
"""

import dataclasses
import shutil
from dataclasses import dataclass
from pathlib import Path

from vortexcfd.core.project import Project
from vortexcfd.foam.case_writer import enable_clean_stop
from vortexcfd.foam.dictfile import write_foam_file
from vortexcfd.foam.mesh_case import (
    TRI_SURFACE,
    MeshCaseInput,
    build_mesh_files,
    prepare_case_dir,
    write_domain_guard,
    write_seed_edge_meshes,
)
from vortexcfd.foam.mesh_estimate import MAX_BACKGROUND_CELLS, MeshEstimate
from vortexcfd.foam.mesh_record import read_mesh_record
from vortexcfd.foam.mesh_study import (
    STUDY_DIR_NAME,
    LayerStack,
    LevelResult,
    StudyLevel,
    StudyRecord,
    estimate_seconds,
    level_dir,
    reference_layers,
    study_levels,
)
from vortexcfd.foam.run_record import read_run_record
from vortexcfd.foam.yplus import first_layer_thickness
from vortexcfd.geometry.domain import union_bounds
from vortexcfd.gui.meshing import (
    MeshingNotReady,
    _loaded_parts,
    _part_overrides,
    case_dir_for,
    domain_fields,
    estimate_for,
    readiness,
    write_domain_surface,
    write_part_surfaces,
)
from vortexcfd.gui.solving import clear_results, physics_problem, solver_input
from vortexcfd.foam.physics_case import build_solver_files

# Background cells per total cell of a meshed case, used for the estimate when the current case
# has no mesh record yet (the default sphere: 192,220 cells from about 100,000 background cells).
DEFAULT_CELLS_PER_BACKGROUND_CELL = 1.9


def study_dir_for(project: Project) -> Path | None:
    return project.path.parent / STUDY_DIR_NAME if project.path is not None else None


@dataclass(frozen=True)
class LevelPlan:
    level: StudyLevel
    estimate: MeshEstimate
    estimated_cells: int  # total, scaled from the current mesh's cells per background cell
    estimated_seconds: float | None  # solver time up to the iteration limit


@dataclass(frozen=True)
class StudyPlan:
    levels: list[LevelPlan]
    layers: LayerStack | None
    domain_volume: float
    cells_per_background: float  # from the current mesh, or the default
    measured: bool  # cells_per_background and the time come from the current case
    warning: str | None  # a level above the background cell limit, etc.


def _seconds_per_cell_iteration(project: Project) -> tuple[float | None, int]:
    """(seconds per cell and iteration, cores) of the last run in case/ (None: unknown)."""
    case = case_dir_for(project)
    if case is None:
        return None, 1
    record, mesh = read_run_record(case), read_mesh_record(case)
    if record is None or mesh is None or not record.duration_s or not record.iterations:
        return None, 1
    cells = mesh.report.cells if mesh.report is not None else None
    if not cells:
        return None, 1
    return record.duration_s / (cells * record.iterations), max(1, record.cores)


def plan_study(project: Project) -> StudyPlan:
    """The three levels of the project's mesh study with their estimates.

    Raises:
        MeshingNotReady: the project cannot be meshed (readiness says why) or a part cannot be loaded.
    """
    reason = readiness(project)
    if reason is not None and "background mesh would have" not in reason:
        raise MeshingNotReady(reason)
    settings = project.sim.studies.mesh
    box, _names, _meshes = _loaded_parts(project)
    mesh = project.sim.mesh
    current = estimate_for(box, mesh)
    yplus_first = None
    if mesh.layer_sizing == "absolute_yplus":
        yplus_first = first_layer_thickness(mesh.target_yplus, project.sim.inflow.speed, project.sim.physics.nu,
                                            box.reference_length)
    layers = reference_layers(mesh, current.surface_size, yplus_first)
    volume = box.volume  # the actual domain volume (D-078)
    ratio, measured = DEFAULT_CELLS_PER_BACKGROUND_CELL, False
    case = case_dir_for(project)
    record = read_mesh_record(case) if case is not None else None
    if record is not None and record.report is not None and record.report.cells and current.total_cells:
        ratio, measured = record.report.cells / current.total_cells, True
    per_cell_it, last_cores = _seconds_per_cell_iteration(project)
    plans, warning = [], None
    for level in study_levels(mesh, settings.ratio, settings.current_as):
        est = estimate_for(box, level.mesh)
        cells = round(est.total_cells * ratio)
        seconds = estimate_seconds(per_cell_it, cells, project.sim.solvers.iterations, last_cores, settings.cores)
        plans.append(LevelPlan(level, est, cells, seconds))
        if est.too_many_cells:
            warning = (f"The {level.name} level would have {est.total_cells:,} background cells (limit "
                       f"{MAX_BACKGROUND_CELLS:,}): lower the ratio or the background cell target.")
    return StudyPlan(plans, layers, volume, ratio, measured, warning)


def study_readiness(project: Project, *, busy: str | None = None) -> str | None:
    """Why the mesh study cannot start, or None."""
    if project.path is None:
        return "Save the project first."
    if busy:
        return busy
    if not project.sim.studies.mesh.quantities:
        return "Choose at least one quantity to study."
    try:
        plan = plan_study(project)
    except MeshingNotReady as exc:
        return str(exc)
    if plan.warning:
        return plan.warning
    return physics_problem(project)


def prepare_study(project: Project) -> tuple[Path, StudyRecord, MeshCaseInput]:
    """Write the meshing case of every level into <project dir>/case_study/level_<n>/ and return
    (study dir, the initial record, the inputs of the last level).

    Raises:
        MeshingNotReady: see ``study_readiness``.
        CaseDirectoryNotOursError: a level directory exists and was not generated by VortexCFD.
    """
    reason = study_readiness(project)
    if reason is not None:
        raise MeshingNotReady(reason)
    plan = plan_study(project)
    settings = project.sim.studies.mesh
    box, names, meshes = _loaded_parts(project)
    from vortexcfd.foam.mesh_case import part_patch_names, safe_part_names

    bounds = [tuple(float(x) for x in m.bounds) for m in meshes]
    safe = safe_part_names(names)
    study = study_dir_for(project)
    study.mkdir(parents=True, exist_ok=True)
    fixed = (plan.layers.first, plan.layers.count) if plan.layers is not None else None
    levels, inputs = [], None
    for lp in plan.levels:
        inputs = MeshCaseInput(
            domain_bounds=box.bounds, symmetric=project.sim.domain.symmetry == "y_min", parts=tuple(safe),
            parts_bounds=union_bounds(bounds), reference_length=box.reference_length, mesh=lp.level.mesh,
            part_bounds=tuple(bounds), part_levels=_part_overrides(project),
            part_patches=tuple(part_patch_names(project.sim.geometry.parts)),
            fixed_layers=fixed if fixed is not None else (1.0, 0),
            **domain_fields(box),
        )
        case = level_dir(study, lp.level.index)
        if case.is_dir():
            clear_results(case) if (case / "constant" / "polyMesh").is_dir() else None
        prepare_case_dir(case, build_mesh_files(inputs))
        write_part_surfaces(case, project, inputs, meshes)
        write_domain_surface(case, box, inputs)
        write_domain_guard(case, inputs)
        write_seed_edge_meshes(case, inputs)
        levels.append(LevelResult(lp.level.index, lp.level.name, lp.level.factor, estimated_cells=lp.estimated_cells))
    record = StudyRecord(settings.ratio, settings.current_as, list(settings.quantities), settings.cores,
                         plan.domain_volume, levels)
    return study, record, inputs


def solver_writer(project: Project):
    """A callable writing the project's solver files (clean stop, the study's cores) into a meshed
    level directory, run on the study's worker thread (it uses only plain data captured here)."""
    inp = solver_input(project)
    cores = project.sim.studies.mesh.cores
    inp = dataclasses.replace(inp, solvers=inp.solvers.model_copy(update={"cores": cores}))
    files = enable_clean_stop(build_solver_files(inp))

    def write(case: Path) -> None:
        for name in ("0",):
            if (case / name).is_dir():
                shutil.rmtree(case / name)
        for rel, spec in files.items():
            write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)

    return write
