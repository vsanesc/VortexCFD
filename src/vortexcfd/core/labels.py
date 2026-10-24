"""Readable labels of the model's choice values and of the set-up summary's entries (D-166).

The user never sees an internal identifier: "incompressible_steady" is "Incompressible, steady", "kOmegaSST" is
"k-ω SST". The model and the files keep the identifiers; the properties panel, the report and the snapshot comparisons
show these labels. Qt-free (core/).
"""

from vortexcfd.core.model import BOUNDARY_KIND_LABELS, DIMENSION_LABELS

# Model field -> {value: label}. A field shown with a choice box uses its labels; the set-up summary maps its values.
VALUE_LABELS: dict[str, dict[str, str]] = {
    "flow": {"incompressible_steady": "Incompressible, steady"},
    "turbulence_model": {"kOmegaSST": "k-ω SST"},
    "relaxation": {"robust": "Robust (p 0.3, U 0.7)"},
    "combine": {"all": "All", "any": "Any"},
    "symmetry": {"none": "None", "y_min": "y-min plane"},
    "analysis_type": {"external": "External flow", "empty": "Empty", "internal": "Internal flow"},
    "dimension": dict(DIMENSION_LABELS),
    "surface_size_reference": {"l_ref": "l_ref", "largest_extent": "L (largest extent)"},
    "layer_sizing": {"absolute_yplus": "Sized from a target y+",
                     "relative": "Thickness relative to the surface cell size"},
    "layer_controls": {"robust": "Robust", "wall_resolved": "Wall-resolved", "legacy": "Legacy"},
    "yplus_at": {"cell_centre": "y+ at the first cell centre", "cell_height": "y+ at the first cell height"},
    "reference_area_basis": {"planform": "Planform", "frontal": "Frontal", "custom": "Custom"},
    "shape": {"box": "Box", "bullet": "Bullet", "c_type": "C-type"},
    "motion": {"stationary": "Stationary wall", "moving": "Moving with the free stream"},
    "boundary_type": dict(BOUNDARY_KIND_LABELS),
    "criterion": {"residual": "residual", "asymptotic": "asymptotic", "mean_stable": "mean stable"},
    "role": {"inlet": "Inlet", "outlet": "Outlet", "wall": "Wall"},
    "inlet_kind": {"velocity": "Velocity", "mass_flow": "Mass flow", "total_pressure": "Total pressure"},
    "frame": {"body": "Turns with the body", "wind": "Fixed (wind axes)"},
    "current_as": {"fine": "Fine level", "medium": "Medium level"},
}

# The set-up summary's groups and fields (workflow/snapshots.setup_summary keys "group: field") and their labels with
# units.
GROUP_LABELS = {"physics": "Physics", "free stream": "Free stream", "domain": "Domain", "mesh": "Mesh",
                "solver": "Solver", "reference": "Reference values", "refinement volume": "Refinement volume",
                "boundary": "Boundary"}
FIELD_LABELS: dict[str, str] = {
    "flow": "Flow", "nu": "Kinematic viscosity ν (m²/s)", "rho_ref": "Reference density ρ (kg/m³)",
    "turbulence_model": "Turbulence model", "speed_of_sound": "Speed of sound a (m/s)",
    "speed": "Free-stream speed (m/s)", "alpha_deg": "Angle of attack α (°)",
    "turbulence_intensity": "Turbulence intensity (fraction)", "viscosity_ratio": "Viscosity ratio νₜ/ν",
    "enabled": "Enabled", "shape": "Shape", "upstream": "Upstream", "downstream": "Downstream", "lateral": "Lateral",
    "vertical": "Vertical", "radius": "Radius", "symmetry": "Symmetry", "ground": "Ground plane",
    "background_cells_target": "Background cells", "target_surface_size": "Surface cell size (fraction)",
    "surface_size_reference": "Surface cell size relative to", "curvature_levels": "Curvature levels",
    "base_size": "Background cell size (m)", "surface_level_min": "Surface level min",
    "surface_level_max": "Surface level max", "feature_angle": "Feature angle (°)", "layers": "Prism layers",
    "expansion_ratio": "Layer expansion ratio", "final_layer_thickness": "Final layer thickness (relative)",
    "min_thickness": "Minimum layer thickness (relative)", "layer_sizing": "Layer sizing",
    "target_yplus": "Target y+", "layer_controls": "Layer controls", "yplus_at": "y+ measured", "cores": "Cores",
    "iterations": "Iteration limit", "stopping": "Stopping criteria", "area": "Reference area A_ref",
    "length": "Reference length l_ref", "CofR": "Centre of rotation", "ground prism layers": "Ground prism layers",
}


def value_label(field: str, value) -> str:
    """The label of a model value (the value itself when it has none)."""
    return VALUE_LABELS.get(field, {}).get(str(value), str(value))


def choices(field: str) -> list[tuple[str, str]]:
    """(value, label) pairs of a choice field, for a choice box carrying the model value as its data."""
    return list(VALUE_LABELS[field].items())


def setup_label(key: str) -> str:
    """A set-up summary key ("physics: nu") as the user reads it ("Physics: Kinematic viscosity ν (m²/s)")."""
    group, sep, field = key.partition(": ")
    if not sep:
        return {"analysis": "Analysis", "parts": "Parts"}.get(key, key)
    if field.endswith(" type"):  # a domain face's boundary type ("inlet type")
        return f"{GROUP_LABELS.get(group, group)}: {field.removesuffix(' type')} boundary type"
    if field.endswith(" prism layers"):
        return f"{GROUP_LABELS.get(group, group)}: {field.removesuffix(' prism layers')} prism layers"
    return f"{GROUP_LABELS.get(group, group)}: {FIELD_LABELS.get(field, field)}"


def setup_value(key: str, text: str) -> str:
    """A set-up summary value with its identifiers replaced by their labels ("incompressible_steady" -> ...)."""
    group, _, field = key.partition(": ")
    if key == "analysis":
        kind, _, dim = text.partition(", ")
        return f"{value_label('analysis_type', kind)}, {value_label('dimension', dim)}" if dim else text
    if field.endswith(" type"):
        return value_label("boundary_type", text)
    if field in VALUE_LABELS:
        return value_label(field, text)
    if key == "reference: area" and text.endswith(")"):  # "auto (planform)"
        head, _, basis = text[:-1].rpartition(" (")
        return f"{head} ({value_label('reference_area_basis', basis)})" if head else text
    if key == "solver: stopping":
        return "; ".join(_criterion_text(part) for part in text.split("; "))
    if key == "domain: ground" and text.startswith("on, "):
        return "on, " + value_label("motion", text.removeprefix("on, ")).lower()
    return text


def _criterion_text(part: str) -> str:
    """A stopping summary entry ("mean_stable Cd") as "Cd mean stable"."""
    kind, _, what = part.partition(" ")
    if kind not in VALUE_LABELS["criterion"]:
        return part
    from vortexcfd.core.reports import report_label

    name = what if kind == "residual" else report_label(what)
    return f"{name} {VALUE_LABELS['criterion'][kind]}".strip()
