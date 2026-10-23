"""Meshing orchestration: project -> meshing case directory (Qt-free).

Lives in workflow/: it joins core (project), geometry (surfaces, domain) and
foam (case files), and foam/ must not depend on geometry/ (which imports pyvista).
"""

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vortexcfd.core.project import Project
from vortexcfd.core.project_io import V10_MESH_FIELDS, V13_MESH_FIELDS, V14_MESH_FIELDS
from vortexcfd.foam.mesh_estimate import estimate_mesh
from vortexcfd.foam.parallel import MESH_CELLS_PER_CORE, physical_cores, recommended_mesh_cores
from vortexcfd.foam.yplus import (
    LayerPlan,
    first_layer_thickness,
    layer_cap,
    plan_layers,
    plan_wall_resolved,
    wall_resolved_surface_size,
)
from vortexcfd.foam.mesh_case import (
    DOMAIN_SURFACE,
    LOCATION_OFFSET,
    ROBUST_CONTROLS_REVISION,
    SECTION_BUFFER_CELLS,
    TRI_SURFACE,
    WALL_RESOLVED_2D_LAYER_CONTROLS,
    WALL_RESOLVED_CONTROLS_REVISION,
    MeshCaseInput,
    build_mesh_files,
    location_in_mesh,
    needs_seeding,
    part_level_range,
    prepare_case_dir,
    part_patch_names,
    safe_part_names,
    section_buffer_cells,
    wall_patch_names,
    write_domain_guard,
    write_seed_edge_meshes,
)
from vortexcfd.foam.mesh_estimate import BACKGROUND_MARGIN_CELLS, MeshEstimate
from vortexcfd.foam.physics_case import LENGTH_AUTO_LABEL, reference_values
from vortexcfd.geometry import regions, section
from vortexcfd.geometry.attitude import Attitude
from vortexcfd.geometry import internal as internal_geometry
from vortexcfd.geometry.domain import DomainBox, compute_domain, ground_wall_start, internal_box, union_bounds
from vortexcfd.geometry.domain_surface import ROLE_ARRAY, meshing_surface
from vortexcfd.geometry.loader import SurfaceLoadError, load_surface
from vortexcfd.workflow import internal, refinement, surface_prep

CASE_DIR_NAME = "case"


class MeshingNotReady(Exception):
    """The project cannot be meshed yet; the message says why."""


@dataclass(frozen=True)
class MeshJob:
    """A prepared meshing case."""

    case_dir: Path
    inputs: MeshCaseInput
    box: DomainBox
    cores: int = 1  # snappyHexMesh ranks (mesh_cores, D-111)


def case_dir_for(project: Project) -> Path | None:
    return project.path.parent / CASE_DIR_NAME if project.path is not None else None


def _part_files(project: Project) -> list[tuple[str, Path | None, str]]:
    """(name, resolved file or None if missing/unset, units) for every part."""
    out = []
    for part in project.sim.geometry.parts:
        path = None
        if part.source_file and project.path is not None:
            candidate = project.resolve_part_path(part)
            path = candidate if candidate.is_file() else None
        out.append((part.name, path, part.units))
    return out


def _body_parts(project: Project, prepared: bool = True) -> tuple[list[str], list]:
    """(part names, loaded meshes in metres) as imported, never rotated: the surfaces the current surface
    preparation made (D-093), else the parts' own (``prepared`` False: always the parts' own)."""
    prep = surface_prep.current(project) if prepared else None
    names, meshes = [], []
    for part, (name, path, units) in zip(project.sim.geometry.parts, _part_files(project)):
        try:
            if prep is not None:
                meshes.append(surface_prep.prepared_surface(project, part, prep)[0])
            else:
                meshes.append(load_surface(path, units))
        except (OSError, SurfaceLoadError) as exc:
            raise MeshingNotReady(f"Cannot load part '{name}': {exc}") from exc
        names.append(name)
    return names, meshes


def _bounds_of(meshes) -> list[tuple[float, ...]]:
    return [tuple(float(b) for b in m.bounds) for m in meshes]


def attitude_for(project: Project, body_bounds) -> Attitude:
    """The parts' rotation (D-120): the angle of attack about the y axis through the CofR of the Reference
    Values (its override, else the centre of the union of the parts' boxes as imported, ``body_bounds``)."""
    cofr = reference_values(body_bounds, project.sim.reports).cofr if body_bounds is not None else (0.0, 0.0, 0.0)
    return Attitude(project.sim.inflow.alpha_deg, cofr)


def project_attitude(project: Project) -> Attitude:
    """``attitude_for`` with the parts loaded here (the rotation centre (0, 0, 0) when they cannot be)."""
    try:
        _names, meshes = _body_parts(project)
    except MeshingNotReady:
        meshes = []
    return attitude_for(project, union_bounds(_bounds_of(meshes)) if meshes else None)


def body_bounds(project: Project):
    """The union of the parts' bounding boxes as imported (not rotated; None without parts): the basis of
    the automatic reference values (D-047), whatever the angle of attack.

    Raises:
        MeshingNotReady: a part cannot be loaded.
    """
    _names, meshes = _body_parts(project)
    return union_bounds(_bounds_of(meshes)) if meshes else None


