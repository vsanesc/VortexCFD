"""First-layer thickness estimate for a target y+ (pure, no Qt). [NUMERICS-REVIEW]"""

import math
from dataclasses import dataclass


def skin_friction(reynolds: float) -> float:
    """Turbulent flat-plate skin friction coefficient, Cf = 0.026 / Re^(1/7)."""
    return 0.026 / reynolds ** (1.0 / 7.0)


def friction_velocity(speed: float, nu: float, length: float) -> float:
    """u* = sqrt(tau_w / rho) with tau_w = 0.5 rho V^2 Cf and Cf from Re = V L / nu."""
    cf = skin_friction(speed * length / nu)
    return math.sqrt(0.5 * speed**2 * cf)


def first_layer_thickness(target_yplus: float, speed: float, nu: float, reference_length: float) -> float:
    """First prism-layer thickness (metres) that gives ``target_yplus``.

    y = y+ nu / u*, with u* from the turbulent flat-plate correlation Cf = 0.026 / Re^(1/7) at
    Re = V L / nu (L = ``reference_length``): tau_w = 0.5 rho V^2 Cf, u* = sqrt(tau_w / rho).

    Convention: the returned value is used AS the first cell height. snappyHexMesh's
    ``firstLayerThickness`` (with ``relativeSizes false``) is the thickness of the cell next to the
    wall, so the cell CENTRE sits at half of it and the y+ that OpenFOAM's ``yPlus`` function
    reports (which uses the cell-centre distance) is about ``target_yplus / 2``. The "twice the
    cell-centre distance" convention is NOT applied: ``yplus_of_first_cell`` is the inverse.
    """
    return target_yplus * nu / friction_velocity(speed, nu, reference_length)


def yplus_of_first_cell(thickness: float, speed: float, nu: float, x: float) -> float:
    """y+ at the CENTRE of a first cell of height ``thickness`` at distance ``x`` from the leading
    edge (the quantity OpenFOAM's yPlus function reports): 0.5 * thickness * u*(Re_x) / nu."""
    return 0.5 * thickness * friction_velocity(speed, nu, x) / nu


MAX_LAYERS = 30
WARNING_HINT = "refine the surface or raise target y+"
# D2 of task 5.4 (D-106): the hard maximum of the expansion ratio the layer cap may raise it to.
MAX_EXPANSION_RATIO = 1.3
# The layer cap of the robust layer controls (D-106), chosen from the 5.4 study (benchmarks/RESULT_5.4.md).
LAYER_CAP = 12


def layer_cap(layer_controls: str) -> dict:
    """The cap arguments of ``plan_layers`` for Mesh.layer_controls: "robust" caps at LAYER_CAP layers
    with the expansion ratio raised to at most MAX_EXPANSION_RATIO (D-106); "legacy" (projects saved
    before schema v13) has no cap."""
    if layer_controls != "robust":
        return {}
    return {"max_layers": LAYER_CAP, "max_expansion": MAX_EXPANSION_RATIO}


def stack_thickness(first: float, expansion: float, count: int) -> float:
    """Total thickness of a geometric stack of ``count`` layers from ``first`` at ratio ``expansion``."""
    if count <= 0:
        return 0.0
    if abs(expansion - 1.0) < 1e-12:
        return first * count
    return first * (expansion**count - 1) / (expansion - 1)


def expansion_for(first: float, count: int, total: float, low: float, high: float) -> float:
    """The expansion ratio in [low, high] at which ``count`` layers from ``first`` reach ``total``
    (``high`` when even that falls short; ``low`` when ``low`` already reaches it). Bisection: the
    stack thickness grows monotonically with the ratio."""
    if stack_thickness(first, low, count) >= total:
        return low
    if stack_thickness(first, high, count) <= total:
        return high
    for _ in range(200):
        mid = 0.5 * (low + high)
        if stack_thickness(first, mid, count) < total:
            low = mid
        else:
            high = mid
    return high


