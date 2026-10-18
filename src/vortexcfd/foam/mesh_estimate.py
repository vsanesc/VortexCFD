"""Mesh size estimate from the domain and the sizing targets (pure, no Qt)."""

import math
from dataclasses import dataclass

from vortexcfd.core.model import Mesh

Bounds = tuple[float, float, float, float, float, float]  # xmin, xmax, ymin, ymax, zmin, zmax

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

    @property
    def too_many_cells(self) -> bool:
        return self.total_cells > MAX_BACKGROUND_CELLS

    def limit_message(self) -> str | None:
        """Why the mesh cannot be generated, or None when the background mesh is acceptable."""
        if not self.too_many_cells:
            return None
        return (
            f"The background mesh would have {self.total_cells:,} cells "
            f"(limit {MAX_BACKGROUND_CELLS:,}): increase the base size, lower the background "
            f"cell target or shrink the domain."
        )


def estimate_mesh(domain_bounds: Bounds, reference_length: float, mesh: Mesh, volume: float | None = None,
                  rounded: bool = False, symmetric: bool = False) -> MeshEstimate:
    """Background cells, refinement levels and surface cell size for ``mesh`` in the domain.

    base_size = (domain volume / background_cells_target)^(1/3) unless overridden, with the actual
    domain ``volume`` when given (a rounded domain is smaller than its bounding box, D-078);
    level_max = max(0, ceil(log2(base_size / (target_surface_size * L)))) and
    level_min = max(level_max - 1, 0), unless given explicitly. A ``rounded`` domain's background box
    is its bounds grown by BACKGROUND_MARGIN_CELLS base cells (not at y_min when ``symmetric``); the
    cell counts are those of the background box.
    """
    extents = (
        domain_bounds[1] - domain_bounds[0],
        domain_bounds[3] - domain_bounds[2],
        domain_bounds[5] - domain_bounds[4],
    )
    if volume is None:
        volume = extents[0] * extents[1] * extents[2]
    overridden = mesh.base_size is not None
    base = mesh.base_size if overridden else (volume / mesh.background_cells_target) ** (1 / 3)
    background = tuple(domain_bounds)
    if rounded:
        m = BACKGROUND_MARGIN_CELLS * base
        background = tuple(
            v - m if i % 2 == 0 and not (i == 2 and symmetric) else v + m if i % 2 else v
            for i, v in enumerate(domain_bounds)
        )
        extents = (background[1] - background[0], background[3] - background[2], background[5] - background[4])
    cells = tuple(max(1, round(e / base)) for e in extents)
    target = mesh.target_surface_size * reference_length
    computed_max = max(0, math.ceil(math.log2(base / target))) if target > 0 else 0
    level_max = mesh.surface_level_max if mesh.surface_level_max is not None else computed_max
    level_min = (
        mesh.surface_level_min if mesh.surface_level_min is not None else max(level_max - 1, 0)
    )
    level_min = min(level_min, level_max)
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
    )