def _selected_bounds(bounds, names, domain):
    """The boxes of the parts the domain is sized around (compute_domain's choice)."""
    if domain.parts is not None:
        chosen = [b for b, n in zip(bounds, names) if n in domain.parts]
        if chosen:
            return chosen
    return bounds


def _loaded_parts(project: Project, prepared: bool = True, rotated: bool = True):
    """(domain box, part names, loaded meshes in metres) for the project's parts: the surfaces the
    current surface preparation made (D-093), else the parts' own (``prepared`` False: always the
    parts' own). With an angle of attack (``rotated``) the meshes are rotated copies (D-120) and the domain
    is sized around them; a ground plane at the parts' lowest z stays where the parts as imported put it,
    so a rotated part may cross it (``readiness`` refuses that). [NUMERICS-REVIEW]"""
    names, meshes = _body_parts(project, prepared)
    if project.sim.internal:  # no domain and no rotation: the fluid is the inside of the parts (D-129)
        box = internal_box(_bounds_of(meshes), fluid_volume(meshes) if meshes else 0.0)
        if project.sim.dimension == "2d":
            box = dataclasses.replace(box, two_d=True)
        return box, names, meshes
    domain = project.sim.domain
    if rotated and meshes and project.sim.inflow.alpha_deg != 0.0:
        body = _bounds_of(meshes)
        att = attitude_for(project, union_bounds(body))
        if domain.ground.enabled and domain.ground.position == "parts_min":
            z = union_bounds(_selected_bounds(body, names, domain))[4]
            domain = domain.model_copy(update={"ground": domain.ground.model_copy(update={"position": "value", "z": z})})
        meshes = [att.surface(m) for m in meshes]
    box = compute_domain(_bounds_of(meshes), domain, names)
    if project.sim.dimension == "2d":
        box = dataclasses.replace(box, two_d=True)
    return box, names, meshes


_fluid_volumes: dict[tuple, float] = {}


def fluid_volume(meshes) -> float:
    """The volume inside the parts' closed surfaces (internal flow, D-129), cached per set of loaded surfaces (the
    loader caches them by file, so the same objects come back while the files do not change)."""
    key = tuple((id(m), m.n_points, m.n_cells) for m in meshes)
    if key not in _fluid_volumes:
        if len(_fluid_volumes) > 32:
            _fluid_volumes.clear()
        _fluid_volumes[key] = internal_geometry.enclosed_volume(meshes)
    return _fluid_volumes[key]


def loaded_parts(project: Project):
    """(domain box, part names, meshes in metres) as meshing uses them (the surface preparation's
    surfaces when one is current; rotated by the angle of attack, D-120).

    Raises:
        MeshingNotReady: a part cannot be loaded.
    """
    return _loaded_parts(project)


def loaded_original_parts(project: Project):
    """(domain box, part names, meshes in metres) of the parts' own surfaces as imported (no preparation,
    no rotation: the surface preparation works on the parts as imported)."""
    return _loaded_parts(project, prepared=False, rotated=False)


def parts_layout(project: Project) -> tuple[DomainBox, tuple[str, ...], tuple[float, ...]]:
    """(domain box, every part wall patch name, union of the parts' bounding boxes in metres as imported,
    not rotated by the angle of attack: the reference values' basis, D-120).

    Raises:
        MeshingNotReady: a part cannot be loaded.
    """
    box, _names, _meshes = _loaded_parts(project)
    return box, wall_patch_names(project.sim.geometry.parts, project.sim.internal), body_bounds(project)


def write_part_surfaces(case_dir: Path, project: Project, inputs: MeshCaseInput, meshes) -> None:
    """The part STLs of a meshing case (metres): a part with several patches (or one renamed patch)
    gets one solid per patch, named after it (D-071); other parts are written as loaded. In 2D (D-121) a part
    is its section (cut at its mid y) extruded across the slab and one slab span beyond it on each side, so
    snappyHexMesh cuts it at the slab's faces. The imported refinement regions' surfaces are written too (D-145)."""
    refinement.write_region_surfaces(case_dir, TRI_SURFACE, project, inputs.volumes, project_attitude(project))
    if inputs.two_d:
        est = inputs.estimate()
        y0, y1 = est.background_bounds[2], est.background_bounds[3]
        for i, (name, mesh) in enumerate(zip(inputs.parts, meshes)):
            loops = section.section_loops(mesh)
            if inputs.internal and inputs.has_regions(i):  # each segment keeps its patch (D-129)
                y = (mesh.bounds[2] + mesh.bounds[3]) / 2
                labels = internal_geometry.labelled_section(mesh, part_patch_labels(project, i, mesh), loops, y)
                patches = list(inputs.patches_of(i))
                walls = [k for k, p in enumerate(patches) if inputs.patch_type(p) == "wall"]
                surface, cell_labels = internal_geometry.labelled_slab(loops, labels, y0 - (y1 - y0), y1 + (y1 - y0),
                                                                       walls[0] if walls else 0)
                regions.write_patch_stl(case_dir / TRI_SURFACE / f"{name}.stl", surface, cell_labels, patches)
                continue
            slab_surface = section.slab(loops, y0 - (y1 - y0), y1 + (y1 - y0))
            slab_surface.save(str(case_dir / TRI_SURFACE / f"{name}.stl"))
        return
    for i, (name, mesh) in enumerate(zip(inputs.parts, meshes)):
        path = case_dir / TRI_SURFACE / f"{name}.stl"
        if not inputs.has_regions(i):
            mesh.save(str(path))  # already scaled to metres
            continue
        regions.write_patch_stl(path, mesh, part_patch_labels(project, i, mesh), list(inputs.patches_of(i)))


