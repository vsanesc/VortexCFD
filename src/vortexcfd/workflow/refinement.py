"""User refinement volumes: sizing, domain check, cell estimate and the wake helper (D-103; Qt-free)."""

from dataclasses import dataclass, replace
from pathlib import Path

from vortexcfd.core.model import ConeShape, RefinementVolume, SurfaceShape
from vortexcfd.core.project import Project, volume_base_name
from vortexcfd.foam.mesh_case import SurfaceRegionEntry, VolumeEntry, part_level_range, volume_surface_file
from vortexcfd.foam.mesh_estimate import MeshEstimate, volume_level, volume_staircase
from vortexcfd.geometry import refinement_volumes as rv
from vortexcfd.geometry.checks import check_surface
from vortexcfd.geometry.loader import SurfaceLoadError, load_surface
from vortexcfd.geometry.attitude import Attitude
from vortexcfd.geometry.domain import DomainBox, union_bounds

# Shown with the estimate (the cell counts of overlapping volumes are added, not merged).
OVERLAP_NOTE = ("Each volume's extra cells are estimated on its own, as a staircase: the volume grown by "
                "nCellsBetweenLevels cells at its level, then a shell of nCellsBetweenLevels cells at each coarser "
                "level, each clipped to the domain; overlapping volumes are counted twice.")
# A volume wholly outside the domain is a warning, never an error: it is left out and meshing goes on
# (owner review of D-103, QUESTIONS 134).
OUTSIDE_IGNORED = "Ignored: outside the domain"
PARTIAL_WARNING = "Part of the volume ({outside:.0f} %) lies outside the domain: only the part inside refines."
FINER_WARNING = ("The target is finer than the finest part surface level (level {level}, {size:.4g} m): "
                 "this volume may dominate the cell count.")


class RegionFileError(ValueError):
    """An imported refinement region's surface cannot be used (missing, unreadable, or not closed in the inside
    mode)."""


class RegionNotClosedError(RegionFileError):
    """The surface is open: usable only to refine within a distance of it (D-159)."""


NOT_CLOSED = ("{name} is not a closed surface ({detail}): refining inside a surface needs a closed one (refine "
              "within a distance of it instead, fix it, or import it as a part and repair it first)")


def load_region(path: Path, units: str, mode: str = "inside") -> "rv.pv.PolyData":
    """An imported region's surface in metres, or RegionFileError when it is missing or unreadable (D-145). The
    inside mode needs a closed surface (outward normals: an inward-oriented one is flipped, on a copy); the distance
    mode takes an open one too, as snappyHexMesh's distance refinement does (D-159)."""
    try:
        mesh = load_surface(path, units)
    except (FileNotFoundError, SurfaceLoadError) as exc:
        raise RegionFileError(f"{Path(path).name}: {exc}") from exc
    report = check_surface(mesh, intersections=False)
    if not report.watertight:
        if mode == "distance":
            return mesh
        detail = f"{report.open_edges} open edges, {report.non_manifold_edges} non-manifold edges"
        raise RegionNotClosedError(NOT_CLOSED.format(name=Path(path).name, detail=detail))
    if report.normals_inward:
        mesh = mesh.copy()
        mesh.flip_faces(inplace=True)
    return mesh


def geometry_shape(project: Project, shape):
    """The geometry the estimate, the viewer and the writer use for a volume shape: an imported surface
    (SurfaceShape) loaded as a ``SurfaceRegion`` (metres, outward normals); any other shape as it is.
    Raises RegionFileError for an unusable surface."""
    if not isinstance(shape, SurfaceShape):
        return shape
    folder = project.folder
    if folder is None:
        raise RegionFileError("the project has no folder")
    mesh = load_region(folder / shape.file, shape.units, shape.mode)
    return rv.SurfaceRegion(mesh, shape.mode, shape.distance)


def meshing_shape(project: Project, volume: RefinementVolume, attitude: Attitude | None):
    """``geometry_shape`` turned with the parts for a "body" volume at an angle of attack (D-120)."""
    shape = geometry_shape(project, volume.shape)
    if attitude is None or not attitude.rotated or volume.frame != "body":
        return shape
    return attitude.shape(shape)


def region_problems(project: Project) -> list[str]:
    """Why an enabled imported region cannot be meshed (one line each; D-145)."""
    out = []
    for v in project.sim.refinement_volumes:
        if v.enabled and isinstance(v.shape, SurfaceShape):
            try:
                geometry_shape(project, v.shape)
            except RegionFileError as exc:
                out.append(f"Refinement region '{v.name}': {exc}")
    return out