@dataclass(frozen=True)
class LayerPlan:
    """Prism layer stack derived from the y+ first layer and the surface cell size.

    ``planned_*`` is the stack of the count rule at the user's expansion ratio; ``count``,
    ``expansion``, ``total`` and ``final`` the stack written to the mesher, which differs from the
    planned one only when a layer cap applies (D-106): fewer layers, the ratio raised up to the
    maximum to keep the planned total, and a thinner stack (``thickness_warning``) when even the
    maximum ratio cannot reach it. The first layer (the y+ estimate) is never changed."""

    count: int  # number of layers written, clamped to [1, MAX_LAYERS] and to the cap
    first: float  # first layer thickness, metres
    expansion: float  # the expansion ratio written
    total: float  # total thickness of the stack written (achievable), metres
    final: float  # thickness of the last layer, metres
    surface_size: float  # surface cell size at the maximum refinement level, metres
    needed: float  # 0.5 * surface_size / first: the growth the stack has to cover
    warning: str | None  # set when the stack cannot reach half a surface cell within 30 layers
    planned_count: int = 0  # the count rule's layers at the user's ratio (before the cap)
    planned_expansion: float = 0.0  # the user's expansion ratio
    planned_total: float = 0.0  # the planned total thickness, metres
    capped: bool = False  # the layer cap reduced the count
    thickness_warning: str | None = None  # the achievable stack is thinner than the planned one

    @property
    def thickness_percent(self) -> float:
        """The achievable stack thickness in percent of the planned one."""
        return 100.0 * self.total / self.planned_total if self.planned_total > 0 else 100.0


def plan_layers(first: float, expansion: float, surface_size: float, max_layers: int | None = None,
                max_expansion: float | None = None) -> LayerPlan:
    """Number of layers so that the geometric stack (first layer ``first``, ratio ``expansion``)
    reaches a final layer of about half the surface cell size:

        n = ceil(ln(0.5 h_surface / t1) / ln(r)) + 1,   clamped to [1, 30].

    A warning is set when n would exceed 30 or when 0.5 h_surface / t1 > r^29 (the stack cannot
    reach half a surface cell): refine the surface or raise the target y+.

    Layer cap (D-106; ``max_layers`` None: no cap): when n exceeds ``max_layers`` the stack keeps the
    first layer and gets ``max_layers`` layers, with the expansion ratio raised (from ``expansion``, at
    most ``max_expansion``) until it reaches the planned total thickness; if the maximum ratio cannot
    reach it, the stack is thinner and ``thickness_warning`` says by how much.
    """
    needed = 0.5 * surface_size / first
    if expansion <= 1.0:
        raw = MAX_LAYERS if needed > 1.0 else 1
    elif needed <= 1.0:
        raw = 1
    else:
        raw = math.ceil(math.log(needed) / math.log(expansion) - 1e-9) + 1  # tolerance: exact powers
    planned_count = max(1, min(MAX_LAYERS, raw))
    warn = raw > MAX_LAYERS or needed > expansion ** (MAX_LAYERS - 1)
    planned_total = stack_thickness(first, expansion, planned_count)
    count, ratio, total = planned_count, expansion, planned_total
    capped = max_layers is not None and planned_count > max_layers
    thickness_warning = None
    if capped:
        count = max(1, max_layers)
        high = max(expansion, max_expansion if max_expansion is not None else expansion)
        ratio = expansion_for(first, count, planned_total, expansion, high)
        total = stack_thickness(first, ratio, count)
        if total < planned_total * (1 - 1e-6):
            thickness_warning = (
                f"The layer stack is thinner than planned: {count} layers (the cap) at expansion ratio "
                f"{ratio:.3g} reach {total:.3g} m of the planned {planned_total:.3g} m "
                f"({100.0 * total / planned_total:.0f} %); the first layer ({first:.3g} m, for the target y+) "
                "is kept.")
    return LayerPlan(
        count=count, first=first, expansion=ratio, total=total,
        final=first * ratio ** (count - 1), surface_size=surface_size, needed=needed,
        warning=(f"The layer stack cannot reach half a surface cell ({0.5 * surface_size:.3g} m) from a "
                 f"{first:.3g} m first layer within {MAX_LAYERS} layers: {WARNING_HINT}.") if warn else None,
        planned_count=planned_count, planned_expansion=expansion, planned_total=planned_total,
        capped=capped, thickness_warning=thickness_warning,
    )
