"""Solver case files for steady incompressible external aerodynamics (no Qt).

Keywords and file names follow the ESI v2606 tutorials incompressible/simpleFoam/motorBike
(fvSchemes, fvSolution, 0.orig/, constant/transportProperties, constant/turbulenceProperties,
system/forceCoeffs) and airFoil2D. [NUMERICS-REVIEW]
"""


def inlet_turbulence(speed: float, intensity: float, nu: float, viscosity_ratio: float) -> tuple[float, float]:
    """Inlet k (m2/s2) and omega (1/s) from the free-stream speed, turbulence intensity and
    eddy-to-molecular viscosity ratio.

    k = 1.5 (V I)^2          turbulence kinetic energy from the intensity I = u' / V
                             (isotropic turbulence, k = 3/2 u'^2)
    omega = k / (nu * ratio) from nut = k / omega and ratio = nut / nu

    Source: the standard estimates of the OpenFOAM user guide (turbulence inlet conditions). The
    motorBike tutorial uses fixed values (k = 0.24, omega = 1.78) instead.
    """
    k = 1.5 * (speed * intensity) ** 2
    omega = k / (nu * viscosity_ratio)
    return k, omega
