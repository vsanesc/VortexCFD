"""Mesh study orchestration: project -> level cases in <project dir>/case_study (Qt-free). (D-066)

Lives in workflow/ for the same reason as workflow/meshing.py: it joins core, geometry (surfaces, domain) and
foam (case files). case/ is never touched: every level is a marker-protected case directory of its
own, <project dir>/case_study/level_<n>/.
"""

import dataclasses
import shutil
from collections.abc import Collection
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
    LEVEL_POSITIONS,
    STUDY_DIR_NAME,
    LayerStack,
    LevelResult,
    StudyLevel,
    StudyRecord,
    estimate_seconds,
    level_dir,
    level_factors,
    reference_layers,
    study_levels,
)
from vortexcfd.foam.run_record import read_run_record
from vortexcfd.foam.yplus import (WR_MAX_CELL_TO_FIRST, first_layer_thickness, plan_wall_resolved,
                                  wall_resolved_surface_size)
from vortexcfd.geometry.domain import ground_wall_start, union_bounds
from vortexcfd.workflow.meshing import (
    MeshingNotReady,
    _junction_features,
    _loaded_parts,
    _part_overrides,
    _volume_entries,
    body_bounds,
    meshing_settings,
    case_dir_for,
    domain_fields,
    internal_fields,
    estimate_for,
    flow_speed,
    mesh_cores,
    readiness,
    surface_length,
    write_domain_surface,
    write_junction_features,
    write_part_surfaces,
)
from vortexcfd.workflow import internal
from vortexcfd.workflow.solving import clear_results, for_case, physics_problem, solver_input
from vortexcfd.foam.physics_case import build_solver_files

# Background cells per total cell of a meshed case, used for the estimate when the current case
# has no mesh record yet (the default sphere: 192,220 cells from about 100,000 background cells).
DEFAULT_CELLS_PER_BACKGROUND_CELL = 1.9


def dimensions(box) -> int:
    return 2 if box.two_d else 3


def domain_measure(box) -> float:
    """The domain's volume, or its area in the x-z plane for a 2D section (D-121): the volume over its y extent."""
    if not box.two_d:
        return box.volume
    return box.volume / (box.bounds[3] - box.bounds[2])


def level_layers(project: Project, plan: "StudyPlan", lp: "LevelPlan") -> tuple[float, int, float] | None:
    """(first layer, count, expansion) of a level: the shared stack of the current settings (D-066), except for
    the wall-resolved controls (D-122), where every level keeps the y+ first layer and the ratio and grows its
    stack to one of its own surface cells (a stack thinner than the cell next to it collapses). None: no layers.
    [NUMERICS-REVIEW]"""
    if plan.layers is None:
        return None
    mesh = project.sim.mesh
    if mesh.effective_layer_controls == "wall_resolved" and mesh.layer_sizing == "absolute_yplus":  # D-123 too
        own = plan_wall_resolved(plan.layers.first, lp.estimate.surface_size)
        return plan.layers.first, own.count, own.expansion
    return plan.layers.first, plan.layers.count, plan.layers.expansion


