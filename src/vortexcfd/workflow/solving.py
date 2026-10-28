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
from vortexcfd.foam.case_writer import enable_clean_stop, enable_write_now, write_spec
from vortexcfd.foam.live_view import LivePlane, LiveViewSpec, safe_name
from vortexcfd.foam.mesh_case import MARKER_NAME, part_force_groups, remove_results
from vortexcfd.foam.mesh_report import lost_part_message
from vortexcfd.foam.results import latest_result_time
from vortexcfd.foam.solver_run import SOLVERS, solver_log
from vortexcfd.foam.transient import TRANSIENT_FILE
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
    boundary_problem,
    face_kinds,
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
    problem = transient_problem(project, _names, probes, locations, drops)
    if problem is not None:
        return problem
    if sim.internal:  # no force coefficients: no reference values to check (D-129)
        return internal_problem(project)
    ref = reference_values(bounds, project.sim.reports, section_span(project) if project.sim.dimension == "2d" else None)
    if ref.l_ref <= 0:
        return "The reference length is zero (the parts have no extent along x): set l_ref."
    if ref.a_ref <= 0:
        return "The reference area is zero (the parts have no extent along x or y): set A_ref."
    return None


def convective_time(project: Project) -> float | None:
    """t_c = l_ref / U in seconds (D-181), None without a part."""
    try:
        _box, _names, bounds = parts_layout(project)
    except (MeshingNotReady, TypeError, ValueError, OSError):  # no part file, or an unsaved project
        return None
    if bounds is None:
        return None
    return reference_values(bounds, project.sim.reports).l_ref / project.sim.inflow.speed


def transient_problem(project: Project, names, probes, locations, drops) -> str | None:
    """Why a transient project cannot be run (D-181), or None: internal flow has no force history to detect the
    sampling start from; the statistics stop's quantity must be a report of the project; a start from the steady
    solution needs one."""
    sim = project.sim
    if not sim.physics.transient:
        return None
    settings = sim.solvers.transient
    if sim.internal and settings.sampling_start is None:
        return ("Transient internal flow: set the sampling start (Solvers > Transient): there are no force "
                "coefficients to detect the end of the start-up transient from.")
    if settings.statistics_stop:
        why = missing_reference(settings.stop_quantity, names, probes, locations, drops, sim.internal)
        if why is not None:
            return f"The statistics stop watches {report_label(settings.stop_quantity)}: {why}."
    end = 0.0 if sim.internal else settings.perturbation_end(convective_time(project))
    if settings.sampling_start is not None and settings.sampling_start < end:  # D-187, D-198: never sampled
        unit = "flow-through times" if settings.time_unit == "flow_through" else "s"
        return (f"The sampling starts at {settings.sampling_start:g} {unit}, inside the start-up perturbation (it "
                f"ends at {end:g} {unit}): start the sampling later, or turn the perturbation off "
                "(Solvers > Transient).")
    if sim.physics.ddes and sim.dimension == "2d":
        return ("DDES resolves three-dimensional turbulence: a 2D project cannot use it. Choose k-\u03c9 SST (URANS) "
                "or make the project 3D.")
    if settings.start_from == "steady":
        case_dir = case_dir_for(project)
        if case_dir is not None and steady_start_time(case_dir) is None:
            return ("Start from the steady solution: this project has no steady solution on the current mesh; run "
                    "it steady first, or start from the free stream.")
    return None


# The DDES grid guidance (D-191) [NUMERICS-REVIEW], from Spalart, "Young-person's guide to detached-eddy simulation
# grids", NASA/CR-2001-211032 (2001): the focus region (where the separated turbulence must be resolved, here the
# finest refinement volume) needs "a minimum of 32^3" cells of the target spacing Delta_0 to cover it (section
# 2.4.2), and the coarser of the cylinder grids it cites (Travin et al. 2000) had Delta_0 = 0.068 D (section 4.2).
DES_FOCUS_CELLS = 32
DES_COARSEST_DELTA = 0.068  # x l_ref
# The averaging this app recommends for a DDES run (D-191): at least this many flow-through times of sampling after
# the start-up (the statistics stop then judges the running mean). A working value, not from a source.
DES_AVERAGING = 50.0