@dataclass(frozen=True)
class VolumeInfo:
    """What meshing does with one volume: its level, the cell size that gives, the share inside the
    domain, the extra cells it adds (its staircase of levels, staircase_cells), ``buffer``: how far the
    outermost region reaches beyond the volume (m), and ``status`` "inside", "partial", "outside" or
    "disabled"."""

    volume: RefinementVolume
    level: int
    achieved_size: float
    fraction: float
    extra_cells: int
    status: str
    messages: tuple[str, ...]
    buffer: float = 0.0

    @property
    def written(self) -> bool:
        return self.status in ("inside", "partial")

    @property
    def ignored(self) -> bool:
        """Enabled but wholly outside the domain: not written, shown as a warning."""
        return self.status == "outside"


def finest_part_level(project: Project, est: MeshEstimate) -> int:
    """The highest maximum surface level of the parts (their overrides, else the mesh's)."""
    parts = project.sim.geometry.parts
    if not parts:
        return est.level_max
    return max(part_level_range(est.level_min, est.level_max, (p.surface_level_min, p.surface_level_max))[1]
               for p in parts)


def volume_info(volume: RefinementVolume, box: DomainBox, est: MeshEstimate, finest: int,
                shape=None) -> VolumeInfo:
    """``shape``: the volume's geometry as meshed (``meshing_shape``); None: ``volume.shape`` (analytic)."""
    shape = volume.shape if shape is None else shape
    level = volume_level(est.base_size, volume.target_size)
    achieved = est.base_size / 2 ** level
    if not volume.enabled:
        return VolumeInfo(volume, level, achieved, 0.0, 0, "disabled", ())
    fraction = rv.domain_fraction(shape, box)
    messages = []
    if fraction <= 0.0:
        status = "outside"
        messages.append(OUTSIDE_IGNORED)
    elif fraction < 1.0:
        status = "partial"
        messages.append(PARTIAL_WARNING.format(outside=100.0 * (1.0 - fraction)))
    else:
        status = "inside"
    if level > finest:
        messages.append(FINER_WARNING.format(level=finest, size=est.base_size / 2 ** finest))
    steps = volume_staircase(level, est.base_size)
    buffer = sum(d for _k, d in steps)
    extra = staircase_cells(shape, box, est.base_size, steps) if fraction > 0 else 0
    return VolumeInfo(volume, level, achieved, fraction, extra, status, tuple(messages), buffer)


def staircase_cells(shape, box: DomainBox, base_size: float, steps: list[tuple[int, float]]) -> int:
    """The extra cells of a volume's staircase (D-103, owner review) [NUMERICS-REVIEW]: the region at its
    level (the shape grown by the first step) and, for each coarser level, the shell between that region
    and the previous one grown again; each region's volume clipped to the domain (its exact volume times
    its sampled share inside); extra cells = sum over the regions and shells of V (8^k - 1) / base^3, i.e.
    the cells at level k minus the background cells in the same volume."""
    total, inner_volume, region = 0.0, 0.0, shape
    for k, distance in steps:
        region = rv.grow(region, distance)
        inside = rv.domain_fraction(region, box) * rv.volume(region)
        total += max(0.0, inside - inner_volume) * (8 ** k - 1) / base_size ** 3
        inner_volume = max(inner_volume, inside)
    return int(round(total))


def meshing_volume(volume: RefinementVolume, attitude: Attitude | None) -> RefinementVolume:
    """The volume as meshing sees it: a "body" volume turned with the parts at the angle of attack, a
    "wind" volume as it is (D-120). [NUMERICS-REVIEW]"""
    if attitude is None or not attitude.rotated or volume.frame != "body":
        return volume
    return volume.model_copy(update={"shape": attitude.shape(volume.shape)})


def volume_infos(project: Project, box: DomainBox, est: MeshEstimate,
                 attitude: Attitude | None = None) -> list[VolumeInfo]:
    """The VolumeInfo of every refinement volume, in the project's order, each in the meshing frame
    (``attitude``: the parts' rotation, workflow/meshing.project_attitude; None: not rotated)."""
    finest = finest_part_level(project, est)
    out = []
    for v in project.sim.refinement_volumes:
        if isinstance(v.shape, SurfaceShape):  # an imported region: its surface loaded (D-145)
            shape = meshing_shape(project, v, attitude) if v.enabled else None
            out.append(volume_info(v, box, est, finest, shape))
        else:
            out.append(volume_info(meshing_volume(v, attitude), box, est, finest))
    return out


def with_volumes(est: MeshEstimate, infos: list[VolumeInfo]) -> MeshEstimate:
    """``est`` with the volumes' extra cells added (the cell-budget limit then includes them)."""
    return replace(est, volume_cells=sum(i.extra_cells for i in infos))


def volume_entries(infos: list[VolumeInfo]) -> tuple[VolumeEntry, ...]:
    """The volumes meshing writes: enabled and at least partly inside the domain. An imported region is written as
    its surface file in constant/triSurface (``write_region_surfaces``, D-145)."""
    return tuple(VolumeEntry(i.volume.name, _entry_shape(i.volume), i.level) for i in infos if i.written)


def _entry_shape(volume: RefinementVolume):
    shape = volume.shape
    if isinstance(shape, SurfaceShape):
        return SurfaceRegionEntry(volume_surface_file(volume.name), shape.mode, shape.distance)
    return shape