def level_buffer_scale(plan: "StudyPlan", lp: "LevelPlan") -> float:
    """The current settings' background cell over the level's (about 1 / its factor; exactly 1 for the current
    level): the level keeps the current settings' refinement regions in metres (D-127). [NUMERICS-REVIEW]"""
    if plan.current_base is None or not lp.estimate.base_size or lp.level.factor == 1.0:
        return 1.0
    return plan.current_base / lp.estimate.base_size


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
    current_base: float | None = None  # the current settings' background cell (D-127: the regions' metres)
    current_as: str = "fine"  # the level the current settings are: the user's choice, or the study's (D-128)
    current_as_note: str | None = None  # why the study chose it, None: the user's choice


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
    length = surface_length(project, box, body_bounds(project)).value
    mesh = meshing_settings(project, box, length)  # the wall-resolved levels (D-122)
    current = estimate_for(box, mesh, length)
    yplus_first = None
    if mesh.layer_sizing == "absolute_yplus":
        yplus_first = first_layer_thickness(mesh.target_yplus, flow_speed(project), project.sim.physics.nu,
                                            length, mesh.yplus_at)  # Re on the surface size length (D-088); the
        # internal-flow speed is the reference inlet's (D-129)
    layers = reference_layers(mesh, current.surface_size, yplus_first)
    if mesh.layer_controls == "wall_resolved" and yplus_first is not None:  # D-122: the stack of the current level
        plan = plan_wall_resolved(yplus_first, current.surface_size)
        layers = LayerStack(yplus_first, plan.count, plan.expansion)
    volume = domain_measure(box)  # the actual domain volume (D-078); the area in 2D (D-121)
    ratio, measured = DEFAULT_CELLS_PER_BACKGROUND_CELL, False
    case = case_dir_for(project)
    record = read_mesh_record(case) if case is not None else None
    if record is not None and record.report is not None and record.report.cells and current.total_cells:
        ratio, measured = record.report.cells / current.total_cells, True
    per_cell_it, last_cores = _seconds_per_cell_iteration(project)
    plans, warning = [], None
    current_as, note = study_current_as(mesh, current.surface_size, yplus_first, settings.ratio, settings.current_as)
    for level in study_levels(mesh, settings.ratio, current_as, dimensions(box)):
        est = estimate_for(box, level.mesh, length)
        cells = round(est.total_cells * ratio)
        seconds = estimate_seconds(per_cell_it, cells, project.sim.solvers.iterations, last_cores, settings.cores)
        plans.append(LevelPlan(level, est, cells, seconds))
        if est.too_many_cells:
            warning = (f"The {level.name} level would have {est.total_cells:,} background cells (limit "
                       f"{MAX_BACKGROUND_CELLS:,}): lower the ratio or the background cell target.")
    return StudyPlan(plans, layers, volume, ratio, measured, warning, current.base_size, current_as, note)


def study_current_as(mesh, surface_size: float, yplus_first: float | None, ratio: float,
                     chosen: str) -> tuple[str, str | None]:
    """(the level the current settings are, why the study chose it or None) (D-128) [NUMERICS-REVIEW]: with the
    wall-resolved controls (chosen or automatic) the coarsest level's surface cell must stay within the
    first-layer limit (WR_MAX_CELL_TO_FIRST first layers, D-122), so the user's choice is kept when its coarse level
    does, else the next position that does (fine -> medium -> coarse; as the coarse level the current settings,
    which meshing keeps within the limit, are the coarsest)."""
    if mesh.effective_layer_controls != "wall_resolved" or yplus_first is None:
        return chosen, None
    limit = wall_resolved_surface_size(yplus_first)
    order = LEVEL_POSITIONS[LEVEL_POSITIONS.index(chosen):]
    for position in order:
        coarsest = surface_size * max(level_factors(ratio, position))
        if coarsest <= limit * (1 + 1e-9):
            break
    if position == chosen:
        return chosen, None
    over = surface_size * max(level_factors(ratio, chosen))
    return position, (f"current settings as the {position} level: as the {chosen} level the coarse level's surface "
                      f"cell ({1e3 * over:.3g} mm) would exceed the wall-resolved limit ({1e3 * limit:.3g} mm, "
                      f"{WR_MAX_CELL_TO_FIRST:g} first layers, D-122)")


def study_readiness(project: Project, *, busy: str | None = None) -> str | None:
    """Why the mesh study cannot start, or None."""
    if project.path is None:
        return "Save the project first."
    if busy:
        return busy
    if not project.sim.studies.mesh.quantities:
        return "Choose at least one quantity to study."
    if project.sim.internal:  # D-129: no force coefficients; an inlet, outlet, plane or pressure drop may be gone
        from vortexcfd.core.reports import missing_reference, report_label
        from vortexcfd.workflow.solving import report_scope

        scope = report_scope(project)
        for quantity in project.sim.studies.mesh.quantities:
            why = missing_reference(quantity, **scope)
            if why is not None:
                return f"Study quantity {report_label(quantity)}: {why}."
    try:
        plan = plan_study(project)
    except MeshingNotReady as exc:
        return str(exc)
    if plan.warning:
        return plan.warning
    return physics_problem(project)


