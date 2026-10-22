"""Mesh size estimate from the domain and the sizing targets (pure, no Qt)."""

import math
from dataclasses import dataclass

from vortexcfd.core.model import Mesh

Bounds = tuple[float, float, float, float, float, float]  # xmin, xmax, ymin, ymax, zmin, zmax

# snappyHexMesh's nCellsBetweenLevels (castellatedMeshControls, written by foam/mesh_case.py): the
# buffer of cells at each level before the next coarser one; the refinement volume estimate builds its
# staircase of levels from it (D-103).
CELLS_BETWEEN_LEVELS = 3
# The Generate Mesh button is disabled above this many background cells.
MAX_BACKGROUND_CELLS = 2_000_000
# A rounded domain (D-078) is cut out of a background box that encloses its surface with this many
# base cells on every side (none on the symmetry plane, which is the box's own y_min face).
BACKGROUND_MARGIN_CELLS = 2


@dataclass(frozen=True)
class MeshEstimate:
    """Sizes the mesher will use, before running it."""

    base_size: float  # background cell size, metres
    base_size_overridden: bool
    cells: tuple[int, int, int]  # background cells per direction
    total_cells: int  # background cells
    level_min: int  # surface refinement levels
    level_max: int
    levels_overridden: bool  # at least one level is an explicit user value
    surface_size: float  # surface cell size at level_max, metres
    background_bounds: Bounds | None = None  # the blockMesh box (the domain's bounds for a box domain)
    surface_length: float = 0.0  # the length target_surface_size multiplies, metres
    # Curvature refinement (D-085): the finest level it may reach on a part at the mesh's levels
    # (level_max + Mesh.curvature_levels; level_max when it is off) and that level's cell size.
    curvature_level: int = 0
    curvature_size: float = 0.0
    # Extra cells of the user refinement volumes (D-103; workflow/refinement.staircase_cells, summed; overlapping volumes
    # are counted twice). They count against the same limit as the background cells.
    volume_cells: int = 0
    # The 2D mode (D-121): the span of the one-cell slab (the surface cell size), 0 in 3D.
    span: float = 0.0

    @property
    def two_d(self) -> bool:
        return self.span > 0.0

    @property
    def budget_cells(self) -> int:
        """The cells the limit applies to: the background cells plus the refinement volumes' extra cells."""
        return self.total_cells + self.volume_cells

    @property
    def too_many_cells(self) -> bool:
        return self.budget_cells > MAX_BACKGROUND_CELLS

    def limit_message(self) -> str | None:
        """Why the mesh cannot be generated, or None when the background mesh is acceptable."""
        if not self.too_many_cells:
            return None
        if self.volume_cells:
            return (
                f"The background mesh and the refinement volumes would have {self.budget_cells:,} cells "
                f"({self.total_cells:,} background, {self.volume_cells:,} in the volumes; limit "
                f"{MAX_BACKGROUND_CELLS:,}): coarsen or shrink the refinement volumes, increase the base size "
                f"or lower the background cell target."
            )
        return (
            f"The background mesh would have {self.total_cells:,} cells "
            f"(limit {MAX_BACKGROUND_CELLS:,}): increase the base size, lower the background "
            f"cell target or shrink the domain."
        )


def volume_level(base_size: float, target_size: float) -> int:
    """The refinement level of a volume with cell size ``target_size`` (D-103): the coarsest level whose
    cell size base / 2^level is at or below the target (rounding towards the finer level); 0 when the
    target is not finer than the background cell."""
    if target_size >= base_size:
        return 0
    return max(0, math.ceil(math.log2(base_size / target_size) - 1e-9))


def volume_staircase(level: int, base_size: float,
                     cells_between_levels: int = CELLS_BETWEEN_LEVELS) -> list[tuple[int, float]]:
    """The staircase of a refinement volume at ``level`` over the background (level 0), D-103 [NUMERICS-REVIEW]:
    (level k, outward growth in metres of the region at k from the region inside it), from k = ``level``
    (grown from the volume itself) down to k = 1. The region at level k is the next finer region (the
    volume itself for k = level) grown by ``cells_between_levels`` cells of that level's size base / 2^k,
    as snappyHexMesh keeps nCellsBetweenLevels cells at each level before the next coarser one."""
    return [(k, cells_between_levels * base_size / 2 ** k) for k in range(level, 0, -1)]


