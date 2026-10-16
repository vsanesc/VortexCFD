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


@dataclass(frozen=True)
class LayerPlan:
    """Prism layer stack derived from the y+ first layer and the surface cell size."""

    count: int  # number of layers, clamped to [1, MAX_LAYERS]
    first: float  # first layer thickness, metres
    expansion: float
    total: float  # total thickness of the stack, metres
    final: float  # thickness of the last layer, metres
    surface_size: float  # surface cell size at the maximum refinement level, metres
    needed: float  # 0.5 * surface_size / first: the growth the stack has to cover
    warning: str | None  # set when the stack cannot reach half a surface cell within 30 layers


def plan_layers(first: float, expansion: float, surface_size: float) -> LayerPlan:
    """Number of layers so that the geometric stack (first layer ``first``, ratio ``expansion``)
    reaches a final layer of about half the surface cell size:

        n = ceil(ln(0.5 h_surface / t1) / ln(r)) + 1,   clamped to [1, 30].

    A warning is set when n would exceed 30 or when 0.5 h_surface / t1 > r^29 (the stack cannot
    reach half a surface cell): refine the surface or raise the target y+.
    """
    needed = 0.5 * surface_size / first
    if expansion <= 1.0:
        raw = MAX_LAYERS if needed > 1.0 else 1
    elif needed <= 1.0:
        raw = 1
    else:
        raw = math.ceil(math.log(needed) / math.log(expansion) - 1e-9) + 1  # tolerance: exact powers
    count = max(1, min(MAX_LAYERS, raw))
    warn = raw > MAX_LAYERS or needed > expansion ** (MAX_LAYERS - 1)
    total = first * (expansion**count - 1) / (expansion - 1) if expansion != 1.0 else first * count
    return LayerPlan(
        count=count, first=first, expansion=expansion, total=total,
        final=first * expansion ** (count - 1), surface_size=surface_size, needed=needed,
        warning=(f"The layer stack cannot reach half a surface cell ({0.5 * surface_size:.3g} m) from a "
                 f"{first:.3g} m first layer within {MAX_LAYERS} layers: {WARNING_HINT}.") if warn else None,
    )
