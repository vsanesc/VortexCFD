"""Report ids: what a report slot can show and what an asymptotic criterion can watch (D-060).

Grammar (plain strings, stored in the project):

- force coefficients of all walls, from forceCoeffs: ``Cd``, ``Cl``, ``CmPitch``;
- their pressure and viscous parts and the centre of pressure, from the forces function object:
  ``Cd_pressure``, ``Cd_viscous``, ``Cl_pressure``, ``Cl_viscous``, ``x_cp``;
- the same for one part's wall patch (only with several parts): ``<base>@<patch>``;
- ``mass_imbalance`` (percent of the inlet flux);
- ``yplus_min``, ``yplus_avg``, ``yplus_max`` (walls, at write times);
- probes: ``probe:<name>:<p|Ux|Uy|Uz|Umag>``.

Asymptotic criteria accept the coefficients (all walls or one part, not x_cp) and ``probe:<name>:p``
or ``probe:<name>:U`` (the velocity vector: the change is the length of the vector difference).
"""

import re
from collections.abc import Iterable

FORCE_COEFFS = ("Cd", "Cl", "CmPitch")
BREAKDOWN = ("Cd_pressure", "Cd_viscous", "Cl_pressure", "Cl_viscous")
PART_BASES = FORCE_COEFFS + BREAKDOWN + ("x_cp",)
YPLUS = ("yplus_min", "yplus_avg", "yplus_max")
MASS = "mass_imbalance"
PROBE_COMPONENTS = ("p", "Ux", "Uy", "Uz", "Umag")
PROBE_CRITERION_COMPONENTS = ("p", "U")
PROBE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_PROBE_ID_RE = re.compile(r"^probe:([A-Za-z][A-Za-z0-9_]{0,31}):(\w+)$")

BASE_LABELS = {
    "Cd": "Cd", "Cl": "Cl", "CmPitch": "Cm (pitch)",
    "Cd_pressure": "Cd pressure", "Cd_viscous": "Cd viscous",
    "Cl_pressure": "Cl pressure", "Cl_viscous": "Cl viscous", "x_cp": "x_cp (m)",
    "yplus_min": "y+ min (walls)", "yplus_avg": "y+ avg (walls)", "yplus_max": "y+ max (walls)",
    MASS: "Mass imbalance (%)",
}


def split_part(report_id: str) -> tuple[str, str | None]:
    """("Cd", "Ball") for "Cd@Ball", (id, None) without a part."""
    base, sep, patch = report_id.partition("@")
    return (base, patch) if sep else (report_id, None)


def split_probe(report_id: str) -> tuple[str, str] | None:
    """(name, component) of a probe id, or None."""
    m = _PROBE_ID_RE.match(report_id)
    return (m.group(1), m.group(2)) if m else None


def is_report_id(report_id: str) -> bool:
    """Syntactically valid report id (the part or probe may no longer exist)."""
    if report_id in FORCE_COEFFS + BREAKDOWN + ("x_cp",) + YPLUS + (MASS,):
        return True
    base, patch = split_part(report_id)
    if patch is not None:
        return base in PART_BASES and bool(patch)
    probe = split_probe(report_id)
    return probe is not None and probe[1] in PROBE_COMPONENTS


def is_criterion_quantity(quantity: str) -> bool:
    base, patch = split_part(quantity)
    if base in FORCE_COEFFS + BREAKDOWN:
        return patch is None or bool(patch)
    probe = split_probe(quantity)
    return probe is not None and probe[1] in PROBE_CRITERION_COMPONENTS


# Scale floor of the relative range (max - min) / max(|mean|, floor) for force and moment
# coefficients: a coefficient whose mean is near zero (Cl of a symmetric body) is judged against
# 0.01 instead (D-058, D-059). Probes have no natural scale: their floor is set by the user.
COEFFICIENT_FLOOR = 0.01


def default_floor(quantity: str) -> float | None:
    """The floor of the relative range for ``quantity``: COEFFICIENT_FLOOR for a force or moment
    coefficient (all walls or one part), None for anything else (no natural scale)."""
    base, _patch = split_part(quantity)
    return COEFFICIENT_FLOOR if base in FORCE_COEFFS + BREAKDOWN else None


def report_label(report_id: str) -> str:
    base, patch = split_part(report_id)
    if patch is not None:
        return f"{BASE_LABELS.get(base, base)} ({patch})"
    probe = split_probe(report_id)
    if probe is not None:
        comp = {"Umag": "|U|", "U": "U"}.get(probe[1], probe[1])
        return f"Probe {probe[0]} {comp}"
    return BASE_LABELS.get(report_id, report_id)


def available_reports(patches: Iterable[str], probes: Iterable[str]) -> list[str]:
    """The ids a report slot can be assigned, for the parts' patches and the probe names (per-part
    reports only with several parts: with one part they equal the totals)."""
    patches = list(patches)
    ids = [*FORCE_COEFFS, *BREAKDOWN, "x_cp"]
    if len(patches) > 1:
        ids += [f"{b}@{p}" for p in patches for b in PART_BASES]
    ids += [MASS, *YPLUS]
    ids += [f"probe:{n}:{c}" for n in probes for c in PROBE_COMPONENTS]
    return ids


def criterion_quantities(patches: Iterable[str], probes: Iterable[str]) -> list[str]:
    patches = list(patches)
    ids = [*FORCE_COEFFS, *BREAKDOWN]
    if len(patches) > 1:
        ids += [f"{b}@{p}" for p in patches for b in FORCE_COEFFS + BREAKDOWN]
    ids += [f"probe:{n}:{c}" for n in probes for c in PROBE_CRITERION_COMPONENTS]
    return ids


def missing_reference(report_id: str, patches: Iterable[str], probes: Iterable[str]) -> str | None:
    """Why ``report_id`` cannot be computed for this project (a removed part or probe), or None."""
    patches = list(patches)
    _base, patch = split_part(report_id)
    if patch is not None:
        if patch not in patches:
            return f"no part patch {patch!r}"
        if len(patches) < 2:
            return "per-part reports need several parts"
    probe = split_probe(report_id)
    if probe is not None and probe[0] not in set(probes):
        return f"no probe {probe[0]!r}"
    return None