def ddes_mesh_warning(project: Project) -> str | None:
    """Why the mesh of a DDES project is too coarse for DDES where the eddies are, or None (D-191): no enabled
    refinement volume (no focus region), its cell coarser than DES_COARSEST_DELTA l_ref, or fewer than
    DES_FOCUS_CELLS cells across its smallest extent. [NUMERICS-REVIEW]"""
    from vortexcfd.geometry import refinement_volumes

    sim = project.sim
    if not sim.physics.ddes:
        return None
    volumes = [v for v in sim.refinement_volumes if v.enabled]
    if not volumes:
        return ("DDES needs a focus region: a refinement volume around the body and its near wake, meshed with "
                "nearly cubic cells, where the separated turbulence is resolved (Spalart 2001).")
    focus = min(volumes, key=lambda v: v.target_size)
    notes = []
    try:
        _box, _names, bounds = parts_layout(project)
    except (MeshingNotReady, TypeError, ValueError, OSError):
        bounds = None
    if bounds is not None:
        l_ref = reference_values(bounds, sim.reports).l_ref
        if focus.target_size > DES_COARSEST_DELTA * l_ref:
            notes.append(f"its cell ({focus.target_size:.3g} m) is coarser than {DES_COARSEST_DELTA:g} l_ref "
                         f"({DES_COARSEST_DELTA * l_ref:.3g} m), the coarser DDES grid of a cylinder in Spalart 2001")
    b = refinement_volumes.bounds(focus.shape)
    extent = min(b[1] - b[0], b[3] - b[2], b[5] - b[4])
    if extent / focus.target_size < DES_FOCUS_CELLS:
        notes.append(f"it is only {extent / focus.target_size:.0f} cells across (at least {DES_FOCUS_CELLS} are "
                     "needed to resolve eddies in it)")
    if not notes:
        return None
    return f"The mesh may be too coarse for DDES in the focus region '{focus.name}': " + "; ".join(notes) + "."


# DDES ships experimental and not validated in 1.1; URANS is the validated transient turbulence option (D-197). Shown
# inline in Physics whenever DDES is chosen (never a dialog).
DDES_EXPERIMENTAL = ("Experimental, not validated: DDES runs in this version but has not been checked against a "
                     "reference case. For validated transient turbulence results use URANS (k-omega SST).")


def ddes_averaging_text(project: Project) -> str:
    """The recommended averaging of a DDES run (D-191)."""
    return (f"Recommended averaging: at least {DES_AVERAGING:g} flow-through times after the start-up (a long "
            "window: resolved turbulence converges slowly); the statistics stop shows when the running mean "
            "has settled.")


def steady_start_time(case_dir: Path) -> str | None:
    """The latest written time of the case's steady solution (a run record without transient results, D-181), the
    start of a transient run "from the steady solution"; None when there is none. A new mesh deletes the results
    (D-051), so a solution in the case is always on its current mesh."""
    from vortexcfd.foam.run_record import read_run_record

    record = read_run_record(case_dir)
    if record is None or record.transient is not None or record.state == "crashed":
        return None
    return latest_result_time(case_dir)


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
    return boundary_problem(project) or physics_problem(project)


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
    if project.sim.physics.transient:  # second order from the start (D-181)
        return False
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
    bounds = [m.bounds for m in meshes]
    extent = max((b[2 * a + 1] - b[2 * a] for b in bounds for a in range(3)), default=1.0)
    planes = []
    for plane in sim.reports.planes:
        n = plane.normal
        length = sum(c * c for c in n) ** 0.5
        unit = tuple(c / length for c in n)
        point = tuple(p + PLANE_NUDGE * extent * c for p, c in zip(plane.point, unit))
        planes.append((plane.name, point, unit))
    return InternalSetup(tuple(inlets), tuple(outlets), k0, omega0, tuple(planes))


