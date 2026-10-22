"""NASA TMR 2D backward-facing step (task w3-internal, Part C; docs/validation/bfs/SETUP.md) as an internal-flow
project of the app: the "2D internal flow" preset (wall-resolved y+ 1, two turbulence stages), the TMR channel in
the x-z plane with H = 1 m.

TMR (https://tmbwg.github.io/turbmodels/backstep_val.html and its grids, backstep5_*levdn.p2dfmt): free-stream inflow
at x/H = -130, a symmetry strip on both sides up to x/H = -110 where both walls start, the upstream channel between
z/H = 1 and 9, the step at x = 0 down to z = 0, the outlet at x/H = 50 with a back pressure; Re_H about 36,000 with
the centre-channel velocity near x/H = -4 as U_ref; M = 0.128. Here (incompressible, the app has no symmetry role):
a uniform velocity inlet at x/H = -110, where TMR's walls start, so the walls develop over the same length; nu =
U_ref H / 36,000 with U_ref = 1 m/s; the inlet speed is set so the centre-channel velocity at x/H = -4 is about U_ref
(the boundary layers' displacement accelerates the core), and the run's own U_ref and Re_H are reported.
"""

from pathlib import Path

from vortexcfd.bench.internal_geometries import extruded_outline_solids, write_solids
from vortexcfd.core.model import MeanStableCriterion, Probe, Simulation, StoppingCriteria
from vortexcfd.core.presets import BUILTIN_PRESETS, apply_preset
from vortexcfd.core.project import Project
from vortexcfd.geometry.loader import stl_solid_names
from vortexcfd.workflow import part_ops

H = 1.0  # m, the step height
X_INLET, X_OUTLET, Z_TOP = -110.0, 50.0, 9.0
RE_H = 36_000.0
U_REF = 1.0  # m/s, the target centre-channel velocity at x/H = -4
NU = U_REF * H / RE_H
RHO = 1.0
# The core speeds up by the walls' displacement thickness between the inlet and x/H = -4 (a first run's ratio
# U_ref / U_inlet; the run reports its own U_ref).
INLET_SPEED = 0.95
# TMR's inflow turbulence (CFL3D and FUN3D, SSTm page): intensity 0.061 %, nut / nu 0.009. With the inlet's mixing
# length condition nut = k^0.5 Cmu^0.25 L, so L = 0.009 nu / (k^0.5 Cmu^0.25) with k = 1.5 (I U)^2.
INLET_INTENSITY = 0.00061
INLET_LENGTH = 0.009 * NU / ((1.5 * (INLET_INTENSITY * INLET_SPEED) ** 2) ** 0.5 * 0.09 ** 0.25)
# The outline (x, z) and the patch of each segment (segment i from point i to point i + 1).
def outline(x_inlet: float = X_INLET) -> list[tuple[float, float]]:
    return [(x_inlet, 1.0), (0.0, 1.0), (0.0, 0.0), (X_OUTLET, 0.0), (X_OUTLET, Z_TOP), (x_inlet, Z_TOP)]


OUTLINE = outline()
# Round 2 (QUESTIONS 209): TMR adjusts "the inflow length ... so that the naturally developing turbulent boundary layer
# on the lower wall ... grows to approximately the correct thickness", about 1.5 H before the step; here the walls start
# at the inlet, moved upstream until delta_99 at x/H = -4 is 1.5 H (calibrated on the 0.129 H mesh, RESULT.md).
X_INLET_ROUND2 = -131.0  # delta_99 1.501 H at x/H = -4 (-123: 1.423 H)
SEGMENTS = ["lower", "step", "floor", "outlet", "upper", "inlet"]
SPAN = 1.0  # the extrusion of the geometry along y (the 2D mode cuts it at mid y)
# Probes: U_ref at the centre of the channel at x/H = -4; the near-wall velocity at x/H = 6 (inside the bubble's end).
REF_PROBE = ("uref", (-4.0, 0.0, 5.0))
REATTACH_PROBE = ("reatt", (6.0, 0.0, 0.05))
ITERATIONS = 12_000
CORES = 8
EXPERIMENT_XR = 6.26  # x/H, Driver & Seegmiller (TMR: 6.26 +- 0.10)
TMR_SST_XR = 6.50  # x/H, "Reattachment is predicted by the SSTm model near x/H = 6.50" (TMR SSTm page)


