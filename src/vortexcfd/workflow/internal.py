"""Internal-flow orchestration (D-129, Qt-free): the patches and their roles, the inlets' hydraulic diameters, the
reference inlet that sizes the surface cells and the y+ layers, and the point inside the fluid.

The fluid is the inside of the imported closed geometry; every surface patch (a region's patch or a part's own,
Part.patch_names()) is an inlet, an outlet or a wall (Simulation.boundaries; a patch without an entry is a wall).
"""

import dataclasses
import math
from dataclasses import dataclass

import numpy as np

from vortexcfd.core.model import LENGTH_SCALE_OF_DH, InletSpec
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_case import LOCATION_OFFSET, MeshCaseInput, part_patch_names
from vortexcfd.geometry import internal as geom


@dataclass(frozen=True)
class InternalPatch:
    """One surface patch of an internal-flow project: its model name (Simulation.boundaries' key), its mesh
    (safe) name, its part and its index among the part's patches, and its role."""

    name: str
    safe: str
    part: int
    index: int
    role: str


def patches(project: Project) -> list[InternalPatch]:
    """Every surface patch of the project in part and region order, with its role."""
    sim = project.sim
    out = []
    for i, (part, safe_names) in enumerate(zip(sim.geometry.parts, part_patch_names(sim.geometry.parts, internal=True))):
        for k, (name, safe) in enumerate(zip(part.patch_names(), safe_names)):
            out.append(InternalPatch(name, safe, i, k, sim.boundary(name).role))
    return out


def open_patches(project: Project) -> tuple[tuple[str, str], ...]:
    """(mesh patch name, role) of every inlet and outlet (MeshCaseInput.open_patches)."""
    return tuple((p.safe, p.role) for p in patches(project) if p.role != "wall")


def wall_patches(project: Project) -> tuple[str, ...]:
    return tuple(p.safe for p in patches(project) if p.role == "wall")


def role_problem(project: Project) -> str | None:
    """Why the roles do not make an internal flow (no inlet or no outlet; a total-pressure inlet needs a static
    outlet, which every outlet is), or None."""
    roles = [p.role for p in patches(project)]
    if "inlet" not in roles:
        return "Set at least one patch as an inlet (Boundaries)."
    if "outlet" not in roles:
        return "Set at least one patch as an outlet (Boundaries)."
    return None


def _patch_labels(project: Project, index: int, mesh) -> np.ndarray:
    from vortexcfd.workflow.meshing import part_patch_labels  # meshing imports this module

    return part_patch_labels(project, index, mesh)


@dataclass(frozen=True)
class InletMeasures:
    """An inlet patch's area (m2) and hydraulic diameter (m) from the parts' surfaces (in 2D: the area per the
    surface's span and D_h = 2 x its width, geometry/internal.patch_measures)."""

    area: float
    hydraulic_diameter: float


def inlet_measures(project: Project, meshes) -> dict[str, InletMeasures]:
    """The measures of every inlet, by mesh patch name. ``meshes``: the parts' loaded surfaces (metres)."""
    two_d = project.sim.dimension == "2d"
    out = {}
    for p in patches(project):
        if p.role != "inlet":
            continue
        labels = _patch_labels(project, p.part, meshes[p.part])
        area, _perimeter, dh = geom.patch_measures(meshes[p.part], labels, p.index, two_d)
        out[p.safe] = InletMeasures(area, dh)
    return out


def bulk_speed(spec: InletSpec, area: float, rho: float, outlet_pressure: float) -> float | None:
    """The inlet's bulk speed estimate (m/s) for the y+ layers and the initial turbulence: the velocity inlet's
    speed; the mass flow over rho A; for a total-pressure inlet the ideal sqrt(2 (p0 - p_out) / rho) with the
    lowest outlet pressure (an upper bound: losses lower it, so the first layer is on the thin side). None when it
    cannot be estimated (a zero area, or p0 not above the outlet). [NUMERICS-REVIEW]"""
    if spec.kind == "velocity":
        return spec.speed
    if spec.kind == "mass_flow":
        return spec.mass_flow / (rho * area) if area > 0 else None
    head = spec.total_pressure - outlet_pressure
    return math.sqrt(2.0 * head / rho) if head > 0 else None


@dataclass(frozen=True)
class ReferenceInlet:
    """The first inlet (in patch order): it sets the internal surface length (its D_h) and the y+ speed."""

    patch: str  # mesh patch name
    hydraulic_diameter: float
    speed: float | None
    area: float


def reference_inlet(project: Project, meshes) -> ReferenceInlet | None:
    """The reference inlet, or None without an inlet."""
    sim = project.sim
    measures = inlet_measures(project, meshes)
    outlets = [sim.boundary(p.name).outlet.pressure for p in patches(project) if p.role == "outlet"]
    for p in patches(project):
        if p.role == "inlet":
            m = measures[p.safe]
            speed = bulk_speed(sim.boundary(p.name).inlet, m.area, sim.physics.rho_ref, min(outlets, default=0.0))
            return ReferenceInlet(p.safe, m.hydraulic_diameter, speed, m.area)
    return None


def length_scale(spec: InletSpec, hydraulic_diameter: float) -> float:
    """The inlet's turbulence length scale (m): the set value, else LENGTH_SCALE_OF_DH x D_h (I2). [NUMERICS-REVIEW]"""
    return spec.length_scale if spec.length_scale is not None else LENGTH_SCALE_OF_DH * hydraulic_diameter


def with_location(inputs: MeshCaseInput, meshes) -> MeshCaseInput:
    """``inputs`` with the locationInMesh inside the closed geometry (D-129) for its own background grid.

    Raises:
        ValueError: no point of the background grid is inside the geometry.
    """
    est = inputs.estimate()
    point = geom.inside_point(meshes, est.background_bounds, est.cells, LOCATION_OFFSET)
    if point is None:
        raise ValueError("no point of the background mesh lies inside the geometry: refine the background "
                         "(Mesh > base size) or check that the geometry is closed")
    return dataclasses.replace(inputs, location=point)
