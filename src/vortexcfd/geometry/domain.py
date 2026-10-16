"""Far-field domain box around the parts (no Qt)."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from vortexcfd.core.model import Domain

Bounds = tuple[float, float, float, float, float, float]  # xmin, xmax, ymin, ymax, zmin, zmax

# Part y_min farther than this fraction of L from the symmetry plane is reported.
SYMMETRY_TOLERANCE = 0.01

# Boundary names in display order.
BOUNDARY_NAMES = ("inlet", "outlet", "sides", "top", "bottom", "symmetry")


@dataclass(frozen=True)
class DomainBox:
    """The computed domain. ``bounds`` is None when there are no parts."""

    reference_length: float  # L in metres (0 without parts)
    bounds: Bounds | None
    size: tuple[float, float, float]
    # boundary name -> faces as (axis, side) with axis 0/1/2 = x/y/z and side 0 = min, 1 = max
    boundaries: dict[str, tuple[tuple[int, int], ...]]
    warnings: list[str] = field(default_factory=list)


def union_bounds(parts_bounds: Sequence[Bounds]) -> Bounds:
    return (
        min(b[0] for b in parts_bounds), max(b[1] for b in parts_bounds),
        min(b[2] for b in parts_bounds), max(b[3] for b in parts_bounds),
        min(b[4] for b in parts_bounds), max(b[5] for b in parts_bounds),
    )


def face_corners(bounds: Bounds, axis: int, side: int) -> list[tuple[float, float, float]]:
    """The four corners of one face of a box (counter-clockwise seen from outside is not
    guaranteed; the corners are in loop order)."""
    lo = [bounds[0], bounds[2], bounds[4]]
    hi = [bounds[1], bounds[3], bounds[5]]
    fixed = hi[axis] if side else lo[axis]
    a, b = [i for i in range(3) if i != axis]
    corners = []
    for u, v in ((lo[a], lo[b]), (hi[a], lo[b]), (hi[a], hi[b]), (lo[a], hi[b])):
        p = [0.0, 0.0, 0.0]
        p[axis], p[a], p[b] = fixed, u, v
        corners.append((p[0], p[1], p[2]))
    return corners


def compute_domain(
    parts_bounds: Sequence[Bounds], domain: Domain, names: Sequence[str] | None = None
) -> DomainBox:
    """Domain box from the parts' bounding boxes (metres) and the multipliers.

    L is the largest extent of the union of the parts' boxes. The box extends ``upstream * L``
    before and ``downstream * L`` after the parts along x (the flow), ``lateral * L`` on each
    side along y and ``vertical * L`` above and below along z. With symmetry "y_min" the box
    starts at the parts' y_min instead.
    """
    if not parts_bounds:
        return DomainBox(0.0, None, (0.0, 0.0, 0.0), {},
                         ["No parts: import a surface to define the domain."])
    u = union_bounds(parts_bounds)
    length = max(u[1] - u[0], u[3] - u[2], u[5] - u[4])
    symmetric = domain.symmetry == "y_min"
    bounds: Bounds = (
        u[0] - domain.upstream * length, u[1] + domain.downstream * length,
        u[2] if symmetric else u[2] - domain.lateral * length, u[3] + domain.lateral * length,
        u[4] - domain.vertical * length, u[5] + domain.vertical * length,
    )
    boundaries: dict[str, tuple[tuple[int, int], ...]] = {
        "inlet": ((0, 0),),
        "outlet": ((0, 1),),
        "sides": ((1, 1),) if symmetric else ((1, 0), (1, 1)),
        "top": ((2, 1),),
        "bottom": ((2, 0),),
    }
    if symmetric:
        boundaries["symmetry"] = ((1, 0),)
    warnings: list[str] = []
    if symmetric and length > 0:
        for i, b in enumerate(parts_bounds):
            if b[2] - u[2] > SYMMETRY_TOLERANCE * length:
                label = names[i] if names is not None else f"Part {i + 1}"
                warnings.append(
                    f"{label} does not touch the symmetry plane "
                    f"(its y_min is {b[2] - u[2]:.4g} m above it)."
                )
    size = (bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
    return DomainBox(length, bounds, size, boundaries, warnings)
