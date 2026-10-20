"""User refinement volumes: sizing, domain check, cell estimate and the wake helper (D-103; Qt-free)."""

from dataclasses import dataclass, replace

from vortexcfd.core.model import ConeShape, RefinementVolume
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_case import VolumeEntry, part_level_range
from vortexcfd.foam.mesh_estimate import MeshEstimate, volume_level, volume_staircase
from vortexcfd.geometry import refinement_volumes as rv
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


def volume_info(volume: RefinementVolume, box: DomainBox, est: MeshEstimate, finest: int) -> VolumeInfo:
    level = volume_level(est.base_size, volume.target_size)
    achieved = est.base_size / 2 ** level
    if not volume.enabled:
        return VolumeInfo(volume, level, achieved, 0.0, 0, "disabled", ())
    fraction = rv.domain_fraction(volume.shape, box)
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
    extra = staircase_cells(volume.shape, box, est.base_size, steps) if fraction > 0 else 0
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


def volume_infos(project: Project, box: DomainBox, est: MeshEstimate) -> list[VolumeInfo]:
    """The VolumeInfo of every refinement volume, in the project's order."""
    finest = finest_part_level(project, est)
    return [volume_info(v, box, est, finest) for v in project.sim.refinement_volumes]


def with_volumes(est: MeshEstimate, infos: list[VolumeInfo]) -> MeshEstimate:
    """``est`` with the volumes' extra cells added (the cell-budget limit then includes them)."""
    return replace(est, volume_cells=sum(i.extra_cells for i in infos))


def volume_entries(infos: list[VolumeInfo]) -> tuple[VolumeEntry, ...]:
    """The volumes meshing writes: enabled and at least partly inside the domain."""
    return tuple(VolumeEntry(i.volume.name, i.volume.shape, i.level) for i in infos if i.written)


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
    metres, in project order; empty: all parts) aligned with the free stream (geometry/refinement_volumes.
    wake_box, D-103); the part surface cell size is the finest maximum surface level of those parts.
    [NUMERICS-REVIEW]"""
    parts = project.sim.geometry.parts
    chosen = part_indices or list(range(len(parts)))
    bounds = union_bounds([parts_bounds[i] for i in chosen])
    level = max(part_level_range(est.level_min, est.level_max,
                                 (parts[i].surface_level_min, parts[i].surface_level_max))[1] for i in chosen)
    box, target = rv.wake_box(bounds, project.sim.inflow.alpha_deg, est.base_size / 2 ** level)
    return RefinementVolume(id="new", name=project.free_volume_name("wake"), shape=box, target_size=target)