def estimate_mesh(domain_bounds: Bounds, surface_length: float, mesh: Mesh, volume: float | None = None,
                  rounded: bool = False, symmetric: bool = False, two_d: bool = False) -> MeshEstimate:
    """Background cells, refinement levels and surface cell size for ``mesh`` in the domain.

    ``surface_length`` is the length the target surface size multiplies (l_ref or L, see
    Mesh.surface_size_reference; the caller resolves it, D-085).
    base_size = (domain volume / background_cells_target)^(1/3) unless overridden, with the actual
    domain ``volume`` when given (a rounded domain is smaller than its bounding box, D-078);
    level_max = max(0, ceil(log2(base_size / (target_surface_size * surface_length)))) and
    level_min = max(level_max - 1, 0), unless given explicitly. A ``rounded`` domain's background box
    is its bounds grown by BACKGROUND_MARGIN_CELLS base cells (not at y_min when ``symmetric``); the
    cell counts are those of the background box.

    ``two_d`` (D-121): the domain is a section in x-z; base_size = (domain area / background_cells_target)^(1/2)
    with the area = volume / y extent; the background is one cell across the span, which is the surface cell
    size (base / 2^level_max), centred on the domain's mid y. [NUMERICS-REVIEW]
    """
    extents = (
        domain_bounds[1] - domain_bounds[0],
        domain_bounds[3] - domain_bounds[2],
        domain_bounds[5] - domain_bounds[4],
    )
    if volume is None:
        volume = extents[0] * extents[1] * extents[2]
    overridden = mesh.base_size is not None
    if two_d:
        area = volume / extents[1] if extents[1] > 0 else extents[0] * extents[2]
        base = mesh.base_size if overridden else (area / mesh.background_cells_target) ** 0.5
    else:
        base = mesh.base_size if overridden else (volume / mesh.background_cells_target) ** (1 / 3)
    background = tuple(domain_bounds)
    if rounded:
        m = BACKGROUND_MARGIN_CELLS * base
        background = tuple(
            v - m if i % 2 == 0 and not (i == 2 and symmetric) else v + m if i % 2 else v
            for i, v in enumerate(domain_bounds)
        )
        extents = (background[1] - background[0], background[3] - background[2], background[5] - background[4])
    target = mesh.target_surface_size * surface_length
    computed_max = max(0, math.ceil(math.log2(base / target))) if target > 0 else 0
    level_max = mesh.surface_level_max if mesh.surface_level_max is not None else computed_max
    level_min = (
        mesh.surface_level_min if mesh.surface_level_min is not None else max(level_max - 1, 0)
    )
    level_min = min(level_min, level_max)
    span = 0.0
    if two_d:
        span = base / 2**level_max
        mid = 0.5 * (background[2] + background[3])
        background = (background[0], background[1], mid - 0.5 * span, mid + 0.5 * span, background[4], background[5])
        extents = (extents[0], span, extents[2])
    cells = tuple(max(1, round(e / base)) if i != 1 or not two_d else 1 for i, e in enumerate(extents))
    return MeshEstimate(
        base_size=base,
        base_size_overridden=overridden,
        cells=cells,  # type: ignore[arg-type]
        total_cells=cells[0] * cells[1] * cells[2],
        level_min=level_min,
        level_max=level_max,
        levels_overridden=mesh.surface_level_min is not None or mesh.surface_level_max is not None,
        surface_size=base / 2**level_max,
        background_bounds=background,  # type: ignore[arg-type]
        surface_length=surface_length,
        curvature_level=level_max + mesh.curvature_levels,
        curvature_size=base / 2 ** (level_max + mesh.curvature_levels),
        span=span,
    )