def stopping() -> StoppingCriteria:
    """Mean-stable (D-118) total pressure loss and near-wall velocity at x/H = 6 over two windows of 500 iterations
    (relative change 0.5 %), after 2,000 iterations. TMR: "the SSTm model does not converge readily to a steady-state
    result" on its fine grids. [NUMERICS-REVIEW: the validation's choice]"""
    return StoppingCriteria(criteria=[
        MeanStableCriterion(quantity="dp:loss:total", window=500, tolerance=0.005, floor=1e-3),
        MeanStableCriterion(quantity=f"probe:{REATTACH_PROBE[0]}:U", window=500, tolerance=0.005, floor=0.01),
    ], combine="all", min_iterations=2000)


# The preset's background target, and the finer family's (task w3-internal, Part C: the first study's levels moved the
# reattachment by about 0.4 H each; the finer family's current settings are the first one's fine level halved in
# area per cell, its levels 0.129 / 0.091 / 0.064 H).
FINE_FAMILY = {"background_cells_target": 160_000, "current_as": "medium"}
# Round 2: the same cells with the longer channel: the medium level's base cell set explicitly (round 1's 0.09117 H).
FINE_FAMILY_ROUND2 = {"base_size": 0.09117, "current_as": "medium"}


def build_project(folder: Path, family: dict | None = None, x_inlet: float = X_INLET) -> Project:
    """The BFS project in ``folder``/bfs (created); ``family``: FINE_FAMILY for the finer mesh study (None: the
    preset's settings, the study's current settings placed by D-128)."""
    folder.mkdir(parents=True, exist_ok=True)
    preset = next(p for p in BUILTIN_PRESETS if p.name == "2D internal flow")
    project = Project.create(folder, "bfs", apply_preset(Simulation(name="bfs"), preset))
    stl = write_solids(project.folder / "geometry" / "bfs.stl",
                       extruded_outline_solids(outline(x_inlet), SEGMENTS, -SPAN / 2, SPAN / 2, "lower"))
    project.add_part(part_ops.with_region_patches(
        part_ops.part_with_solid_regions(project.folder, "bfs", stl, "m", stl_solid_names(stl))))
    project.update_physics(nu=NU, rho_ref=RHO)
    project.update_boundary("inlet", role="inlet", inlet={"kind": "velocity", "speed": INLET_SPEED,
                                                          "turbulence_intensity": INLET_INTENSITY,
                                                          "length_scale": INLET_LENGTH})
    project.update_boundary("outlet", role="outlet", outlet={"pressure": 0.0})
    probes = [Probe(name=n, location=loc) for n, loc in (REF_PROBE, REATTACH_PROBE)]
    project.update_reports(probes=[p.model_dump() for p in probes],
                           pressure_drops=[{"name": "loss", "upstream": "patch:inlet", "downstream": "patch:outlet"}],
                           slots=[f"probe:{REATTACH_PROBE[0]}:Ux", "dp:loss:total", f"probe:{REF_PROBE[0]}:Ux"])
    project.update_solver(iterations=ITERATIONS, write_interval=ITERATIONS, cores=CORES, stopping=stopping())
    project.update_study("mesh", quantities=["dp:loss:total", f"probe:{REATTACH_PROBE[0]}:Ux"], cores=CORES)
    if family is not None:
        project.update_mesh(**{k: v for k, v in family.items() if k != "current_as"})
        if "current_as" in family:
            project.update_study("mesh", current_as=family["current_as"])
    project.save()
    return project


def verdict(xr: float, sst_consistent: bool) -> str:
    """I5: PASS within 10 % of the experiment; PASS WITH NOTE 10-20 % if consistent with the TMR SST codes; FAIL
    beyond."""
    error = abs(xr / EXPERIMENT_XR - 1.0)
    if error <= 0.10:
        return "PASS"
    if error <= 0.20 and sst_consistent:
        return "PASS WITH NOTE"
    return "FAIL"
