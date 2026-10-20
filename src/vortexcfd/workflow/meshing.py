"""Meshing orchestration: project -> meshing case directory (Qt-free).

Lives in workflow/: it joins core (project), geometry (surfaces, domain) and
foam (case files), and foam/ must not depend on geometry/ (which imports pyvista).
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vortexcfd.core.project import Project
from vortexcfd.core.project_io import V10_MESH_FIELDS
from vortexcfd.foam.mesh_estimate import estimate_mesh
from vortexcfd.foam.yplus import LayerPlan, first_layer_thickness, plan_layers
from vortexcfd.foam.mesh_case import (
    DOMAIN_SURFACE,
    TRI_SURFACE,
    MeshCaseInput,
    build_mesh_files,
    location_in_mesh,
    needs_seeding,
    part_level_range,
    prepare_case_dir,
    part_patch_names,
    safe_part_names,
    wall_patch_names,
    write_domain_guard,
    write_seed_edge_meshes,
)
from vortexcfd.foam.mesh_estimate import BACKGROUND_MARGIN_CELLS, MeshEstimate
from vortexcfd.foam.physics_case import LENGTH_AUTO_LABEL, reference_values
from vortexcfd.geometry import regions
from vortexcfd.geometry.domain import DomainBox, compute_domain, union_bounds
from vortexcfd.geometry.domain_surface import ROLE_ARRAY, meshing_surface
from vortexcfd.geometry.loader import SurfaceLoadError, load_surface
from vortexcfd.workflow import surface_prep

CASE_DIR_NAME = "case"


class MeshingNotReady(Exception):
    """The project cannot be meshed yet; the message says why."""


@dataclass(frozen=True)
class MeshJob:
    """A prepared meshing case."""

    case_dir: Path
    inputs: MeshCaseInput
    box: DomainBox


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


def _loaded_parts(project: Project, prepared: bool = True):
    """(domain box, part names, loaded meshes in metres) for the project's parts: the surfaces the
    current surface preparation made (D-093), else the parts' own (``prepared`` False: always the
    parts' own)."""
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
    bounds = [tuple(float(b) for b in m.bounds) for m in meshes]
    return compute_domain(bounds, project.sim.domain, names), names, meshes


def loaded_original_parts(project: Project):
    """(domain box, part names, meshes in metres) of the parts' own surfaces (no preparation)."""
    return _loaded_parts(project, prepared=False)


def parts_layout(project: Project) -> tuple[DomainBox, tuple[str, ...], tuple[float, ...]]:
    """(domain box, every part wall patch name, union of the parts' bounding boxes in metres).

    Raises:
        MeshingNotReady: a part cannot be loaded.
    """
    box, _names, meshes = _loaded_parts(project)
    bounds = [tuple(float(b) for b in m.bounds) for m in meshes]
    return box, wall_patch_names(project.sim.geometry.parts), union_bounds(bounds) if bounds else None


def write_part_surfaces(case_dir: Path, project: Project, inputs: MeshCaseInput, meshes) -> None:
    """The part STLs of a meshing case (metres): a part with several patches (or one renamed patch)
    gets one solid per patch, named after it (D-071); other parts are written as loaded."""
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
    """The mesh estimate of ``box`` (its actual volume; the background box of a rounded shape) with
    the surface size from ``surface_length`` (None: the domain's L; see ``surface_length``)."""
    length = box.reference_length if surface_length is None else surface_length
    return estimate_mesh(box.bounds, length, mesh, volume=box.volume, rounded=box.rounded,
                         symmetric=box.symmetric)


@dataclass(frozen=True)
class SurfaceLength:
    """The length the target surface size multiplies (D-085): ``source`` is "l_ref" (set in the
    Reference Values), "l_ref_auto" (l_ref never set: its automatic value) or "largest_extent" (L,
    projects made before schema v10)."""

    value: float
    source: str

    def describe(self) -> str:
        if self.source == "largest_extent":
            return f"L = {self.value:.4g} m (largest extent of the parts)"
        return f"l_ref = {self.value:.4g} m" + (f" ({LENGTH_AUTO_LABEL})" if self.source == "l_ref_auto" else "")


SURFACE_LENGTH_AUTO_WARNING = ("l_ref is not set: the surface cell size and the y+ first layer use its automatic "
                               "value ({auto}). Set the reference length under Reports & Monitors > "
                               "Reference Values.")


