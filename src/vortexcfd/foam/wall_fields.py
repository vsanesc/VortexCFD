"""Wall fields written at write times: skin friction from wallShearStress and the y+ distribution
(no Qt, no pyvista). [NUMERICS-REVIEW] (D-061)

wallShearStress (src/functionObjects/field/wallShearStress, v2606) writes, on the wall patches,
tau = n_in . devReff with n_in the patch normal pointing INTO the domain (``-Sf/|Sf|``) and devReff
the kinematic effective stress (m2/s2, incompressible). That is the stress the wall exerts on the
fluid: on a wall with attached flow along +x its x component is negative. The skin friction on the
body is the opposite vector, so

    Cf   = |tau| / (0.5 U_ref^2)
    Cf_x = -(tau . d) / (0.5 U_ref^2)      d = the free-stream direction (cos a, 0, sin a)

Cf_x > 0 where the near-wall flow goes downstream, < 0 where it runs back (separated or
recirculating flow).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vortexcfd.foam.dictfile import read_foam_file

# y+ bins of the wall faces: [0, 1), [1, 5), [5, 30), [30, 300), [300, inf).
YPLUS_EDGES = (0.0, 1.0, 5.0, 30.0, 300.0)
YPLUS_LABELS = ("0-1", "1-5", "5-30", "30-300", "> 300")


def skin_friction(tau, u_ref: float):
    """Cf = |tau| / (0.5 U_ref^2) of kinematic wall shear stress vectors (n, 3)."""
    if u_ref <= 0:
        raise ValueError("U_ref must be positive")
    return np.linalg.norm(np.asarray(tau, dtype=float), axis=1) / (0.5 * u_ref * u_ref)


def skin_friction_along(tau, direction, u_ref: float):
    """Cf_x = -(tau . d) / (0.5 U_ref^2): the body's skin friction along the free-stream direction
    d (unit vector), with sign (negative where the near-wall flow runs upstream)."""
    if u_ref <= 0:
        raise ValueError("U_ref must be positive")
    d = np.asarray(direction, dtype=float)
    d = d / np.linalg.norm(d)
    return -(np.asarray(tau, dtype=float) @ d) / (0.5 * u_ref * u_ref)


@dataclass(frozen=True)
class YPlusHistogram:
    """Fraction of wall faces per y+ bin (YPLUS_LABELS), and the face count."""

    fractions: tuple[float, ...]
    faces: int


def yplus_histogram(values: Iterable[float]) -> YPlusHistogram:
    """Face counts per bin divided by the number of faces: [0, 1), [1, 5), [5, 30), [30, 300),
    [300, inf). A face exactly on an edge goes to the upper bin; negative or non-finite values (none
    are expected) are left out."""
    v = np.asarray(list(values) if not isinstance(values, np.ndarray) else values, dtype=float)
    v = v[np.isfinite(v) & (v >= 0)]
    if v.size == 0:
        return YPlusHistogram(tuple(0.0 for _ in YPLUS_LABELS), 0)
    idx = np.searchsorted(np.asarray(YPLUS_EDGES[1:]), v, side="right")
    counts = np.bincount(idx, minlength=len(YPLUS_LABELS))
    return YPlusHistogram(tuple(float(c) / v.size for c in counts), int(v.size))


def wall_face_values(field_file: Path, patches: Iterable[str]) -> dict[str, np.ndarray]:
    """The boundary values of a field file on the given patches: patch -> array (n,) or (n, 3).
    A patch missing from the file or without a ``value`` entry is left out."""
    data = read_foam_file(field_file)
    boundary = data.get("boundaryField", {}) if isinstance(data, Mapping) else {}
    out: dict[str, np.ndarray] = {}
    for name in patches:
        entry = boundary.get(name) if isinstance(boundary, Mapping) else None
        if not isinstance(entry, Mapping) or "value" not in entry:
            continue
        out[name] = np.atleast_1d(np.asarray(entry["value"], dtype=float))
    return out


def case_yplus_histogram(case_dir: Path, patches: Iterable[str]) -> tuple[str, YPlusHistogram] | None:
    """(time, histogram) of the y+ field on the wall patches at the latest result time, or None when
    no yPlus field was written."""
    from vortexcfd.foam.results import latest_result_time

    time = latest_result_time(case_dir)
    if time is None:
        return None
    path = Path(case_dir) / time / "yPlus"
    if not path.is_file():
        return None
    values = wall_face_values(path, patches)
    if not values:
        return None
    return time, yplus_histogram(np.concatenate([v.ravel() for v in values.values()]))
