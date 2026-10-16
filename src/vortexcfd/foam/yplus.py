"""First-layer thickness estimate for a target y+ (pure, no Qt). [NUMERICS-REVIEW]"""

import math


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
