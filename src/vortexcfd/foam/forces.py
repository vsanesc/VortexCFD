"""Force breakdown, centre of pressure and mass balance from the function objects' files (no Qt).
[NUMERICS-REVIEW] (D-060)

Files (v2606, checked on real runs, fixtures in tests/data/breakdown_run/):

- forces (``forces1`` for all walls, ``forces_<patch>`` per part when there are several parts):
  ``force.dat`` and ``moment.dat``, columns Time, total_x total_y total_z, pressure_x ... viscous_z,
  in N and N m (rho = rhoInf) in the global axes, moments about CofR.
- forceCoeffs header (``coefficient.dat``): dragDir, liftDir, magUInf, lRef, Aref and CofR used.
- surfaceFieldValue sum(phi) on a patch (``massFlow_<patch>``): ``surfaceFieldValue.dat``,
  columns Time, sum(phi) (m3/s, positive out of the domain).

Coefficients of a force F (pressure, viscous or total): C_d = F . dragDir / (q A_ref), C_l =
F . liftDir / (q A_ref), q = 0.5 rho U^2; the pitching moment coefficient C_m = M_y / (q A_ref
l_ref) (pitch axis +y, D-047). Centre of pressure along x in the body axes: the point on the
line through CofR parallel to the body x axis where the resultant gives the same pitching moment,
x_cp = x_CofR - M_y / F_z(body). The app turns the free stream by the angle of attack and never
the body, so the body axes are the global axes of the geometry (x along the chord, z normal to it)
and F_z(body) is the global z force, whatever the incidence. It is undefined (None) when
|F_z(body)| < CP_MIN_NORMAL q A_ref (near-zero normal force: the ratio is meaningless).
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path

CP_MIN_NORMAL = 1e-3  # |F_z(body)| / (q A_ref) below this: no centre of pressure
MASS_WARNING = 0.1  # percent of the inlet flux

Vector = tuple[float, float, float]
_VEC_RE = re.compile(r"^#\s*(\w+)\s*:\s*\(([^)]*)\)")
_NUM_RE = re.compile(r"^#\s*(\w+)\s*:\s*([-+0-9.eE]+)\s*$")


@dataclass(frozen=True)
class CoeffAxes:
    """The forceCoeffs reference values written in coefficient.dat's header."""

    drag_dir: Vector
    lift_dir: Vector
    mag_u: float
    l_ref: float
    a_ref: float
    cofr: Vector


def read_coeff_axes(path: Path) -> CoeffAxes | None:
    """The header of a coefficient.dat (None when incomplete)."""
    vectors, numbers = {}, {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith("#"):
                    break
                m = _VEC_RE.match(line)
                if m:
                    vectors[m.group(1)] = tuple(float(v) for v in m.group(2).split())
                    continue
                m = _NUM_RE.match(line)
                if m:
                    numbers[m.group(1)] = float(m.group(2))
    except OSError:
        return None
    try:
        return CoeffAxes(vectors["dragDir"], vectors["liftDir"], numbers["magUInf"], numbers["lRef"],
                         numbers["Aref"], vectors["CofR"])
    except KeyError:
        return None


@dataclass(frozen=True)
class ForceSample:
    """One row of force.dat and moment.dat: (total, pressure, viscous) vectors."""

    time: float
    force: tuple[Vector, Vector, Vector]
    moment: tuple[Vector, Vector, Vector] | None = None


def parse_vector_row(text: str) -> tuple[float, tuple[Vector, Vector, Vector]] | None:
    """A force.dat / moment.dat row -> (time, (total, pressure, viscous))."""
    try:
        values = [float(v) for v in text.replace("(", " ").replace(")", " ").split()]
    except ValueError:
        return None
    if len(values) < 10:
        return None
    t = values[0]
    vecs = tuple(tuple(values[1 + 3 * i:4 + 3 * i]) for i in range(3))
    return t, vecs  # type: ignore[return-value]


def _dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@dataclass(frozen=True)
class ForceRow:
    """Coefficients of one wall set (a part or all walls) at one iteration."""

    name: str
    cd: float
    cd_pressure: float
    cd_viscous: float
    cl: float
    cl_pressure: float
    cl_viscous: float
    cm: float | None
    x_cp: float | None  # m; None: undefined (near-zero normal force)


def breakdown(name: str, sample: ForceSample, axes: CoeffAxes, rho: float) -> ForceRow:
    """The force row of ``sample`` with the forceCoeffs axes and reference values."""
    q_a = 0.5 * rho * axes.mag_u ** 2 * axes.a_ref
    total, pressure, viscous = sample.force
    cd = [_dot(f, axes.drag_dir) / q_a for f in (total, pressure, viscous)]
    cl = [_dot(f, axes.lift_dir) / q_a for f in (total, pressure, viscous)]
    cm = x_cp = None
    if sample.moment is not None:
        my = sample.moment[0][1]
        cm = my / (q_a * axes.l_ref)
        if abs(total[2]) / q_a >= CP_MIN_NORMAL:
            x_cp = axes.cofr[0] - my / total[2]
    return ForceRow(name, cd[0], cd[1], cd[2], cl[0], cl[1], cl[2], cm, x_cp)


def mass_imbalance(inlet_flux: float, outlet_flux: float, others: float = 0.0) -> float | None:
    """Net flux out of the domain as a percentage of the inlet flux: 100 (phi_in + phi_out +
    others) / |phi_in| (sum(phi) is positive out of the domain, so phi_in < 0). None without inflow."""
    if inlet_flux == 0 or not math.isfinite(inlet_flux):
        return None
    return 100.0 * (inlet_flux + outlet_flux + others) / abs(inlet_flux)