def surface_length(project: Project, box: DomainBox, parts_bounds=None) -> SurfaceLength:
    """The surface size length of ``project`` (``parts_bounds``: the union of every part's box, as
    the solver's reference values use; None: loaded here). Never raises."""
    if project.sim.mesh.surface_size_reference == "largest_extent":
        return SurfaceLength(box.reference_length, "largest_extent")
    if parts_bounds is None:
        try:
            _box, _names, meshes = _loaded_parts(project)
            parts_bounds = union_bounds([tuple(float(b) for b in m.bounds) for m in meshes]) if meshes else None
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
    e.g. a mesh study level)."""
    return estimate_for(box, mesh or project.sim.mesh, surface_length(project, box, parts_bounds).value)


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
    est = estimate_for(box, project.sim.mesh)
    parts = union_bounds([tuple(float(b) for b in m.bounds) for m in meshes])
    return location_in_mesh(est.background_bounds, parts, est.cells, box.inlet_x if box.rounded else None)


def plan_layers_for(project: Project, box: DomainBox) -> LayerPlan:
    """The y+ layer stack for ``project``: first layer from the estimator with Re on the surface size
    length (l_ref, or L for projects made before schema v10; D-088), count from the surface cell size
    at the maximum refinement level (see foam/yplus.plan_layers). [NUMERICS-REVIEW]"""
    mesh = project.sim.mesh
    length = surface_length(project, box)
    first = first_layer_thickness(mesh.target_yplus, project.sim.inflow.speed, project.sim.physics.nu,
                                  length.value)
    est = estimate_for(box, mesh, length.value)
    return plan_layers(first, mesh.expansion_ratio, est.surface_size)


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
    return plan_layers_for(project, box).warning


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
    if not project.sim.domain.enabled:
        if project.sim.analysis_type == "empty":
            return "Generate the domain first (Regions > Domain)."
        return "Enable the fluid domain."
    try:
        box, _, _ = _loaded_parts(project)
    except MeshingNotReady as exc:
        return str(exc)
    return estimate_for(box, project.sim.mesh).limit_message()


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
    length = surface_length(project, box, union_bounds(bounds))
    safe = safe_part_names(names)
    first_layer = layer_count = None
    if project.sim.mesh.layer_sizing == "absolute_yplus":
        plan = plan_layers_for(project, box)
        first_layer, layer_count = plan.first, plan.count
    inputs = MeshCaseInput(
        domain_bounds=box.bounds,
        symmetric=project.sim.domain.symmetry == "y_min",
        parts=tuple(safe),
        parts_bounds=union_bounds(bounds),
        reference_length=box.reference_length,
        mesh=project.sim.mesh,
        first_layer_thickness=first_layer,
        layer_count=layer_count,
        part_bounds=tuple(bounds),
        part_levels=_part_overrides(project),
        part_patches=tuple(part_patch_names(project.sim.geometry.parts)),
        surface_length=length.value,
        extra_features=_junction_features(project, box, length.value),
        **domain_fields(box),
    )
    return inputs, box, meshes


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
    return MeshJob(case_dir, inputs, box)


def junction_level(project: Project, box: DomainBox, length: float) -> int:
    """The refinement level of the intersection curves (D-093, corrected in D-097): the finest level
    the parts' surfaces can reach, their highest maximum surface level (overrides, else the mesh's)
    plus the curvature refinement levels (D-085). The parts' maximum surface level alone is often below
    what curvature refinement already gives the cells at a junction, and then the curves refine
    nothing (the 5.2 aircraft: level 5 against cells at level 7). [NUMERICS-REVIEW]"""
    est = estimate_for(box, project.sim.mesh, length)
    top = max(part_level_range(est.level_min, est.level_max, o)[1] for o in _part_overrides(project))
    return top + project.sim.mesh.curvature_levels


def _junction_features(project: Project, box: DomainBox, length: float) -> tuple[tuple[str, int], ...]:
    prep = surface_prep.current(project)
    if prep is None or prep.features_file is None or not project.sim.geometry.parts:
        return ()
    return ((surface_prep.JUNCTION_FILE, junction_level(project, box, length)),)


def write_junction_features(case_dir: Path, project: Project, inputs: MeshCaseInput) -> None:
    """Copy the surface preparation's intersection curves into constant/triSurface (D-093); an earlier
    copy is removed when the case has none."""
    target = case_dir / TRI_SURFACE / surface_prep.JUNCTION_FILE
    prep = surface_prep.current(project)
    if not inputs.extra_features or prep is None or prep.features_file is None:
        target.unlink(missing_ok=True)
        return
    target.write_bytes((project.folder / prep.features_file).read_bytes())


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
    for key, legacy in V10_MESH_FIELDS.items():  # a project meshed before v10 keeps its hash (D-085)
        if mesh.get(key) == legacy:
            del mesh[key]
    payload = {
        "parts": parts,
        "domain": project.sim.domain.model_dump(),
        "mesh": mesh,
        # Absolute (y+) layer sizes depend on the flow; relative sizes do not.
        "yplus_inputs": (
            [project.sim.inflow.speed, project.sim.physics.nu]
            if project.sim.mesh.layer_sizing == "absolute_yplus" else None
        ),
    }
    if project.sim.mesh.surface_size_reference == "l_ref":  # l_ref sizes the surface (D-085)
        payload["surface_l_ref"] = project.sim.reports.reference_length
    prep = project.sim.surface_prep
    if prep is not None:  # the prepared surfaces and curves are meshing inputs (D-093)
        folder = project.path.parent if project.path else None
        files = [f for p in prep.parts for f in (p.surface_file, p.region_ids)] + [prep.features_file]
        payload["surface_prep"] = [prep.strategy, prep.inputs_hash] + [
            _hash_file(folder / f) if folder is not None and f and (folder / f).is_file() else None for f in files]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