def part_patch_labels(project: Project, index: int, mesh) -> np.ndarray:
    """Per triangle of the loaded (or prepared) surface ``mesh`` of part ``index``: its patch, an index
    into MeshCaseInput.patches_of(index) (all 0 for a part without regions)."""
    part = project.sim.geometry.parts[index]
    if not part.regions:  # one patch, the part itself
        return np.zeros(mesh.n_cells, dtype=int)
    try:
        ids = surface_prep.base_ids(project, part, mesh, surface_prep.current(project))
    except regions.RegionError as exc:
        raise MeshingNotReady(f"Part '{part.name}': {exc}") from exc
    return regions.patch_labels(part, ids, part.patch_names())


def estimate_for(box: DomainBox, mesh, surface_length: float | None = None) -> MeshEstimate:
    """The mesh estimate of ``box`` (its actual volume; the background box of a rounded shape; a 2D slab,
    D-121) with the surface size from ``surface_length`` (None: the domain's L; see ``surface_length``)."""
    length = box.reference_length if surface_length is None else surface_length
    return estimate_mesh(box.bounds, length, mesh, volume=box.volume, rounded=box.rounded,
                         symmetric=box.symmetric, two_d=box.two_d, internal=box.internal)


@dataclass(frozen=True)
class SurfaceLength:
    """The length the target surface size multiplies (D-085): ``source`` is "l_ref" (set in the
    Reference Values), "l_ref_auto" (l_ref never set: its automatic value) or "largest_extent" (L,
    projects made before schema v10)."""

    value: float
    source: str

    def describe(self) -> str:
        if self.source == "dh_auto":
            return f"D_h = {self.value:.4g} m (hydraulic diameter of the first inlet)"
        if self.source == "largest_extent":
            return f"L = {self.value:.4g} m (largest extent of the parts)"
        return f"l_ref = {self.value:.4g} m" + (f" ({LENGTH_AUTO_LABEL})" if self.source == "l_ref_auto" else "")


SURFACE_LENGTH_AUTO_WARNING = ("l_ref is not set: the surface cell size and the y+ first layer use its automatic "
                               "value ({auto}). Set the reference length under Reports & Monitors > "
                               "Reference Values.")


def surface_length(project: Project, box: DomainBox, parts_bounds=None) -> SurfaceLength:
    """The surface size length of ``project`` (``parts_bounds``: the union of every part's box as imported,
    as the solver's reference values use (``body_bounds``); None: loaded here). Never raises. Internal flow
    (D-129): l_ref when it is set, else the hydraulic diameter of the first inlet ("dh_auto"; the largest extent
    without an inlet). [NUMERICS-REVIEW]"""
    if project.sim.internal and project.sim.mesh.surface_size_reference == "l_ref":
        if project.sim.reports.reference_length is not None:
            return SurfaceLength(project.sim.reports.reference_length, "l_ref")
        inlet = _reference_inlet(project)
        if inlet is not None and inlet.hydraulic_diameter > 0:
            return SurfaceLength(inlet.hydraulic_diameter, "dh_auto")
        return SurfaceLength(box.reference_length, "largest_extent")
    if project.sim.mesh.surface_size_reference == "largest_extent":
        return SurfaceLength(box.reference_length, "largest_extent")
    if parts_bounds is None:
        try:
            parts_bounds = body_bounds(project)
        except MeshingNotReady:  # a part cannot be loaded (readiness says so): the parts the box knows
            parts_bounds = box.parts_bounds
    if parts_bounds is None:
        return SurfaceLength(box.reference_length, "largest_extent")
    ref = reference_values(parts_bounds, project.sim.reports)
    if ref.l_ref <= 0:  # a part with no x extent: l_ref is unusable (Run Solver says so, D-047)
        return SurfaceLength(box.reference_length, "largest_extent")
    return SurfaceLength(ref.l_ref, "l_ref_auto" if ref.l_auto else "l_ref")


def surface_length_warning(length: SurfaceLength) -> str | None:
    """The Mesh properties warning when the surface size (and the y+ Reynolds number, D-088) follow an
    l_ref that was never set."""
    if length.source != "l_ref_auto":
        return None
    return SURFACE_LENGTH_AUTO_WARNING.format(auto=LENGTH_AUTO_LABEL)


def project_estimate(project: Project, box: DomainBox, mesh=None, parts_bounds=None) -> MeshEstimate:
    """The mesh estimate of ``project`` in ``box`` with its surface length (``mesh``: other settings,
    e.g. a mesh study level; None: ``meshing_settings``)."""
    length = surface_length(project, box, parts_bounds).value
    return estimate_for(box, mesh or meshing_settings(project, box, length), length)