def prepare_study(project: Project, only: Collection[str] | None = None) -> tuple[Path, StudyRecord, MeshCaseInput]:
    """Write the meshing case of every level into <project dir>/case_study/level_<n>/ and return
    (study dir, the initial record, the inputs of the last level). ``only``: the names of the levels to
    prepare (and record); the other levels' directories are left as they are, so a level can be run on
    its own after another one (None: every level).

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
    safe = safe_part_names(names, project.sim.internal)
    study = study_dir_for(project)
    study.mkdir(parents=True, exist_ok=True)
    fixed = (plan.layers.first, plan.layers.count) if plan.layers is not None else None
    body = body_bounds(project)  # the reference values' basis, never rotated (D-120)
    length = surface_length(project, box, body).value
    # The refinement volumes and junction curves keep the current settings' refinement levels on every
    # level: a level scales the base size and every target size by the same factor, so each level number
    # is unchanged and the cells inside them scale like the rest (D-117). [NUMERICS-REVIEW]
    volumes = _volume_entries(project, box, body)
    features = _junction_features(project, box, length)
    levels, inputs = [], None
    for lp in plan.levels:
        if only is not None and lp.level.name not in only:
            continue
        stack = level_layers(project, plan, lp)
        inputs = MeshCaseInput(
            domain_bounds=box.bounds, symmetric=project.sim.domain.symmetry == "y_min", parts=tuple(safe),
            parts_bounds=union_bounds(bounds), reference_length=box.reference_length, mesh=lp.level.mesh,
            part_bounds=tuple(bounds), part_levels=_part_overrides(project),
            part_patches=tuple(part_patch_names(project.sim.geometry.parts, project.sim.internal)),
            fixed_layers=(stack[0], stack[1]) if stack is not None else (1.0, 0),
            layer_expansion=stack[2] if stack is not None else None,
            surface_length=length, volumes=volumes, extra_features=features,
            ground=box.ground, ground_layers=box.ground and project.sim.domain.ground.layers,
            ground_wall_start=ground_wall_start(project.sim.domain, box.bounds),
            two_d=box.two_d, buffer_scale=level_buffer_scale(plan, lp),  # the current regions everywhere (D-127)
            study_level=True,  # every 3D level with the shells, the current one included (D-127)
            **domain_fields(box),
            **internal_fields(project, box),
        )
        if box.internal:  # the locationInMesh inside the geometry on this level's own grid (D-129)
            inputs = internal.with_location(inputs, meshes)
        case = level_dir(study, lp.level.index)
        if case.is_dir():
            clear_results(case) if (case / "constant" / "polyMesh").is_dir() else None
        prepare_case_dir(case, build_mesh_files(inputs))
        write_part_surfaces(case, project, inputs, meshes)
        write_domain_surface(case, box, inputs)
        write_domain_guard(case, inputs)
        write_seed_edge_meshes(case, inputs)
        write_junction_features(case, project, inputs)
        planned = [stack[0], stack[1]] if stack is not None and project.sim.mesh.layer_sizing == "absolute_yplus" else []
        levels.append(LevelResult(lp.level.index, lp.level.name, lp.level.factor, estimated_cells=lp.estimated_cells,
                                  planned_layers=planned))
    # every level meshes on the project's meshing cores (Mesh.cores, else automatic), one level at a time (D-111)
    record = StudyRecord(settings.ratio, plan.current_as, list(settings.quantities), settings.cores,
                         plan.domain_volume, levels, mesh_cores=mesh_cores(project, box).used, dimensions=dimensions(box),
                         current_as_note=plan.current_as_note)
    return study, record, inputs


def solver_writer(project: Project):
    """A callable writing the project's solver files (clean stop, the study's cores) into a meshed
    level directory, run on the study's worker thread (it uses only plain data captured here). A 2D level's
    reference area uses that level's own span (D-121)."""
    inp = solver_input(project)
    cores = project.sim.studies.mesh.cores
    inp = dataclasses.replace(inp, solvers=inp.solvers.model_copy(update={"cores": cores}))

    def write(case: Path) -> None:
        for name in ("0",):
            if (case / name).is_dir():
                shutil.rmtree(case / name)
        for rel, spec in enable_clean_stop(build_solver_files(for_case(inp, case))).items():
            write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)

    return write
