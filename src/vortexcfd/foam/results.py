"""Solver results on disk: the latest time directory and the fields it holds (no Qt, no pyvista).

The Results Scene lists only fields that exist in the latest time directory (D-053). Pressure in the
incompressible solvers is kinematic (p / rho, m2/s2), so the pressure coefficient is
Cp = p / (0.5 U_ref^2) with p_ref = 0 (the outlet value).
"""

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class FieldSpec:
    """A field the Results Scene can show."""

    key: str  # e.g. "p", "Cp", "U_mag", "U_x", "wallShearStress_mag"
    label: str  # shown in the selector and the scalar bar
    units: str
    source: str  # the OpenFOAM field file it comes from
    component: int | None = None  # 0, 1, 2 for a vector component (-1: along the free stream); None: scalar or magnitude
    magnitude: bool = False
    # The square root of a mean squared fluctuation (D-181): of a scalar (pPrime2Mean) or of a diagonal component of
    # a symmetric tensor (UPrime2Mean: xx 0, yy 3, zz 5).
    rms: bool = False

    @property
    def field_class(self) -> str:
        """The volume field class the source must have."""
        if self.rms and self.component is not None:
            return "volSymmTensorField"
        return "volVectorField" if (self.component is not None or self.magnitude) else "volScalarField"

    @property
    def title(self) -> str:
        return f"{self.label} [{self.units}]" if self.units else self.label


# In the order of the selector; a field is listed only when its source file exists.
FIELD_SPECS = (
    FieldSpec("p", "p (kinematic)", "m²/s²", "p"),
    FieldSpec("Cp", "Cp", "", "p"),
    FieldSpec("U_mag", "|U|", "m/s", "U", magnitude=True),
    FieldSpec("U_x", "Ux", "m/s", "U", component=0),
    FieldSpec("U_y", "Uy", "m/s", "U", component=1),
    FieldSpec("U_z", "Uz", "m/s", "U", component=2),
    FieldSpec("k", "k", "m²/s²", "k"),
    FieldSpec("omega", "omega", "1/s", "omega"),
    FieldSpec("nut", "nut", "m²/s", "nut"),
    FieldSpec("yPlus", "y+", "", "yPlus"),
    FieldSpec("wallShearStress_mag", "|\u03c4w| wall shear stress (kinematic)", "m²/s²", "wallShearStress",
              magnitude=True),
    # Skin friction on the walls (foam/wall_fields.py, D-061): |tau| / (0.5 U_ref^2) and its signed
    # component along the free stream (negative where the near-wall flow runs back).
    FieldSpec("Cf", "Cf", "", "wallShearStress", magnitude=True),
    FieldSpec("Cf_x", "Cf_x (free-stream direction)", "", "wallShearStress", component=-1),
    # The time-averaged fields of a transient run (fieldAverage, D-181): the means and the RMS of the fluctuations.
    FieldSpec("pMean", "p mean (kinematic)", "m²/s²", "pMean"),
    FieldSpec("CpMean", "Cp mean", "", "pMean"),
    FieldSpec("UMean_mag", "|U mean|", "m/s", "UMean", magnitude=True),
    FieldSpec("UMean_x", "Ux mean", "m/s", "UMean", component=0),
    FieldSpec("UMean_y", "Uy mean", "m/s", "UMean", component=1),
    FieldSpec("UMean_z", "Uz mean", "m/s", "UMean", component=2),
    FieldSpec("p_rms", "p RMS (kinematic)", "m²/s²", "pPrime2Mean", rms=True),
    FieldSpec("Ux_rms", "Ux RMS", "m/s", "UPrime2Mean", component=0, rms=True),
    FieldSpec("Uy_rms", "Uy RMS", "m/s", "UPrime2Mean", component=3, rms=True),
    FieldSpec("Uz_rms", "Uz RMS", "m/s", "UPrime2Mean", component=5, rms=True),
)
FIELDS_BY_KEY = {f.key: f for f in FIELD_SPECS}


def _time_value(name: str) -> float | None:
    try:
        return float(name)
    except ValueError:
        return None


def latest_result_time(case_dir: Path) -> str | None:
    """Name of the latest time directory after 0 that holds field files, or None (no results)."""
    best: tuple[float, str] | None = None
    case_dir = Path(case_dir)
    if not case_dir.is_dir():
        return None
    for child in case_dir.iterdir():
        value = _time_value(child.name)
        if value is None or value <= 0 or not child.is_dir():
            continue
        if not any(f.is_file() for f in child.iterdir()):
            continue
        if best is None or value > best[0]:
            best = (value, child.name)
    return best[1] if best else None


def result_times(case_dir: Path) -> list[str]:
    """The names of every time directory after 0 that holds field files, in time order (the Results Scene's time
    choice, D-181)."""
    case_dir = Path(case_dir)
    if not case_dir.is_dir():
        return []
    found = []
    for child in case_dir.iterdir():
        value = _time_value(child.name)
        if value is None or value <= 0 or not child.is_dir():
            continue
        if any(f.is_file() for f in child.iterdir()):
            found.append((value, child.name))
    return [name for _value, name in sorted(found)]


_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*;", re.MULTILINE)


def field_class(path: Path) -> str | None:
    """The FoamFile header class of a field file (read from its first 2 kB)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(2048).decode("utf-8", errors="replace")
    except OSError:
        return None
    match = _CLASS_RE.search(head)
    return match.group(1) if match else None


def available_fields(case_dir: Path, time: str | None = None) -> list[FieldSpec]:
    """The FieldSpecs whose source is a volume field in the given (default: latest) time directory:
    scalars for scalar specs, vectors for magnitudes and components."""
    time = time if time is not None else latest_result_time(case_dir)
    if time is None:
        return []
    folder = Path(case_dir) / time
    classes = {spec.source: field_class(folder / spec.source) for spec in FIELD_SPECS}
    out = []
    for spec in FIELD_SPECS:
        if classes[spec.source] == spec.field_class:
            out.append(spec)
    return out


def pressure_coefficient(p, u_ref: float):
    """Cp = p / (0.5 U_ref^2) for kinematic pressure p (incompressible OpenFOAM), p_ref = 0."""
    if u_ref <= 0:
        raise ValueError("U_ref must be positive")
    return np.asarray(p, dtype=float) / (0.5 * u_ref * u_ref)


def field_values(spec: FieldSpec, data: dict, u_ref: float, direction=(1.0, 0.0, 0.0)):
    """The values of ``spec`` from the arrays read from the case (``data``: source name -> array,
    vectors as (n, 3)); ``direction`` is the free-stream direction (for Cf_x)."""
    from vortexcfd.foam.wall_fields import skin_friction, skin_friction_along

    raw = np.asarray(data[spec.source], dtype=float)
    if spec.key in ("Cp", "CpMean"):
        return pressure_coefficient(raw, u_ref)
    if spec.rms:  # a mean squared fluctuation: its root (never negative but for round-off)
        square = raw[:, spec.component] if spec.component is not None else raw
        return np.sqrt(np.clip(square, 0.0, None))
    if spec.key == "Cf":
        return skin_friction(raw, u_ref)
    if spec.key == "Cf_x":
        return skin_friction_along(raw, direction, u_ref)
    if spec.magnitude:
        return np.linalg.norm(raw, axis=1)
    if spec.component is not None:
        return raw[:, spec.component]
    return raw
