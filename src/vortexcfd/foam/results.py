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
        cls = classes[spec.source]
        vector_spec = spec.component is not None or spec.magnitude
        if cls == ("volVectorField" if vector_spec else "volScalarField"):
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
    if spec.key == "Cp":
        return pressure_coefficient(raw, u_ref)
    if spec.key == "Cf":
        return skin_friction(raw, u_ref)
    if spec.key == "Cf_x":
        return skin_friction_along(raw, direction, u_ref)
    if spec.magnitude:
        return np.linalg.norm(raw, axis=1)
    if spec.component is not None:
        return raw[:, spec.component]
    return raw
