"""Report ids: what a report slot can show and what an asymptotic criterion can watch (D-060).

Grammar (plain strings, stored in the project):

- force coefficients of all walls, from forceCoeffs: ``Cd``, ``Cl``, ``CmPitch``;
- their pressure and viscous parts, the body-axis axial and normal coefficients and the centre of
  pressure, from the forces function object: ``Cd_pressure``, ``Cd_viscous``, ``Cl_pressure``,
  ``Cl_viscous``, ``C_axial``, ``C_normal``, ``x_cp`` (D-060, D-120);
- the same for one part's wall patch (only with several parts): ``<base>@<patch>``;
- ``mass_imbalance`` (percent of the inlet flux);
- ``yplus_min``, ``yplus_avg``, ``yplus_max`` (walls, at write times);
- probes: ``probe:<name>:<p|Ux|Uy|Uz|Umag>``;
- internal flow (D-129): ``flow:<quantity>:<patch|plane>:<name>`` with the quantity ``mdot`` (mass flow rate in kg/s,
  positive out of the domain on a patch, along the normal on a plane), ``p_area`` / ``p_mass`` (area- and
  mass-averaged static pressure, Pa) or ``p0_area`` / ``p0_mass`` (total pressure, Pa); a pressure drop
  ``dp:<name>:<static|total>`` (mass-averaged upstream minus downstream, Pa).

Asymptotic criteria accept the coefficients (all walls or one part, not x_cp), ``probe:<name>:p``
or ``probe:<name>:U`` (the velocity vector: the change is the length of the vector difference) and the internal-flow
quantities (no default floor: it is set in their units).
"""

import re
from collections.abc import Iterable

FORCE_COEFFS = ("Cd", "Cl", "CmPitch")
# C_axial and C_normal: the force coefficients along the parts' own x and z axes at the angle of attack
# (body axes, D-120).
BREAKDOWN = ("Cd_pressure", "Cd_viscous", "Cl_pressure", "Cl_viscous", "C_axial", "C_normal")
PART_BASES = FORCE_COEFFS + BREAKDOWN + ("x_cp",)
YPLUS = ("yplus_min", "yplus_avg", "yplus_max")
MASS = "mass_imbalance"
PROBE_COMPONENTS = ("p", "Ux", "Uy", "Uz", "Umag")
PROBE_CRITERION_COMPONENTS = ("p", "U")
PROBE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_PROBE_ID_RE = re.compile(r"^probe:([A-Za-z][A-Za-z0-9_]{0,31}):(\w+)$")
# Internal flow (D-129).
FLOW_QUANTITIES = ("mdot", "p_area", "p_mass", "p0_area", "p0_mass")
FLOW_QUANTITY_LABELS = {"mdot": "Mass flow (kg/s)", "p_area": "p area-avg (Pa)", "p_mass": "p mass-avg (Pa)",
                        "p0_area": "p0 area-avg (Pa)", "p0_mass": "p0 mass-avg (Pa)"}
DROP_KINDS = ("static", "total")
_FLOW_ID_RE = re.compile(r"^flow:(\w+):(patch|plane):(.+)$")
_DROP_ID_RE = re.compile(r"^dp:([A-Za-z][A-Za-z0-9_]{0,31}):(static|total)$")