def _reference_inlet(project: Project):
    """The internal-flow reference inlet (workflow/internal.reference_inlet), None when the parts cannot be loaded or
    there is no inlet."""
    try:
        _names, meshes = _body_parts(project)
        return internal.reference_inlet(project, meshes) if meshes else None
    except (MeshingNotReady, ValueError):
        return None


def flow_speed(project: Project) -> float:
    """The speed of the y+ estimate: the free stream; in internal flow the reference inlet's bulk speed (the inflow
    speed when it cannot be estimated, D-129). [NUMERICS-REVIEW]"""
    if project.sim.internal:
        inlet = _reference_inlet(project)
        if inlet is not None and inlet.speed:
            return inlet.speed
    return project.sim.inflow.speed


def yplus_first_layer(project: Project, length: float) -> float:
    """The first layer of absolute (y+) sizing: the estimator with Re on the surface size length (D-088), the
    target at the first cell centre by default (D-107); internal flow: the reference inlet's bulk speed and, by
    default, its hydraulic diameter (D-129). [NUMERICS-REVIEW]"""
    mesh = project.sim.mesh
    return first_layer_thickness(mesh.target_yplus, flow_speed(project), project.sim.physics.nu, length,
                                 mesh.yplus_at)


def meshing_settings(project: Project, box: DomainBox, length: float | None = None):
    """The Mesh settings meshing uses: the project's, except that the wall-resolved layer controls (D-122) raise
    the surface levels until the surface cell is at most WR_MAX_CELL_TO_FIRST first layers (an explicit maximum
    level that is already fine enough is kept; a coarser one is raised). A target y+ below 5 with the robust controls
    selects the wall-resolved ones (D-123): the copy returned carries "wall_resolved". [NUMERICS-REVIEW]"""
    mesh = project.sim.mesh
    if mesh.wall_resolved_auto:
        mesh = mesh.model_copy(update={"layer_controls": "wall_resolved"})
    if mesh.layer_controls != "wall_resolved" or mesh.layer_sizing != "absolute_yplus" or box.bounds is None:
        return mesh
    length = surface_length(project, box).value if length is None else length
    est = estimate_for(box, mesh, length)
    limit = wall_resolved_surface_size(yplus_first_layer(project, length))
    if est.surface_size <= limit * (1 + 1e-9):
        return mesh
    level = max(0, math.ceil(math.log2(est.base_size / limit) - 1e-9))
    low = mesh.surface_level_min if mesh.surface_level_min is not None else level - 1
    return mesh.model_copy(update={"surface_level_max": level, "surface_level_min": max(0, min(low, level))})


def domain_fields(box: DomainBox) -> dict:
    """The MeshCaseInput fields of the domain shape (D-078). A rounded shape's surface carries every
    role but the symmetry plane, which is the background box's y_min face."""
    if not box.rounded:
        return {}
    return {"domain_shape": box.shape, "domain_volume": box.volume, "inlet_x": box.inlet_x,
            "domain_patches": tuple(r for r in box.roles if r != "symmetry")}


def write_domain_surface(case_dir: Path, box: DomainBox, inputs: MeshCaseInput) -> None:
    """constant/triSurface/domain.stl of a rounded domain: one solid per patch, the open edge on a
    symmetry plane extended through it by the background margin (geometry/domain_surface.py)."""
    if not inputs.rounded:
        return
    est = inputs.estimate()
    surface = meshing_surface(box, BACKGROUND_MARGIN_CELLS * est.base_size)
    names = list(inputs.domain_patches)
    role_index = {i: names.index(r) for i, r in enumerate(box.roles) if r in names}
    labels = np.array([role_index[int(r)] for r in surface.cell_data[ROLE_ARRAY]], dtype=int)
    regions.write_patch_stl(case_dir / TRI_SURFACE / f"{DOMAIN_SURFACE}.stl", surface, labels, names)


def fluid_location(project: Project) -> tuple[float, float, float] | None:
    """The locationInMesh of the project's mesh (the fluid side kept by snappyHexMesh), or None when
    the parts cannot be loaded or there are none."""
    try:
        box, _names, meshes = _loaded_parts(project)
    except MeshingNotReady:
        return None
    if box.bounds is None:
        return None
    est = project_estimate(project, box)
    if box.internal:  # inside the closed geometry (D-129)
        return internal_geometry.inside_point(meshes, est.background_bounds, est.cells, LOCATION_OFFSET)
    parts = union_bounds([tuple(float(b) for b in m.bounds) for m in meshes])
    return location_in_mesh(est.background_bounds, parts, est.cells, box.inlet_x if box.rounded else None)


def plan_layers_for(project: Project, box: DomainBox) -> LayerPlan:
    """The y+ layer stack for ``project``: first layer from the estimator with Re on the surface size
    length (l_ref, or L for projects made before schema v10; D-088), count from the surface cell size
    at the maximum refinement level (see foam/yplus.plan_layers). [NUMERICS-REVIEW]"""
    mesh = project.sim.mesh
    length = surface_length(project, box)
    first = yplus_first_layer(project, length.value)  # at the first cell centre by default (D-107)
    est = estimate_for(box, meshing_settings(project, box, length.value), length.value)
    if mesh.effective_layer_controls == "wall_resolved":  # one surface cell thick at ratio 1.2 (D-122, D-123)
        return plan_wall_resolved(first, est.surface_size)
    return plan_layers(first, mesh.expansion_ratio, est.surface_size, **layer_cap(mesh.layer_controls))



