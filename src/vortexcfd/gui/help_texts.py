"""The properties panel's help (D-148): the manual section each section header's "?" opens.

Anchors are the headings of docs/manual/09_properties_reference.md (GitHub-style: lower case, spaces as "-").
"""

PROPERTIES_CHAPTER = "09_properties_reference.md"

# section key (PropertiesPanel._section) -> anchor in PROPERTIES_CHAPTER
SECTION_HELP: dict[str, str] = {
    "mesh_sizing": "mesh-sizing",
    "mesh_refinement": "surface-refinement-and-curvature",
    "mesh_layers": "prism-layers",
    "mesh_parallel": "parallel-meshing",
    "mesh_estimate": "the-cell-estimate",
    "inflow_computed": "free-stream",
    "free_stream": "free-stream",
    "body_attitude": "body-attitude",
    "dom_size": "domain-size",
    "dom_symmetry": "domain-size",
    "dom_computed": "domain-size",
    "dom_ground": "ground-plane",
    "boundary": "domain-boundaries",
    "sp_title": "surface-preparation",
    "vol_list": "refinement-volumes",
    "vol_edit": "refinement-volumes",
    "ref_used": "reference-values",
    "stop_criteria": "stopping-criteria",
    "ms_title": "mesh-independence-study",
    "ms_estimate": "mesh-independence-study",
    "ps_title": "polar-sweep",
    "probes": "probes",
    "checks": "part-checks",
    "regions": "part-regions",
}


def help_target(key: str) -> str | None:
    """"<chapter>#<anchor>" of a section, or None (no "?")."""
    anchor = SECTION_HELP.get(key)
    return f"{PROPERTIES_CHAPTER}#{anchor}" if anchor else None
