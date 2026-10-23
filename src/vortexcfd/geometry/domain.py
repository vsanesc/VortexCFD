"""Far-field domain around the parts: box, bullet and C-type shapes (no Qt, D-019, D-078)."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from vortexcfd.core.model import Domain

Bounds = tuple[float, float, float, float, float, float]  # xmin, xmax, ymin, ymax, zmin, zmax

# Part y_min farther than this fraction of L from the symmetry plane is reported.
SYMMETRY_TOLERANCE = 0.01

# Boundary names (roles) in display order; a shape uses some of them (DomainBox.roles).
BOUNDARY_NAMES = ("inlet", "outlet", "farfield", "sides", "top", "bottom", "ground", "symmetry")
SHAPE_ROLES = {
    "box": ("inlet", "outlet", "sides", "top", "bottom"),
    "bullet": ("inlet", "outlet", "farfield"),
    "c_type": ("inlet", "outlet", "farfield", "sides"),
}
SHAPE_LABELS = {"box": "Box", "bullet": "Bullet", "c_type": "C-type"}


def shape_roles(shape: str, symmetric: bool, ground: bool = False) -> tuple[str, ...]:
    """The boundary roles of a domain shape, in display order. With the ground plane (box only, D-116)
    the bottom face is the role "ground" instead of "bottom"."""
    roles = SHAPE_ROLES[shape]
    if ground and shape == "box":
        roles = tuple("ground" if r == "bottom" else r for r in roles)
    return roles + (("symmetry",) if symmetric else ())


@dataclass(frozen=True)
class DomainBox:
    """The computed domain. ``bounds`` (the domain's own bounding box) is None when there are no parts.

    ``boundaries`` maps the box's roles to its faces; the rounded shapes have no box faces and are
    described by ``axis`` (the centre of the rounded front: hemisphere centre for the bullet, a point
    of the spanwise half-cylinder axis for the C-type), ``radius_m`` and ``x_rear`` (the outlet
    plane); the C-type spans y over ``y_span``. ``volume`` is the exact (analytic) domain volume.
    """

    reference_length: float  # L in metres (0 without parts)
    bounds: Bounds | None
    size: tuple[float, float, float]
    # boundary name -> faces as (axis, side) with axis 0/1/2 = x/y/z and side 0 = min, 1 = max
    boundaries: dict[str, tuple[tuple[int, int], ...]]
    warnings: list[str] = field(default_factory=list)
    shape: str = "box"
    symmetric: bool = False
    volume: float = 0.0
    roles: tuple[str, ...] = ()
    axis: tuple[float, float, float] | None = None
    radius_m: float = 0.0
    x_rear: float = 0.0
    y_span: tuple[float, float] = (0.0, 0.0)
    parts_bounds: Bounds | None = None  # union of the boxes of the parts the domain is sized around
    ground: bool = False  # the bottom face is the ground plane (D-116)
    two_d: bool = False  # a 2D section in x-z (D-121): the mesh is a one-cell slab across y
    # Internal flow (D-129): no domain; ``bounds`` are the parts' bounds and ``volume`` the fluid volume inside them.
    internal: bool = False

    @property
    def rounded(self) -> bool:
        return self.shape != "box"

    @property
    def inlet_x(self) -> float | None:
        """x of the inlet where the axis meets it (the box's x_min)."""
        if self.bounds is None:
            return None
        return self.axis[0] - self.radius_m if self.rounded else self.bounds[0]

    def contains(self, point: Sequence[float], tol: float = 1e-9) -> bool:
        """True if ``point`` lies inside the domain (or on its boundary within ``tol``)."""
        if self.bounds is None:
            return False
        x, y, z = point
        b = self.bounds
        if not (b[0] - tol <= x <= b[1] + tol and b[2] - tol <= y <= b[3] + tol and b[4] - tol <= z <= b[5] + tol):
            return False
        if not self.rounded:
            return True
        ax, ay, az = self.axis
        r = self.radius_m + tol
        if self.shape == "bullet":
            radial2 = (y - ay) ** 2 + (z - az) ** 2
            if x < ax:
                return (x - ax) ** 2 + radial2 <= r * r
            return radial2 <= r * r
        if x < ax:  # c_type: the front half-cylinder (spanwise axis)
            return (x - ax) ** 2 + (z - az) ** 2 <= r * r
        return True


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


def ground_z(domain: Domain, parts_union: Bounds) -> float:
    """z of the ground plane (D-116): the lowest z of the parts the domain is sized around, or the
    user's value."""
    return parts_union[4] if domain.ground.position == "parts_min" else domain.ground.z


def ground_wall_start(domain: Domain, bounds: Bounds) -> float | None:
    """x where the ground wall starts when a slip strip lies upstream of it (D-118): the user's
    ``wall_start_x`` when the ground is on and the value lies strictly inside the box's x range (at or
    ahead of the inlet: no strip, the wall starts at the inlet). A value at or behind the outlet is
    returned too; meshing refuses it (workflow/meshing.meshing_problem)."""
    g = domain.ground
    if not g.enabled or domain.shape != "box" or g.wall_start_x is None or g.wall_start_x <= bounds[0]:
        return None
    return g.wall_start_x


def ground_warnings(parts_bounds: Sequence[Bounds], z: float, names: Sequence[str] | None) -> list[str]:
    """A part wholly below the ground plane is outside the fluid; one that crosses it is cut by the
    domain (the part of it below the plane is not meshed; its supports may do so on purpose)."""
    out = []
    for i, b in enumerate(parts_bounds):
        label = names[i] if names is not None else f"Part {i + 1}"
        if b[5] <= z:
            out.append(f"{label} lies below the ground plane (z = {z:.4g} m): it is outside the fluid.")
    return out


def _box_corners(b: Bounds) -> list[tuple[float, float, float]]:
    return [(x, y, z) for x in (b[0], b[1]) for y in (b[2], b[3]) for z in (b[4], b[5])]


def compute_domain(
    parts_bounds: Sequence[Bounds], domain: Domain, names: Sequence[str] | None = None
) -> DomainBox:
    """Domain from the parts' bounding boxes (metres) and the multipliers of L.

    The domain is sized around the parts listed in ``domain.parts`` (by name; None, or no listed
    part loaded: every part). L is the largest extent of the union of their boxes, c its centre.

    - box: ``upstream * L`` before and ``downstream * L`` after the parts along x (the flow),
      ``lateral * L`` on each side along y and ``vertical * L`` above and below along z. With
      symmetry "y_min" the box starts at the parts' y_min instead. With the ground plane (D-116) the
      bottom face is the ground at the parts' lowest z or at ``domain.ground.z``.
    - bullet: a hemisphere of radius ``radius * L`` centred at c, a cylinder of the same radius behind
      it along +x up to ``downstream * L`` after the parts. With symmetry the axis lies in the plane
      y = the parts' y_min and only the half y >= that plane is kept.
    - c_type: in the x-z plane a half-disc of radius ``radius * L`` centred at c in front, flat top
      and bottom at z = c_z +- R up to ``downstream * L`` after the parts; along y it spans
      c_y +- ``lateral * L``, or [y_min, y_min + lateral * L] with symmetry at the parts' y_min.
    """
    if not parts_bounds:
        return DomainBox(0.0, None, (0.0, 0.0, 0.0), {},
                         ["No parts: import a surface to define the domain."], shape=domain.shape,
                         symmetric=domain.symmetry == "y_min")
    selected = list(parts_bounds)
    if domain.parts is not None and names is not None:
        chosen = [b for b, n in zip(parts_bounds, names) if n in domain.parts]
        selected = chosen or selected
    u = union_bounds(selected)
    length = max(u[1] - u[0], u[3] - u[2], u[5] - u[4])
    symmetric = domain.symmetry == "y_min"
    centre = ((u[0] + u[1]) / 2, (u[2] + u[3]) / 2, (u[4] + u[5]) / 2)
    shape = domain.shape
    boundaries: dict[str, tuple[tuple[int, int], ...]] = {}
    axis = None
    radius_m = x_rear = 0.0
    y_span = (0.0, 0.0)
    ground = domain.ground.enabled and shape == "box"
    if shape == "box":
        z_ground = ground_z(domain, u) if ground else None
        ext = {name: domain.extent_m(name, length) for name in ("upstream", "downstream", "lateral", "vertical")}
        bounds: Bounds = (
            u[0] - ext["upstream"], u[1] + ext["downstream"],
            u[2] if symmetric else u[2] - ext["lateral"], u[3] + ext["lateral"],
            u[4] - ext["vertical"] if z_ground is None else z_ground, u[5] + ext["vertical"],
        )
        boundaries = {
            "inlet": ((0, 0),),
            "outlet": ((0, 1),),
            "sides": ((1, 1),) if symmetric else ((1, 0), (1, 1)),
            "top": ((2, 1),),
            "ground" if ground else "bottom": ((2, 0),),
        }
        if symmetric:
            boundaries["symmetry"] = ((1, 0),)
        volume = (bounds[1] - bounds[0]) * (bounds[3] - bounds[2]) * (bounds[5] - bounds[4])
    else:
        radius_m = domain.extent_m("radius", length)
        x_rear = u[1] + domain.extent_m("downstream", length)
        if shape == "bullet":
            axis = (centre[0], u[2] if symmetric else centre[1], centre[2])
            bounds = (axis[0] - radius_m, x_rear, axis[1] if symmetric else axis[1] - radius_m,
                      axis[1] + radius_m, axis[2] - radius_m, axis[2] + radius_m)
            volume = (2.0 / 3.0 * math.pi * radius_m ** 3
                      + math.pi * radius_m ** 2 * max(0.0, x_rear - axis[0])) * (0.5 if symmetric else 1.0)
        else:  # c_type
            axis = (centre[0], centre[1], centre[2])
            half = domain.extent_m("lateral", length)
            y_span = (u[2], u[2] + half) if symmetric else (centre[1] - half, centre[1] + half)
            bounds = (axis[0] - radius_m, x_rear, y_span[0], y_span[1], axis[2] - radius_m, axis[2] + radius_m)
            area = 0.5 * math.pi * radius_m ** 2 + 2.0 * radius_m * max(0.0, x_rear - axis[0])
            volume = area * (y_span[1] - y_span[0])
    roles = shape_roles(shape, symmetric, ground)
    size = (bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
    box = DomainBox(length, bounds, size, boundaries, [], shape=shape, symmetric=symmetric, volume=volume,
                    roles=roles, axis=axis, radius_m=radius_m, x_rear=x_rear, y_span=y_span, parts_bounds=u,
                    ground=ground)
    warnings = box.warnings
    if ground:
        warnings.extend(ground_warnings(parts_bounds, bounds[4], names))
    if symmetric and length > 0:
        for i, b in enumerate(parts_bounds):
            if b[2] - u[2] > SYMMETRY_TOLERANCE * length:
                label = names[i] if names is not None else f"Part {i + 1}"
                warnings.append(
                    f"{label} does not touch the symmetry plane "
                    f"(its y_min is {b[2] - u[2]:.4g} m above it)."
                )
    if box.rounded:
        outside = [names[i] if names is not None else f"Part {i + 1}" for i, b in enumerate(parts_bounds)
                   if not all(box.contains(c) for c in _box_corners(b))]
        if outside:
            warnings.append(f"The domain does not enclose {', '.join(outside)}: increase the radius or the "
                            "downstream length.")
    return box


def internal_box(parts_bounds: Sequence[Bounds], fluid_volume: float) -> DomainBox:
    """The "domain" of an internal-flow analysis (D-129): the union of the parts' boxes, the fluid volume inside the
    closed geometry, L the largest extent; no far-field boundaries."""
    if not parts_bounds:
        return DomainBox(0.0, None, (0.0, 0.0, 0.0), {}, ["No parts: import the closed geometry of the fluid."],
                         internal=True)
    u = union_bounds(list(parts_bounds))
    size = (u[1] - u[0], u[3] - u[2], u[5] - u[4])
    return DomainBox(max(size), u, size, {}, shape="box", volume=fluid_volume, parts_bounds=u, internal=True)