def layer_warning(project: Project) -> str | None:
    """Warning about the y+ layer stack (None for relative sizing, or when it is fine or unknown)."""
    if project.sim.mesh.layer_sizing != "absolute_yplus":
        return None
    try:
        box, _, _ = _loaded_parts(project)
    except MeshingNotReady:
        return None
    if box.bounds is None:
        return None
    plan = plan_layers_for(project, box)
    lines = [w for w in (plan.warning, plan.thickness_warning) if w]  # the capped stack too (D-106)
    return " ".join(lines) or None


def readiness(project: Project) -> str | None:
    """Why the project cannot be meshed, or None when it can."""
    if project.path is None:
        return "Save the project first: the mesh case is created next to the project file."
    files = _part_files(project)
    if not any(path is not None for _, path, _ in files):
        return "Import at least one part."
    missing = [name for name, path, _ in files if path is None]
    if missing:
        return f"The file of part '{missing[0]}' is missing."
    if surface_prep.state(project) == "stale":
        return surface_prep.STALE_MESSAGE
    regions_problem = refinement.region_problems(project)  # imported refinement regions (D-145)
    if regions_problem:
        return regions_problem[0]
    if project.sim.internal:
        return internal_readiness(project)
    if not project.sim.domain.enabled:
        if project.sim.analysis_type == "empty":
            return "Generate the domain first (Regions > Domain)."
        return "Enable the fluid domain."
    try:
        box, names, meshes = _loaded_parts(project)
    except MeshingNotReady as exc:
        return str(exc)
    if box.ground and box.parts_bounds is not None and box.bounds[4] >= box.parts_bounds[5]:
        return "The ground plane is above every part: lower it (Fluid Domain > Ground plane)."
    problem = attitude_problem(project, box, names, meshes) or section_problem(project, names, meshes)
    if problem is not None:
        return problem
    start = ground_wall_start(project.sim.domain, box.bounds)
    if start is not None and start >= box.bounds[1]:
        return (f"The ground wall starts at x = {start:.4g} m, at or behind the outlet (x = {box.bounds[1]:.4g} m): "
                "move it upstream (Fluid Domain > Ground plane).")
    return estimate_with_volumes(project, box).limit_message()


def internal_section_problem(project: Project, names, meshes) -> str | None:
    """A 2D internal-flow patch the section does not cut (D-129), or None: the section at mid y carries a patch per
    segment, so a patch with no segment (e.g. the slab's end caps on a patch of their own) would be a patch with no
    face, which snappyHexMesh refuses."""
    if project.sim.dimension != "2d":
        return None
    for i, (part, name, mesh) in enumerate(zip(project.sim.geometry.parts, names, meshes)):
        patches = part.patch_names()
        if len(patches) < 2:
            continue
        y = (mesh.bounds[2] + mesh.bounds[3]) / 2
        cut = internal_geometry.labelled_section(mesh, part_patch_labels(project, i, mesh), section.section_loops(mesh), y)
        missing = [p for k, p in enumerate(patches) if not any((seg == k).any() for seg in cut)]
        if missing:
            return (f"Part '{name}': patch '{missing[0]}' is not on the 2D section (the cut at mid y): assign its "
                    "regions to another patch.")
    return None


def internal_readiness(project: Project) -> str | None:
    """Why an internal-flow project cannot be meshed (D-129), or None: the roles (an inlet and an outlet), the closed
    geometry, a 2D section of every part, an inlet that sizes the mesh and the background cell limit."""
    problem = internal.role_problem(project)
    if problem is not None:
        return problem
    try:
        box, names, meshes = _loaded_parts(project)
    except MeshingNotReady as exc:
        return str(exc)
    problem = (internal_geometry.closure_problem(meshes) or section_problem(project, names, meshes)
               or internal_section_problem(project, names, meshes))
    if problem is not None:
        return problem
    inlet = internal.reference_inlet(project, meshes)
    if inlet is None or inlet.hydraulic_diameter <= 0:
        return "The first inlet has no area: check its patch."
    if inlet.speed is None and project.sim.mesh.layer_sizing == "absolute_yplus":
        return (f"The y+ layers need a speed at inlet {inlet.patch}: its total pressure must be above the outlet "
                "pressure.")
    return estimate_with_volumes(project, box).limit_message()


# A rotated part may touch the ground plane within this fraction of L (rounding of the rotation).
GROUND_TOUCH_TOLERANCE = 1e-9


def attitude_problem(project: Project, box: DomainBox, names, meshes) -> str | None:
    """Why the rotated parts cannot be meshed (D-120, owner decision A2), or None: a part that leaves the
    domain or crosses the ground plane at the angle of attack. At 0 degrees nothing is checked here (a
    support crossing the ground is allowed, D-116; a part outside a rounded domain is a domain warning)."""
    alpha = project.sim.inflow.alpha_deg
    if alpha == 0.0 or box.bounds is None:
        return None
    from vortexcfd.geometry.refinement_volumes import inside_domain

    for name, mesh in zip(names, meshes):
        points = np.asarray(mesh.points)
        if box.ground and points[:, 2].min() < box.bounds[4] - GROUND_TOUCH_TOLERANCE * max(box.reference_length, 1.0):
            return (f"Part '{name}' crosses the ground plane when rotated to the angle of attack ({alpha:g} deg): "
                    "lower the ground plane or change the angle.")
        if not inside_domain(box, points).all():
            return (f"Part '{name}' leaves the domain when rotated to the angle of attack ({alpha:g} deg): enlarge "
                    "the domain or size it around every part.")
    return None