# A cutting plane is written this fraction of the parts' largest extent along its normal from the user's point
# (D-129): a plane that lies on a layer of mesh faces (a round coordinate on a regular background) is sampled with
# the faces of both neighbouring cells (the pipe validation: 368 faces and 105 % of the pipe's area at x = 40 D
# against 336 elsewhere), so the plane never lies on one. [NUMERICS-REVIEW]
PLANE_NUDGE = 1e-6


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
                           two_stage=two_stage_turbulence(project), patch_kinds=face_kinds(project))


# The solvers' logs (D-181) and the transient control file, cleared before a run.
SOLVER_LOGS = tuple(f"log.{name}" for name in SOLVERS)


def clear_results(case_dir: Path) -> list[str]:
    """Remove the previous run's outputs before a run: the results (mesh_case.remove_results: time
    directories after 0, postProcessing/, processor* directories, the run record), plus 0/
    (rewritten), the decomposeParDict of an earlier parallel run and the solver, decomposePar and
    reconstructPar logs. constant/polyMesh is never touched."""
    removed = remove_results(case_dir)
    if (case_dir / "0").is_dir():
        shutil.rmtree(case_dir / "0")
    for name in (*SOLVER_LOGS, "log.decomposePar", "log.reconstructPar", "system/decomposeParDict",
                 TRANSIENT_FILE):
        (case_dir / name).unlink(missing_ok=True)
    return removed


def clear_solution(case_dir: Path) -> list[str]:
    """Clear solution (D-171): the results (mesh_case.remove_results: the written times, postProcessing, the processor
    directories, the run record) and the solver, decomposePar and reconstructPar logs; the mesh, 0/ and the
    dictionaries stay. Returns the removed names."""
    removed = remove_results(case_dir)
    for name in (*SOLVER_LOGS, "log.decomposePar", "log.reconstructPar"):
        if (case_dir / name).is_file():
            (case_dir / name).unlink()
            removed.append(name)
    return removed


def live_view_planes(project: Project, section: LivePlane | None = None) -> tuple[LivePlane, ...]:
    """The planes the live view samples (D-172): the Results Scene's section plane (``section``, the window's) and the
    plane of every clip of the results scene."""
    planes = [section] if section is not None else []
    for obj in project.sim.results.objects:
        if obj.kind == "clip":
            planes.append(LivePlane(safe_name(f"clip_{obj.id}"), tuple(obj.origin), tuple(obj.normal)))
    return tuple(planes)


def app_solver_files(project: Project, case_dir: Path, interactive: bool = False, planes: tuple = ()) -> dict:
    """The solver files of ``project`` (clean stop enabled); ``interactive`` (a run started from the app, D-172): the
    live view (when the project has it on) and "Write fields now" too. The benchmark, the validation drivers and the
    studies write the plain files."""
    inp = for_case(solver_input(project), case_dir)
    if interactive and project.sim.solvers.live_view:
        inp = dataclasses.replace(inp, live_view=LiveViewSpec(tuple(inp.patches), tuple(planes),
                                                              project.sim.solvers.live_view_interval))
    files = enable_clean_stop(build_solver_files(inp))
    return enable_write_now(files) if interactive else files