def write_region_surfaces(case_dir: Path, tri_surface: str, project: Project, entries, attitude) -> None:
    """The surfaces of the imported regions among ``entries`` (VolumeEntry) written to <case>/<tri_surface>/ in
    metres as meshed (turned with the parts at an angle of attack); stale region files are removed (D-145)."""
    folder = case_dir / tri_surface
    wanted = {}
    by_name = {v.name: v for v in project.sim.refinement_volumes}
    for entry in entries:
        if entry.surface_file is not None and entry.name in by_name:
            wanted[entry.surface_file] = by_name[entry.name]
    for stale in folder.glob(f"{volume_surface_file('*')}"):
        if stale.name not in wanted:
            stale.unlink(missing_ok=True)
    for file, volume in wanted.items():
        meshing_shape(project, volume, attitude).mesh.save(str(folder / file), binary=False)


def is_closed(path: Path, units: str) -> bool:
    """Whether a region's surface can refine inside itself (closed); RegionFileError when it cannot be read."""
    try:
        load_region(path, units, "inside")
    except RegionNotClosedError:
        return False
    return True


def region_mode(path: Path, units: str) -> str:
    """The mode a new imported region starts in: inside a closed surface, within a distance of an open one."""
    return "inside" if is_closed(path, units) else "distance"


def surface_volume(project: Project, relative: str, units: str, est: MeshEstimate, mode: str | None = None,
                   distance: float = 0.0, name: str | None = None) -> RefinementVolume:
    """A refinement volume of the imported surface ``relative`` (in the project folder), its target the part surface
    cell size; ``mode`` None: inside a closed surface, within a distance of an open one (D-159); ``distance`` in
    metres for the distance mode (0: one surface cell)."""
    if mode is None:
        mode = region_mode(project.folder / relative, units)  # RegionFileError when not readable
    load_region(project.folder / relative, units, mode)  # RegionFileError when not usable in that mode
    if mode == "distance" and distance <= 0:
        distance = est.surface_size
    shape = SurfaceShape(file=relative, units=units, mode=mode, distance=distance if mode == "distance" else 0.0)
    base = volume_base_name(name or Path(relative).stem)
    return RefinementVolume(id="new", name=project.free_volume_name(base), shape=shape, target_size=est.surface_size)


def new_volume(project: Project, kind: str, box: DomainBox, est: MeshEstimate) -> RefinementVolume:
    """A volume of shape ``kind`` with editable defaults placed over the parts (or the domain centre):
    sized like the parts' box, target = the part surface cell size."""
    from vortexcfd.core.model import BoxShape, CylinderShape, SphereShape

    b = box.parts_bounds or box.bounds or (-0.5, 0.5, -0.5, 0.5, -0.5, 0.5)
    c = ((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2)
    ext = (max(b[1] - b[0], 1e-6), max(b[3] - b[2], 1e-6), max(b[5] - b[4], 1e-6))
    r = max(ext) / 2
    if kind == "box":
        shape = BoxShape(centre=c, size=tuple(2 * e for e in ext))
    elif kind == "cylinder":
        shape = CylinderShape(point1=(b[0], c[1], c[2]), point2=(b[1] + max(ext), c[1], c[2]), radius=r)
    elif kind == "sphere":
        shape = SphereShape(centre=c, radius=1.5 * r)
    elif kind == "cone":
        shape = ConeShape(point1=(b[1], c[1], c[2]), point2=(b[1] + 2 * max(ext), c[1], c[2]),
                          radius1=r, radius2=1.5 * r)
    else:
        raise ValueError(f"unknown volume shape {kind!r}")
    return RefinementVolume(id="new", name=project.free_volume_name(kind), shape=shape,
                            target_size=est.surface_size)


def wake_volume(project: Project, part_indices: list[int], parts_bounds: list, est: MeshEstimate) -> RefinementVolume:
    """The "Add wake volume" box behind the parts ``part_indices`` (``parts_bounds``: every part's box in
    metres as meshed, i.e. rotated by the angle of attack (D-120), in project order; empty: all parts) along
    the free stream, +x (geometry/refinement_volumes.wake_box, D-103), in the "wind" frame (it does not turn
    with the parts); the part surface cell size is the finest maximum surface level of those parts.
    [NUMERICS-REVIEW]"""
    parts = project.sim.geometry.parts
    chosen = part_indices or list(range(len(parts)))
    bounds = union_bounds([parts_bounds[i] for i in chosen])
    level = max(part_level_range(est.level_min, est.level_max,
                                 (parts[i].surface_level_min, parts[i].surface_level_max))[1] for i in chosen)
    box, target = rv.wake_box(bounds, est.base_size / 2 ** level)
    return RefinementVolume(id="new", name=project.free_volume_name("wake"), shape=box, target_size=target,
                            frame="wind")