def section_problem(project: Project, names, meshes) -> str | None:
    """Why the parts cannot be meshed as a 2D section (D-121), or None (3D: never): a part split into several
    patches, or one whose cut at its mid y gives no closed section curve."""
    if project.sim.dimension != "2d":
        return None
    for part, name, mesh in zip(project.sim.geometry.parts, names, meshes):
        if len(part.patch_names()) > 1 and not project.sim.internal:  # internal: one patch per segment (D-129)
            return f"Part '{name}' has several patches: a 2D section takes one patch per part."
        try:
            section.section_loops(mesh)
        except ValueError as exc:
            return f"Part '{name}' has no 2D section: {exc}."
    return None


def estimate_with_volumes(project: Project, box: DomainBox, parts_bounds=None) -> MeshEstimate:
    """The project's mesh estimate with its refinement volumes' extra cells (D-103)."""
    est = project_estimate(project, box, parts_bounds=parts_bounds)
    return refinement.with_volumes(est, refinement.volume_infos(project, box, est, project_attitude(project)))


@dataclass(frozen=True)
class MeshCores:
    """The meshing cores of a project (D-111)."""

    used: int
    recommended: int  # foam/parallel.recommended_mesh_cores of ``cells``
    cells: int  # estimated background cells, refinement volumes included
    automatic: bool  # Mesh.cores unset: the Solvers cores capped by the recommendation

    def describe(self) -> str:
        how = "automatic" if self.automatic else "set"
        return (f"{self.used} ({how}; recommended {self.recommended} for {self.cells:,} background cells, "
                f"{MESH_CELLS_PER_CORE:,} per core)")


def mesh_cores(project: Project, box: DomainBox, physical: int | None = None) -> MeshCores:
    """The snappyHexMesh ranks of ``project`` (D-111): Mesh.cores when set, else the meshing recommendation
    from the estimated background cells, min(physical, cells / 12,500, 8); never more than the physical
    cores, at least 1. The Solvers cores do not enter: their cap (D-064) measured the solver's efficiency,
    and meshing scales better (owner review of D-111). [NUMERICS-REVIEW]"""
    physical = physical or physical_cores()
    cells = estimate_with_volumes(project, box).budget_cells
    recommended = recommended_mesh_cores(cells, physical)
    chosen = project.sim.mesh.cores
    used = recommended if chosen is None else chosen
    return MeshCores(max(1, min(used, physical)), recommended, cells, chosen is None)


def mesh_inputs(project: Project) -> tuple[MeshCaseInput, DomainBox, list]:
    """(the meshing case input, the domain box, the parts' loaded surfaces in metres) of ``project``:
    everything the meshing dictionaries depend on.

    Raises:
        MeshingNotReady: see ``readiness``, or a part cannot be loaded.
    """
    reason = readiness(project)
    if reason is not None:
        raise MeshingNotReady(reason)
    box, names, meshes = _loaded_parts(project)
    bounds = [tuple(float(b) for b in m.bounds) for m in meshes]
    body = body_bounds(project)
    length = surface_length(project, box, body)
    safe = safe_part_names(names, project.sim.internal)
    first_layer = layer_count = expansion = None
    if project.sim.mesh.layer_sizing == "absolute_yplus":
        plan = plan_layers_for(project, box)
        first_layer, layer_count, expansion = plan.first, plan.count, plan.expansion
    inputs = MeshCaseInput(
        domain_bounds=box.bounds,
        symmetric=project.sim.domain.symmetry == "y_min",
        parts=tuple(safe),
        parts_bounds=union_bounds(bounds),
        reference_length=box.reference_length,
        mesh=meshing_settings(project, box, length.value),
        first_layer_thickness=first_layer,
        layer_count=layer_count,
        layer_expansion=expansion,
        part_bounds=tuple(bounds),
        part_levels=_part_overrides(project),
        part_patches=tuple(part_patch_names(project.sim.geometry.parts, project.sim.internal)),
        surface_length=length.value,
        extra_features=_junction_features(project, box, length.value),
        volumes=_volume_entries(project, box, body),
        ground=box.ground,
        ground_layers=box.ground and project.sim.domain.ground.layers,
        ground_wall_start=ground_wall_start(project.sim.domain, box.bounds),
        two_d=box.two_d,
        **domain_fields(box),
        **internal_fields(project, box),
    )
    if box.internal:
        try:
            inputs = internal.with_location(inputs, meshes)
        except ValueError as exc:
            raise MeshingNotReady(str(exc)) from exc
    return inputs, box, meshes


def internal_fields(project: Project, box: DomainBox) -> dict:
    """The MeshCaseInput fields of internal flow (D-129): the fluid volume as the domain volume, the inlets and
    outlets; none for other analyses (their dictionaries are unchanged)."""
    if not box.internal:
        return {}
    return {"internal": True, "domain_volume": box.volume, "open_patches": internal.open_patches(project)}


