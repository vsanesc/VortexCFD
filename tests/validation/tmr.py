"""NASA TMR flat-plate reference data and the grid-convergence procedure (pure functions, no OpenFOAM).

Reference data: tests/data/tmr/ (README there). Grid convergence: Celik, Ghia, Roache, Freitas, Coleman,
Raad, "Procedure for Estimation and Reporting of Uncertainty Due to Discretization in CFD Applications",
J. Fluids Eng. 130 (2008) 078001, the procedure the TMR pages use, implemented in vortexcfd.foam.gci.
"""

import math
import re
from pathlib import Path

from vortexcfd.foam.gci import celik_gci  # the procedure itself lives in the app (Task 6.4)

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


def incompressible_reference() -> tuple[float, float]:
    """(mean of the finest-grid values, mean of the extrapolated values) of Cf at X_REF over the
    three incompressible codes of cf_incomp_results_sstv.dat (three finest grids each, r = 2)."""
    zones = read_zones(DATA / "cf_incomp_results_sstv.dat")
    finest, extrapolated = [], []
    for rows in zones.values():
        rows = sorted(rows, key=lambda r: -r[0])  # finest (largest N) first
        finest.append(rows[0][3])
        extrapolated.append(celik_gci(rows[0][3], rows[1][3], rows[2][3], 2.0, 2.0).extrapolated)
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