BASE_LABELS = {
    "Cd": "Cd", "Cl": "Cl", "CmPitch": "Cm (pitch)",
    "Cd_pressure": "Cd pressure", "Cd_viscous": "Cd viscous",
    "Cl_pressure": "Cl pressure", "Cl_viscous": "Cl viscous", "x_cp": "x_cp (m)",
    "C_axial": "C_A (body axial)", "C_normal": "C_N (body normal)",
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


def split_flow(report_id: str) -> tuple[str, str, str] | None:
    """(quantity, "patch" or "plane", name) of an internal-flow id, or None."""
    m = _FLOW_ID_RE.match(report_id)
    return (m.group(1), m.group(2), m.group(3)) if m and m.group(1) in FLOW_QUANTITIES else None


def split_drop(report_id: str) -> tuple[str, str] | None:
    """(pressure-drop name, "static" or "total") of a pressure-drop id, or None."""
    m = _DROP_ID_RE.match(report_id)
    return (m.group(1), m.group(2)) if m else None


def flow_id(quantity: str, location: str) -> str:
    """The id of ``quantity`` at ``location`` ("patch:<name>" or "plane:<name>")."""
    return f"flow:{quantity}:{location}"


def is_report_id(report_id: str) -> bool:
    """Syntactically valid report id (the part or probe may no longer exist)."""
    if report_id in FORCE_COEFFS + BREAKDOWN + ("x_cp",) + YPLUS + (MASS,):
        return True
    if split_flow(report_id) is not None or split_drop(report_id) is not None:
        return True
    base, patch = split_part(report_id)
    if patch is not None:
        return base in PART_BASES and bool(patch)
    probe = split_probe(report_id)
    return probe is not None and probe[1] in PROBE_COMPONENTS


def is_criterion_quantity(quantity: str) -> bool:
    if split_flow(quantity) is not None or split_drop(quantity) is not None:
        return True
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


def report_unit(report_id: str) -> str:
    """The unit of a report's values ("" for a coefficient or y+; D-166): probes in the solver's kinematic units."""
    flow = split_flow(report_id)
    if flow is not None:
        return "kg/s" if flow[0] == "mdot" else "Pa"
    if split_drop(report_id) is not None:
        return "Pa"
    probe = split_probe(report_id)
    if probe is not None:
        return "m\u00b2/s\u00b2" if probe[1] == "p" else "m/s"
    base, _patch = split_part(report_id)
    return {"x_cp": "m", MASS: "%"}.get(base, "")


def report_label(report_id: str) -> str:
    flow = split_flow(report_id)
    if flow is not None:
        return f"{FLOW_QUANTITY_LABELS[flow[0]]} {flow[1]} {flow[2]}"
    drop = split_drop(report_id)
    if drop is not None:
        return f"dp {drop[1]} {drop[0]} (Pa)"
    base, patch = split_part(report_id)
    if patch is not None:
        return f"{BASE_LABELS.get(base, base)} ({patch})"
    probe = split_probe(report_id)
    if probe is not None:
        comp = {"Umag": "|U|", "U": "U"}.get(probe[1], probe[1])
        return f"Probe {probe[0]} {comp}"
    return BASE_LABELS.get(report_id, report_id)


def available_reports(patches: Iterable[str], probes: Iterable[str], locations: Iterable[str] = (),
                      drops: Iterable[str] = (), internal: bool = False) -> list[str]:
    """The ids a report slot can be assigned, for the parts' patches and the probe names (per-part
    reports only with several parts: with one part they equal the totals). Internal flow (D-129): no force
    reports; the flow quantities of every ``locations`` entry ("patch:<inlet or outlet>", "plane:<name>") and
    both kinds of every pressure drop in ``drops``."""
    patches = list(patches)
    ids = [] if internal else [*FORCE_COEFFS, *BREAKDOWN, "x_cp"]
    if len(patches) > 1 and not internal:
        ids += [f"{b}@{p}" for p in patches for b in PART_BASES]
    ids += [MASS, *YPLUS]
    ids += [flow_id(q, loc) for loc in locations for q in FLOW_QUANTITIES]
    ids += [f"dp:{d}:{k}" for d in drops for k in DROP_KINDS]
    ids += [f"probe:{n}:{c}" for n in probes for c in PROBE_COMPONENTS]
    return ids


def criterion_quantities(patches: Iterable[str], probes: Iterable[str], locations: Iterable[str] = (),
                         drops: Iterable[str] = (), internal: bool = False) -> list[str]:
    patches = list(patches)
    ids = [] if internal else [*FORCE_COEFFS, *BREAKDOWN]
    if len(patches) > 1 and not internal:
        ids += [f"{b}@{p}" for p in patches for b in FORCE_COEFFS + BREAKDOWN]
    ids += [flow_id(q, loc) for loc in locations for q in FLOW_QUANTITIES]
    ids += [f"dp:{d}:{k}" for d in drops for k in DROP_KINDS]
    ids += [f"probe:{n}:{c}" for n in probes for c in PROBE_CRITERION_COMPONENTS]
    return ids


def missing_reference(report_id: str, patches: Iterable[str], probes: Iterable[str], locations: Iterable[str] = (),
                      drops: Iterable[str] = (), internal: bool = False) -> str | None:
    """Why ``report_id`` cannot be computed for this project (a removed part, probe, inlet / outlet, plane or
    pressure drop, or a force report in an internal-flow project), or None."""
    flow = split_flow(report_id)
    if flow is not None:
        location = f"{flow[1]}:{flow[2]}"
        return None if location in set(locations) else f"no inlet, outlet or plane {flow[2]!r}"
    drop = split_drop(report_id)
    if drop is not None:
        return None if drop[0] in set(drops) else f"no pressure drop {drop[0]!r}"
    patches = list(patches)
    base, patch = split_part(report_id)
    if internal and base in PART_BASES:
        return "an internal-flow analysis has no force reports"
    if patch is not None:
        if patch not in patches:
            return f"no part patch {patch!r}"
        if len(patches) < 2:
            return "per-part reports need several parts"
    probe = split_probe(report_id)
    if probe is not None and probe[0] not in set(probes):
        return f"no probe {probe[0]!r}"
    return None