def _volume_entries(project: Project, box: DomainBox, parts_bounds) -> tuple:
    """The refinement volumes meshing writes (enabled, not wholly outside the domain; D-103), the
    body-frame ones turned with the parts (D-120). ``parts_bounds``: ``body_bounds``."""
    if not project.sim.refinement_volumes:
        return ()
    est = project_estimate(project, box, parts_bounds=parts_bounds)
    att = attitude_for(project, parts_bounds)
    return refinement.volume_entries(refinement.volume_infos(project, box, est, att))


def prepare_job(project: Project) -> MeshJob:
    """Write the meshing case for ``project`` into <project dir>/case and return the job.

    Raises:
        MeshingNotReady: see ``readiness``, or a part cannot be loaded.
        CaseDirectoryNotOursError: <project dir>/case exists and was not generated by VortexCFD.
    """
    inputs, box, meshes = mesh_inputs(project)
    case_dir = case_dir_for(project)
    prepare_case_dir(case_dir, build_mesh_files(inputs))
    write_junction_features(case_dir, project, inputs)
    write_part_surfaces(case_dir, project, inputs, meshes)
    write_domain_surface(case_dir, box, inputs)
    write_domain_guard(case_dir, inputs)
    write_seed_edge_meshes(case_dir, inputs)
    return MeshJob(case_dir, inputs, box, mesh_cores(project, box).used)


def junction_level(project: Project, box: DomainBox, length: float) -> int:
    """The refinement level of the intersection curves (D-093, corrected in D-097): the finest level
    the parts' surfaces can reach, their highest maximum surface level (overrides, else the mesh's)
    plus the curvature refinement levels (D-085). The parts' maximum surface level alone is often below
    what curvature refinement already gives the cells at a junction, and then the curves refine
    nothing (the 5.2 aircraft: level 5 against cells at level 7). [NUMERICS-REVIEW]"""
    est = estimate_for(box, meshing_settings(project, box, length), length)
    top = max(part_level_range(est.level_min, est.level_max, o)[1] for o in _part_overrides(project))
    return top + project.sim.mesh.curvature_levels


def _junction_features(project: Project, box: DomainBox, length: float) -> tuple[tuple[str, int], ...]:
    prep = surface_prep.current(project)
    if prep is None or prep.features_file is None or not project.sim.geometry.parts:
        return ()
    return ((surface_prep.JUNCTION_FILE, junction_level(project, box, length)),)


def write_junction_features(case_dir: Path, project: Project, inputs: MeshCaseInput) -> None:
    """Copy the surface preparation's intersection curves into constant/triSurface (D-093), turned with the
    parts at an angle of attack (D-120); an earlier copy is removed when the case has none."""
    target = case_dir / TRI_SURFACE / surface_prep.JUNCTION_FILE
    prep = surface_prep.current(project)
    if not inputs.extra_features or prep is None or prep.features_file is None:
        target.unlink(missing_ok=True)
        return
    source = project.folder / prep.features_file
    att = project_attitude(project)
    if not att.rotated:
        target.write_bytes(source.read_bytes())
        return
    target.write_text(att.edge_mesh_text(source.read_text(encoding="utf-8"), target.name), encoding="utf-8")


def _part_overrides(project: Project) -> tuple[tuple[int | None, int | None], ...]:
    return tuple((p.surface_level_min, p.surface_level_max) for p in project.sim.geometry.parts)


SEEDED_TEXT = "is small relative to the background mesh: refinement seeded automatically"


def thin_part_warnings(project: Project) -> list[str]:
    """Pre-mesh notes, one per part flagged by mesh_case.needs_seeding (small relative to the
    background cells, or thinner than THIN_SURFACE_CELLS surface cells at its maximum level). Such
    parts are seeded automatically (D-052); the lost-part guard still checks the result.
    Empty when the parts cannot be loaded (readiness says why)."""
    try:
        box, names, meshes = _loaded_parts(project)
    except MeshingNotReady:
        return []
    if box.bounds is None:
        return []
    bounds = union_bounds([tuple(float(b) for b in m.bounds) for m in meshes])
    est = project_estimate(project, box, parts_bounds=bounds)
    out = []
    for part, name, surf in zip(project.sim.geometry.parts, names, meshes):
        bounds = tuple(float(b) for b in surf.bounds)
        override = (part.surface_level_min, part.surface_level_max)
        _lo, hi = part_level_range(est.level_min, est.level_max, override)
        if needs_seeding(bounds, est.base_size, hi):
            out.append(f"Part {name} {SEEDED_TEXT}")
    return out


_file_hashes: dict[tuple[str, int, int], str] = {}


def _hash_file(path: Path) -> str:
    """SHA-256 of a file's contents, cached by (path, mtime, size)."""
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    digest = _file_hashes.get(key)
    if digest is None:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        digest = _file_hashes[key] = h.hexdigest()
    return digest


