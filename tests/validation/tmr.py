"""NASA TMR flat-plate reference data and the grid-convergence procedure (pure functions, no OpenFOAM).

Reference data: tests/data/tmr/ (README there). Grid convergence: Celik, Ghia, Roache, Freitas, Coleman,
Raad, "Procedure for Estimation and Reporting of Uncertainty Due to Discretization in CFD Applications",
J. Fluids Eng. 130 (2008) 078001, the procedure the TMR pages use.
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "tmr"
X_REF = 0.970084071  # the TMR station for Cf
PASS_LIMIT = 0.03  # |error| <= 3 %: PASS
NOTE_LIMIT = 0.05  # 3 % < |error| <= 5 %: PASS WITH NOTE (TMR note on OpenFOAM's SST); above: FAIL
OPENFOAM_NOTE_URL = "https://tmbwg.github.io/turbmodels/openfoam_issues.html"


def read_zones(path: Path) -> dict[str, list[list[float]]]:
    """Tecplot ASCII zones of a TMR .dat file: zone title -> rows of floats."""
    zones: dict[str, list[list[float]]] = {}
    current = None
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "variables")):
            continue
        if stripped.lower().startswith("zone"):
            current = re.search(r't="([^"]*)"', stripped).group(1)
            zones[current] = []
            continue
        zones[current].append([float(v.replace("D", "E")) for v in stripped.split()])
    return zones


@dataclass(frozen=True)
class Gci:
    """Celik et al. (2008) result for three solutions phi1 (fine), phi2, phi3 (coarse)."""

    order: float  # observed (apparent) order p
    extrapolated: float  # phi_ext^21
    approx_error: float  # e_a^21 = |(phi1 - phi2) / phi1|
    extrapolated_error: float  # e_ext^21 = |(phi_ext - phi1) / phi_ext|
    gci_fine: float  # GCI_fine^21 = 1.25 e_a^21 / (r21^p - 1)
    monotonic: bool  # s = sign(eps32 / eps21) > 0


def celik_gci(phi1: float, phi2: float, phi3: float, r21: float = 2.0, r32: float = 2.0) -> Gci:
    """Observed order by fixed-point iteration of p = |ln|eps32/eps21| + q(p)| / ln r21 with
    q(p) = ln((r21^p - s) / (r32^p - s)) (q = 0 for a constant ratio), then Richardson extrapolation
    and the fine-grid convergence index with safety factor 1.25."""
    eps21, eps32 = phi2 - phi1, phi3 - phi2
    s = 1.0 if eps32 / eps21 > 0 else -1.0
    p = 1.0
    for _ in range(200):
        q = math.log((r21**p - s) / (r32**p - s))
        p_new = abs(math.log(abs(eps32 / eps21)) + q) / math.log(r21)
        if abs(p_new - p) < 1e-12:
            break
        p = p_new
    ext = (r21**p * phi1 - phi2) / (r21**p - 1)
    ea = abs((phi1 - phi2) / phi1)
    return Gci(p, ext, ea, abs((ext - phi1) / ext), 1.25 * ea / (r21**p - 1), s > 0)


def incompressible_reference() -> tuple[float, float]:
    """(mean of the finest-grid values, mean of the extrapolated values) of Cf at X_REF over the
    three incompressible codes of cf_incomp_results_sstv.dat (three finest grids each, r = 2)."""
    zones = read_zones(DATA / "cf_incomp_results_sstv.dat")
    finest, extrapolated = [], []
    for rows in zones.values():
        rows = sorted(rows, key=lambda r: -r[0])  # finest (largest N) first
        finest.append(rows[0][3])
        extrapolated.append(celik_gci(rows[0][3], rows[1][3], rows[2][3]).extrapolated)
    return sum(finest) / len(finest), sum(extrapolated) / len(extrapolated)


def cf_plate(code: str = "CFL3D") -> tuple[list[float], list[float]]:
    """(x, cf) over the plate (x >= 0) from cf_plate_sstv.dat, compressible, finest grid."""
    rows = [r for r in read_zones(DATA / "cf_plate_sstv.dat")[code] if r[0] >= 0.0]
    return [r[0] for r in rows], [r[1] for r in rows]


def verdict(error: float) -> str:
    """Band of a relative error against the TMR reference."""
    if abs(error) <= PASS_LIMIT:
        return "PASS"
    if abs(error) <= NOTE_LIMIT:
        return "PASS WITH NOTE"
    return "FAIL"
