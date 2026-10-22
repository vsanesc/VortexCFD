"""Grid convergence index (no Qt). [NUMERICS-REVIEW]

Celik, Ghia, Roache, Freitas, Coleman, Raad, "Procedure for Estimation and Reporting of Uncertainty
Due to Discretization in CFD Applications", J. Fluids Eng. 130 (2008) 078001: three solutions
phi1 (fine), phi2, phi3 (coarse) on grids with representative cell sizes h1 < h2 < h3 and ratios
r21 = h2 / h1, r32 = h3 / h2.

- eps21 = phi2 - phi1, eps32 = phi3 - phi2, s = sign(eps32 / eps21);
- the apparent order p solves p = |ln|eps32 / eps21| + q(p)| / ln r21 with
  q(p) = ln((r21^p - s) / (r32^p - s)) (fixed-point iteration; q = 0 for r21 = r32);
- phi_ext^21 = (r21^p phi1 - phi2) / (r21^p - 1);
- e_a^21 = |(phi1 - phi2) / phi1|, e_ext^21 = |(phi_ext - phi1) / phi_ext|;
- GCI_fine^21 = 1.25 e_a^21 / (r21^p - 1), GCI_medium^32 = 1.25 e_a^32 / (r32^p - 1).

Oscillatory convergence (s < 0: the differences have opposite signs) gets no number: the paper's
p is then not an order of convergence, and the result says "oscillatory, GCI not applicable".
Equal solutions on two grids (eps = 0) give no order either ("converged to the digits shown" when
both differences are zero, otherwise "undefined").

Asymptotic range check: GCI_medium^32 / (r21^p GCI_fine^21) close to 1 means the three grids are
in the asymptotic range (Roache's check, the ratio of the two GCIs corrected by the order).
"""

import math
from dataclasses import dataclass

SAFETY_FACTOR = 1.25
MONOTONIC = "monotonic"
OSCILLATORY = "oscillatory"
DIVERGENT = "divergent"  # same signs, but the differences grow with refinement (no order p > 0)
UNDEFINED = "undefined"
OSCILLATORY_TEXT = "oscillatory, GCI not applicable"
# The asymptotic ratio within this band of 1 counts as in the asymptotic range.
ASYMPTOTIC_BAND = 0.1


@dataclass(frozen=True)
class GciResult:
    """The result for three solutions. The numbers are None unless ``convergence`` is monotonic."""

    convergence: str  # MONOTONIC, OSCILLATORY, DIVERGENT or UNDEFINED
    order: float | None = None  # apparent order p
    extrapolated: float | None = None  # phi_ext^21
    approx_error: float | None = None  # e_a^21 (fraction)
    extrapolated_error: float | None = None  # e_ext^21 (fraction)
    gci_fine: float | None = None  # GCI_fine^21 (fraction)
    gci_medium: float | None = None  # GCI_medium^32 (fraction)
    asymptotic_ratio: float | None = None  # GCI_medium^32 / (r21^p GCI_fine^21)

    @property
    def applicable(self) -> bool:
        return self.convergence == MONOTONIC and self.gci_fine is not None

    @property
    def in_asymptotic_range(self) -> bool | None:
        if self.asymptotic_ratio is None:
            return None
        return abs(self.asymptotic_ratio - 1.0) <= ASYMPTOTIC_BAND

    @property
    def text(self) -> str:
        """One line for tables: the GCI or why there is none."""
        if self.applicable:
            return f"GCI {100 * self.gci_fine:.3g} %"
        if self.convergence == OSCILLATORY:
            return OSCILLATORY_TEXT
        if self.convergence == DIVERGENT:
            return "divergent (differences grow with refinement), GCI not applicable"
        return "undefined (equal solutions on two grids), GCI not applicable"


def apparent_order(eps21: float, eps32: float, r21: float, r32: float, s: float = 1.0) -> float:
    """p by fixed-point iteration (Celik et al. 2008, Eqs. 3a-3c)."""
    p = 1.0
    for _ in range(500):
        q = math.log((r21**p - s) / (r32**p - s))
        p_new = abs(math.log(abs(eps32 / eps21)) + q) / math.log(r21)
        if abs(p_new - p) < 1e-12:
            return p_new
        p = p_new
    return p


def celik_gci(phi1: float, phi2: float, phi3: float, r21: float, r32: float) -> GciResult:
    """Celik et al. (2008) for phi1 (fine), phi2 (medium), phi3 (coarse); r21, r32 > 1."""
    if r21 <= 1.0 or r32 <= 1.0:
        raise ValueError("refinement ratios must be above 1")
    eps21, eps32 = phi2 - phi1, phi3 - phi2
    if eps21 == 0.0 or eps32 == 0.0:
        return GciResult(UNDEFINED)
    s = 1.0 if eps32 / eps21 > 0 else -1.0
    if s < 0:
        return GciResult(OSCILLATORY)
    p = apparent_order(eps21, eps32, r21, r32, s)
    # The absolute value in the order equation also returns a p > 0 when the change GROWS with
    # refinement; such a p does not reproduce the data: phi = phi0 + C h^p gives
    # eps32 / eps21 = r21^p (r32^p - 1) / (r21^p - 1).
    if not math.isfinite(p) or p <= 0.0:
        return GciResult(DIVERGENT)
    predicted = r21**p * (r32**p - 1.0) / (r21**p - 1.0)
    if abs(predicted - eps32 / eps21) > 1e-6 * abs(eps32 / eps21):
        return GciResult(DIVERGENT)
    ext = (r21**p * phi1 - phi2) / (r21**p - 1.0)
    ea21 = abs((phi1 - phi2) / phi1) if phi1 != 0 else math.inf
    ea32 = abs((phi2 - phi3) / phi2) if phi2 != 0 else math.inf
    eext = abs((ext - phi1) / ext) if ext != 0 else math.inf
    gci21 = SAFETY_FACTOR * ea21 / (r21**p - 1.0)
    gci32 = SAFETY_FACTOR * ea32 / (r32**p - 1.0)
    ratio = gci32 / (r21**p * gci21) if gci21 > 0 else None
    return GciResult(MONOTONIC, p, ext, ea21, eext, gci21, gci32, ratio)


def cell_size(volume: float, cells: int, dimensions: int = 3) -> float:
    """Representative cell size h = (V / N)^(1/3) in 3D, (A / N)^(1/2) in 2D with ``volume`` the area
    (Celik et al. 2008, Eqs. 1 and 2)."""
    if cells <= 0 or volume <= 0:
        raise ValueError("volume and cell count must be positive")
    return (volume / cells) ** (1.0 / dimensions)


def study(values: list[float], sizes: list[float]) -> GciResult:
    """GCI from three (value, h) pairs in any order (sorted fine to coarse by h)."""
    if len(values) != 3 or len(sizes) != 3:
        raise ValueError("a GCI needs exactly three grids")
    pairs = sorted(zip(sizes, values))
    (h1, f1), (h2, f2), (h3, f3) = pairs
    return celik_gci(f1, f2, f3, h2 / h1, h3 / h2)