def _domain_for_hash(domain) -> dict:
    """The domain as the mesh hash sees it: without the ground plane when it is off (projects saved before
    schema v16 keep their hash) and without the ground's motion, which only the solver reads (D-116)."""
    data = domain.model_dump()
    ground = data.pop("ground")
    if ground["enabled"]:
        ground.pop("motion")
        if ground.get("wall_start_x") is None:  # no slip strip: the hash of schema v16 (D-118)
            ground.pop("wall_start_x", None)
        data["ground"] = ground
    return data


def inputs_hash(project: Project) -> str:
    """Hash of everything a mesh depends on: part names, file contents and units, the domain
    and the mesh settings. A saved mesh whose hash differs from this one is out of date."""
    parts = []
    for part in project.sim.geometry.parts:
        path = project.resolve_part_path(part) if part.source_file and project.path else None
        digest = _hash_file(path) if path is not None and path.is_file() else None
        entry = [part.name, part.units, digest, part.surface_level_min, part.surface_level_max]
        if part.regions or part.region_ids:  # regions change the patches (D-071); old hashes stay valid
            ids = project.path.parent / part.region_ids if part.region_ids and project.path else None
            entry.append([[r.name, r.members, r.patch] for r in part.regions])
            entry.append(_hash_file(ids) if ids is not None and ids.is_file() else None)
        parts.append(entry)
    mesh = project.sim.mesh.model_dump()
    mesh.pop("cores", None)  # a parallel run meshes the same inputs (D-111)
    for key, legacy in {**V10_MESH_FIELDS, **V13_MESH_FIELDS, **V14_MESH_FIELDS}.items():  # a project meshed
        # before v10 / v13 / v14 keeps its hash (D-085, D-106, D-107)
        if mesh.get(key) == legacy:
            del mesh[key]
    payload = {
        "parts": parts,
        "domain": _domain_for_hash(project.sim.domain),
        "mesh": mesh,
        # Absolute (y+) layer sizes depend on the flow; relative sizes do not.
        "yplus_inputs": (
            [project.sim.inflow.speed, project.sim.physics.nu]
            if project.sim.mesh.layer_sizing == "absolute_yplus" else None
        ),
    }
    mesh_settings = project.sim.mesh
    if mesh_settings.wall_resolved_auto:  # the robust controls gave way to the wall-resolved ones (D-123)
        payload["wall_resolved_auto"] = True
    elif mesh_settings.layer_controls == "robust" and mesh_settings.layer_sizing == "absolute_yplus":
        # the robust controls changed in 5.4b (D-106): a mesh made with the earlier ones is out of date
        payload["robust_controls"] = ROBUST_CONTROLS_REVISION
    if mesh_settings.effective_layer_controls == "wall_resolved":  # the layer phase's relaxed set changed (D-135)
        payload["wall_resolved_controls"] = WALL_RESOLVED_CONTROLS_REVISION
    if project.sim.internal:  # the roles set the patch types and the layered walls (D-129); others keep their hash
        payload["internal"] = [[p.safe, p.role] for p in internal.patches(project)]
        payload["internal_l_ref"] = project.sim.reports.reference_length
        if project.sim.mesh.layer_sizing == "absolute_yplus":  # the y+ speed is the reference inlet's
            payload["internal_yplus_speed"] = flow_speed(project)
    if project.sim.dimension == "2d":  # D-121; 3D projects keep their hash
        payload["dimension"] = "2d"
        buffer = section_buffer_cells(mesh_settings)
        if buffer != SECTION_BUFFER_CELLS:  # wall-resolved: the staircase buffer (D-124) and the medial-axis walk
            payload["section_buffer_cells"] = buffer  # (D-125); other projects keep their hash
            payload["wall_resolved_2d_layers"] = WALL_RESOLVED_2D_LAYER_CONTROLS
    alpha = project.sim.inflow.alpha_deg
    if alpha != 0.0:  # the parts are rotated (D-120); at 0 the hash of the projects saved before v18
        payload["alpha_deg"] = alpha
        payload["rotation_centre"] = project.sim.reports.center_of_rotation  # None: the parts' box centre
    enabled = [v for v in project.sim.refinement_volumes if v.enabled]
    if enabled:  # only enabled volumes reach the mesh (D-103); none: the hash of a project without volumes
        skip = {"enabled"} if alpha != 0.0 else {"enabled", "frame"}  # the frame matters only when rotated
        payload["refinement_volumes"] = [v.model_dump(mode="json", exclude=skip) for v in enabled]
        folder = project.path.parent if project.path else None
        for entry, v in zip(payload["refinement_volumes"], enabled):  # an imported region's surface (D-145)
            if v.shape.kind == "surface":
                path = folder / v.shape.file if folder is not None else None
                entry["surface_hash"] = _hash_file(path) if path is not None and path.is_file() else None
    if project.sim.mesh.surface_size_reference == "l_ref":  # l_ref sizes the surface (D-085)
        payload["surface_l_ref"] = project.sim.reports.reference_length
    prep = project.sim.surface_prep
    if prep is not None:  # the prepared surfaces and curves are meshing inputs (D-093)
        folder = project.path.parent if project.path else None
        files = [f for p in prep.parts for f in (p.surface_file, p.region_ids)] + [prep.features_file]
        payload["surface_prep"] = [prep.strategy, prep.inputs_hash] + [
            _hash_file(folder / f) if folder is not None and f and (folder / f).is_file() else None for f in files]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