def prepare_solver_case(project: Project, interactive: bool = False, planes: tuple = ()) -> Path:
    """Write the solver files (clean stop enabled) into the meshed case and return its path. ``interactive``: a run
    started from the app, with the live view and Write fields now (``planes``: the live view's, D-172).

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
    files = app_solver_files(project, case_dir, interactive, planes)
    sim = project.sim
    start = None
    if sim.physics.transient and sim.solvers.transient.start_from == "steady":  # D-181
        latest = steady_start_time(case_dir)
        if latest is None:
            raise SolvingNotReady("There is no steady solution to start the transient run from.")
        start = case_dir / STEADY_START
        shutil.rmtree(start, ignore_errors=True)
        shutil.copytree(case_dir / latest, start)
    clear_results(case_dir)
    for rel, spec in files.items():
        write_spec(case_dir / rel, spec)
    if start is not None:
        start_from_fields(case_dir, start, files)
        shutil.rmtree(start, ignore_errors=True)
    return case_dir


# Where the steady solution's latest fields wait while the case is cleared for a transient run (D-181).
STEADY_START = "steady_start"


def start_from_fields(case_dir: Path, source: Path, files) -> list[str]:
    """The initial fields of a run started from another solution (D-181) [NUMERICS-REVIEW]: each 0/ field the solver
    files write that ``source`` has is that solution's field (its internalField) with the new boundary conditions
    (the solver files' boundaryField), as D-171's continue from a changed set-up; a field the source lacks (k and
    omega after a laminar run) keeps the free-stream start. Returns the fields taken from ``source``."""
    from vortexcfd.foam.case_writer import insert_comment
    from vortexcfd.foam.dictfile import set_foam_entry

    taken = []
    for rel, spec in files.items():
        if not rel.startswith("0/"):
            continue
        name = Path(rel).name
        if not (Path(source) / name).is_file():
            continue
        target = Path(case_dir) / rel
        shutil.copyfile(Path(source) / name, target)
        set_foam_entry(target, "boundaryField", spec.content["boundaryField"])
        if spec.comment:  # a declared start-up perturbation (D-198)
            insert_comment(target, spec.comment)
        taken.append(name)
    return taken


# The Solvers fields of the live view (D-172): not results inputs.
LIVE_FIELDS = ("live_view", "live_view_interval")


# -- continuing a solution (D-171) ---------------------------------------------------------------------------------

# The Physics fields of DDES only (D-191).
DES_FIELDS = ("des_delta", "des_use_sigma", "des_scheme")


# The run states a solution can be continued from: the user stopped it, it reached the iteration limit, or its
# stopping criteria were met (continued with more iterations and, if wanted, tighter criteria; D-176).
CONTINUABLE = ("stopped", "iteration_limit", "criteria_met")
# A transient solution (D-189): stopped, at its end time, or ended by the statistics stop; continued to a later end.
TRANSIENT_CONTINUABLE = ("stopped", "end_time", "criteria_met")
# The transient settings that only say how far a run goes, not what it solves (D-189): a later end time, another
# write interval or statistics stop leave a solution continuable.
TRANSIENT_RUN_LENGTH = ("end_time", "write_interval", "statistics_stop", "stop_quantity", "window", "tolerance",
                        # the sampling settings: a solution whose start-up was not detected can be given its
                        # sampling start by hand, or a looser detection, and continued (D-189)
                        "sampling_start", "detect_tolerance")


def latest_iteration(case_dir: Path) -> tuple[int | None, int | None]:
    """(the latest written time of the case directory, the latest of processor0) as iterations; None: none."""
    case_dir = Path(case_dir)
    found = []
    for folder in (case_dir, case_dir / "processor0"):
        name = latest_result_time(folder) if folder.is_dir() else None
        found.append(int(round(float(name))) if name is not None else None)
    return found[0], found[1]


def processor_count(case_dir: Path) -> int:
    return sum(1 for child in Path(case_dir).glob("processor*") if child.is_dir() and child.name[9:].isdigit())


def latest_times(case_dir: Path) -> tuple[float | None, float | None]:
    """(the latest written time of the case directory, the latest of processor0) in seconds; None: none."""
    case_dir = Path(case_dir)
    found = []
    for folder in (case_dir, case_dir / "processor0"):
        name = latest_result_time(folder) if folder.is_dir() else None
        found.append(float(name) if name is not None else None)
    return found[0], found[1]


def can_continue(case_dir: Path | None, record) -> bool:
    """Whether the solution of ``case_dir`` can be continued: a run that was stopped, reached its limit or met its
    criteria (a transient one: stopped, at its end time or statistically converged, D-189), and a written time to
    start from."""
    if case_dir is None or record is None:
        return False
    if record.transient is not None:
        if record.state not in TRANSIENT_CONTINUABLE:
            return False
        latest, in_processors = latest_times(case_dir)
        return (latest or in_processors or 0.0) > 0.0
    if record.state not in CONTINUABLE:
        return False
    latest, in_processors = latest_iteration(case_dir)
    return (latest or in_processors or 0) > 0


def solution_hash(project: Project) -> str:
    """The results hash without the iteration limit, the write interval and the stopping criteria: what changes the
    solution's path (the mesh, the physics, the free stream or the boundaries, the schemes, the reference values),
    not how long or how far it runs. Continue tells a changed set-up by it (D-171)."""
    sim = project.sim
    payload = json.loads(_results_payload(project))
    payload["solvers"] = sim.solvers.model_dump(exclude={"cores", "iterations", "write_interval", "stopping",
                                                         *LIVE_FIELDS, *_steady_excluded(project)})
    if sim.physics.transient:  # how far a transient run goes is not its set-up (D-189)
        for name in TRANSIENT_RUN_LENGTH:
            payload["solvers"]["transient"].pop(name, None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def settings_changed(project: Project, record) -> bool:
    """Whether the solution's set-up changed since ``record`` was written (older records: any results input)."""
    if record.settings_hash:
        return solution_hash(project) != record.settings_hash
    return results_hash(project) != record.inputs_hash


def replace_boundaries(case_dir: Path, time_name: str, files) -> list[str]:
    """Give the fields of the written time ``time_name`` the boundary conditions of the new solver files (their
    0/ fields' boundaryField), keeping the solution (internalField) [NUMERICS-REVIEW] (D-171). Returns the fields
    changed."""
    from vortexcfd.foam.dictfile import set_foam_entry

    changed = []
    for rel, spec in files.items():
        if not rel.startswith("0/"):
            continue
        target = Path(case_dir) / time_name / Path(rel).name
        if target.is_file() and "boundaryField" in spec.content:
            set_foam_entry(target, "boundaryField", spec.content["boundaryField"])
            changed.append(Path(rel).name)
    return changed


def prepare_continue(project: Project, record, rewrite: bool = False, interactive: bool = False, planes: tuple = ()):
    """Make the case continue its solution from the latest written time (D-171): controlDict starts from latestTime
    and ends at the project's iteration limit (the total), with the project's write interval and criteria. With
    ``rewrite`` (the set-up changed and the user continues from the current solution) every solver file is written
    again and the latest time's fields get the new boundary conditions [NUMERICS-REVIEW]; a two-stage solution in
    its second stage gets the stage-2 schemes again. Returns (case directory, solver_run.ContinueFrom).

    Raises:
        SolvingNotReady: nothing to continue, or the set-up changed and the latest time is only in the processor
        directories.
    """
    from vortexcfd.foam.dictfile import set_foam_entry
    from vortexcfd.foam.logparse import parse_log_text
    from vortexcfd.foam.solver_run import ContinueFrom, apply_stage2, read_stages

    if record is not None and record.transient is not None:
        return prepare_continue_transient(project, record, interactive, planes)
    case_dir = case_dir_for(project)
    if not can_continue(case_dir, record):
        raise SolvingNotReady("There is no stopped solution to continue.")
    reason = physics_problem(project)
    if reason is not None:
        raise SolvingNotReady(reason)
    in_case, in_processors = latest_iteration(case_dir)
    latest = max(v for v in (in_case, in_processors) if v is not None)
    cores = project.sim.solvers.cores
    reuse = (cores > 1 and not rewrite and processor_count(case_dir) == cores and in_processors == latest)
    reconstruct_first = in_case is None or in_case < latest
    if rewrite and reconstruct_first:
        raise SolvingNotReady("The latest time is only in the processor directories (reconstructPar did not run): "
                              "start over, or continue with the unchanged set-up.")
    files = app_solver_files(project, case_dir, interactive, planes)
    two_stage = record.stages and int(record.stages[-1].get("stage", 1)) == 2
    if rewrite:
        for rel, spec in files.items():
            write_spec(case_dir / rel, spec)
        replace_boundaries(case_dir, _time_name(case_dir, latest), files)
        stage2 = read_stages(case_dir)
        if two_stage and stage2 is not None:
            apply_stage2(case_dir, stage2)  # the solution was in stage 2: its schemes again (D-126)
    else:
        spec = files["system/controlDict"]  # the iteration limit, the write interval and the criteria now
        write_spec(case_dir / "system/controlDict", spec)
    set_foam_entry(case_dir / "system" / "controlDict", "startFrom", "latestTime")
    try:
        text = solver_log(case_dir).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    history = tuple(step for step in parse_log_text(text).time_steps if step.time <= latest)
    stage1 = dict(record.stages[0]) if record.stages else None
    resume = ContinueFrom(latest, history, reuse, reconstruct_first and not reuse,
                          2 if two_stage else 1, record.switch_iteration if two_stage else None, stage1)
    return case_dir, resume


def prepare_continue_transient(project: Project, record, interactive: bool = False, planes: tuple = ()):
    """Continue a transient solution to the project's (later) end time without restarting it (D-189), the transient
    counterpart of D-171: controlDict is written again (the end time, the write interval that ends on it, the live
    view) and starts from the latest written time; a sampling that has started keeps its fieldAverage entry and
    start time, so OpenFOAM's fieldAverage goes on from the means written at that time (v2606 fieldAverage reads
    them back on a restart: restartOnRestart is off) and the app's statistics go on over the whole force history
    from the same sampling start. The control file keeps the sampling start, whether it was detected and the end of
    the start-up perturbation; a start-up not yet over is detected as before. Returns (case directory,
    solver_run.ContinueFrom) whose ``iteration`` is the solution's time steps so far.

    Raises:
        SolvingNotReady: nothing to continue, the set-up changed (start over), the end time is not after the
        latest time.
    """
    from vortexcfd.foam import transient as transient_files
    from vortexcfd.foam.logparse import parse_log_text
    from vortexcfd.foam.solver_run import ContinueFrom

    case_dir = case_dir_for(project)
    if not can_continue(case_dir, record):
        raise SolvingNotReady("There is no stopped transient solution to continue.")
    reason = physics_problem(project)
    if reason is not None:
        raise SolvingNotReady(reason)
    if settings_changed(project, record):
        raise SolvingNotReady("The set-up changed since this transient solution was computed: start over.")
    in_case, in_processors = latest_times(case_dir)
    latest = max(v for v in (in_case, in_processors) if v is not None)
    files = app_solver_files(project, case_dir, interactive, planes)
    new = transient_files.TransientControl.from_content(files[transient_files.TRANSIENT_FILE].content)
    if new.end_time <= latest * (1 + 1e-9):
        raise SolvingNotReady(f"Set an end time after the latest time of the solution (t = {latest:.6g} s).")
    old = transient_files.read_control(case_dir) or new
    if old.sampling_start is not None:  # the sampling has started: it goes on from the same start
        control = dataclasses.replace(new, sampling_start=old.sampling_start, detected=old.detected,
                                      not_before=old.not_before, perturbations=old.perturbations)
    else:  # not started: the start set now by hand (the statistics from it; the field averages from the restart
        # at the latest, they cannot go back in time), or the detection goes on with the new tolerance
        control = dataclasses.replace(new, not_before=old.not_before, perturbations=old.perturbations)
    cores = project.sim.solvers.cores
    reuse = (cores > 1 and processor_count(case_dir) == cores and in_processors is not None
             and abs(in_processors - latest) <= 1e-9 * max(1.0, latest))
    reconstruct_first = in_case is None or in_case < latest * (1 - 1e-12)
    spec = files["system/controlDict"]
    content = dict(spec.content)
    content["functions"] = dict(content["functions"])
    if control.sampling_start is not None:  # the averages go on from the same start (or begin at the restart)
        content["functions"][transient_files.FIELD_AVERAGE] = transient_files.field_average(
            max(control.sampling_start, latest) if old.sampling_start is None else control.sampling_start)
    content["startFrom"] = "latestTime"
    interval = transient_times_of(project, case_dir).write_interval  # the write times count from the restart
    content["writeInterval"] = transient_files.even_interval(control.end_time - latest, interval)
    write_spec(case_dir / "system" / "controlDict", dataclasses.replace(spec, content=content))
    transient_files.write_control(case_dir, control)
    try:
        text = solver_log(case_dir).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    history = tuple(step for step in parse_log_text(text).time_steps if step.time <= latest * (1 + 1e-12))
    steps = int((record.transient or {}).get("steps") or len(history))
    return case_dir, ContinueFrom(steps, history, reuse, reconstruct_first and not reuse)


def transient_times_of(project: Project, case_dir: Path):
    """The transient settings of ``project`` in seconds (physics_case.TransientTimes) for its case."""
    from vortexcfd.foam.physics_case import transient_times

    return transient_times(for_case(solver_input(project), case_dir))


def _time_name(case_dir: Path, iteration: int) -> str:
    """The directory name of the written time ``iteration`` ("120")."""
    for child in Path(case_dir).iterdir():
        try:
            if child.is_dir() and abs(float(child.name) - iteration) < 1e-9:
                return child.name
        except ValueError:
            continue
    return str(iteration)


def results_hash(project: Project) -> str:
    """Hash of everything the results depend on: the mesh inputs plus the physics, inflow, solver
    and report settings. Saved results whose hash differs are out of date. The number of cores is
    left out: a parallel run solves the same case (the results agree to solver tolerance, D-063)."""
    return hashlib.sha256(_results_payload(project).encode()).hexdigest()


def _results_payload(project: Project) -> str:
    """The results hash's inputs as JSON text (results_hash, solution_hash)."""
    sim = project.sim
    payload = {
        "mesh": inputs_hash(project),
        # the Mach number's only (D-168); the DDES settings only with DDES, so other projects keep their hash (D-191)
        "physics": sim.physics.model_dump(exclude={"speed_of_sound", *(() if sim.physics.ddes else DES_FIELDS)}),
        "inflow": sim.inflow.model_dump(),
        # the live view: no input (D-172); a steady project's hash has no transient settings (D-181)
        "solvers": sim.solvers.model_dump(exclude={"cores", *LIVE_FIELDS, *_steady_excluded(project)}),
        "reports": sim.reports.model_dump(exclude={"slots"}),  # slot choice does not change results
    }
    if sim.domain.ground.enabled:  # the ground's motion is a solver input only (D-116)
        payload["ground_motion"] = sim.domain.ground.motion
    if two_stage_turbulence(project):  # D-126; single-stage projects keep their hash
        payload["turbulence_stages"] = 2
    if sim.internal:  # the boundaries (D-129); external projects keep their hash
        payload["boundaries"] = [b.model_dump() for b in sim.boundaries]
    if sim.domain.boundary_types:  # the faces' conditions (D-147); a domain left as it was keeps its hash
        payload["boundary_types"] = dict(sorted(sim.domain.boundary_types.items()))
    return json.dumps(payload, sort_keys=True)


def _steady_excluded(project: Project) -> tuple[str, ...]:
    """The Solvers fields a steady project's hashes leave out: its transient settings (D-181), so every steady
    project keeps its hash."""
    return () if project.sim.physics.transient else ("transient",)
