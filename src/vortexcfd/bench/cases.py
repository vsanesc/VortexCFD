"""Benchmark case definitions (D-081).

Every case starts from the app's defaults: a new Simulation with the built-in "External flow" preset,
as the New simulation dialog creates it. A case lists only what it changes (``mesh``, ``inflow``, ``reports``,
``domain``); ``deviations`` reports every value that differs from those defaults, plus the
benchmark-only settings of the indicative y+ run (fixed iterations, no stopping criteria, cores).

Zones are bands of the wall where layer coverage is reported separately, in metres in the
geometry's own axes (x along the flow, z up), as axis-aligned boxes or as distance bands around
line segments.
"""

from dataclasses import dataclass, field

from vortexcfd.bench import geometries as geo

Box = tuple[float, float, float, float, float, float]  # xmin, xmax, ymin, ymax, zmin, zmax
Segment = tuple[tuple[float, float, float], tuple[float, float, float]]

INF = 1e9
# Fixed iteration count of the indicative y+ run (chosen to keep the full benchmark near 10 minutes).
YPLUS_ITERATIONS = 400


@dataclass(frozen=True)
class Zone:
    """A band of the wall: faces whose centre lies in one of ``boxes`` or within ``width`` of one of
    ``segments``."""

    name: str
    description: str
    boxes: tuple[Box, ...] = ()
    segments: tuple[Segment, ...] = ()
    width: float = 0.0


@dataclass(frozen=True)
class BenchCase:
    name: str
    geometry: str  # key of geometries.GEOMETRIES
    units: str  # units of an STL file (CAD files carry their own)
    # m: normalises surface fidelity (the app's own L is reported too) and is set as the project's l_ref
    # (``reports``), from which the surface cell size follows (D-085)
    reference_length: float
    description: str
    mesh: dict = field(default_factory=dict)  # Mesh fields changed from the preset
    reports: dict = field(default_factory=dict)  # Reports fields changed from the defaults
    inflow: dict = field(default_factory=dict)  # Inflow fields changed from the defaults
    domain: dict = field(default_factory=dict)  # Domain fields changed from the preset
    zones: tuple[Zone, ...] = ()
    iterations: int = YPLUS_ITERATIONS


def _wing_zones() -> tuple[Zone, ...]:
    c, span = geo.WING_CHORD / 1000, geo.WING_SPAN / 1000
    tip = 0.05 * c
    return (
        Zone("trailing_edge", "last 5 % of the chord (x/c >= 0.95), whole span",
             boxes=((0.95 * c, INF, -INF, INF, -INF, INF),)),
        Zone("tips", f"faces within {tip:g} m (5 % of the chord) of either tip plane",
             boxes=((-INF, INF, -INF, tip, -INF, INF), (-INF, INF, span - tip, INF, -INF, INF))),
    )


AHMED_BAND = 0.02  # m: half-width of the edge bands (about 2 % of the length)


def _ahmed_zones() -> tuple[Zone, ...]:
    s = geo.ahmed_slant_points()
    length, half, height = geo.AHMED_LENGTH / 1000, geo.AHMED_WIDTH / 2000, geo.AHMED_HEIGHT / 1000
    x0, zr = s["x_start"] / 1000, s["z_rear"] / 1000
    slant = (
        ((x0, -half, height), (x0, half, height)),  # roof / slant edge
        ((length, -half, zr), (length, half, zr)),  # slant / rear face edge
        ((x0, -half, height), (length, -half, zr)),  # slant side edges
        ((x0, half, height), (length, half, zr)),
    )
    rear = (
        ((length, -half, 0.0), (length, half, 0.0)),  # rear face: bottom edge
        ((length, -half, 0.0), (length, -half, zr)),  # rear face: vertical edges
        ((length, half, 0.0), (length, half, zr)),
        ((length, -half, zr), (length, half, zr)),  # rear face: top edge (shared with the slant)
    )
    return (
        Zone("slant_edges", f"within {AHMED_BAND:g} m of the four edges of the 25 degree slant",
             segments=slant, width=AHMED_BAND),
        Zone("rear_edges", f"within {AHMED_BAND:g} m of the four edges of the rear face",
             segments=rear, width=AHMED_BAND),
    )


CASES: dict[str, BenchCase] = {
    "sphere": BenchCase(
        name="sphere", geometry="sphere", units="m", reference_length=1.0,
        description="sphere, diameter 1 m, STL (control case)",
        reports={"reference_length": 1.0},  # l_ref = the diameter
    ),
    "wing": BenchCase(
        name="wing", geometry="wing", units="mm", reference_length=1.0,
        reports={"reference_length": 1.0},  # l_ref = the chord
        description="rectangular wing NACA 0012, chord 1 m, span 3 m, trailing edge 0.25 % of the chord, "
                    "flat tips, STEP",
        zones=_wing_zones(),
    ),
    "ahmed": BenchCase(
        name="ahmed", geometry="ahmed", units="mm", reference_length=geo.AHMED_LENGTH / 1000,
        reports={"reference_length": geo.AHMED_LENGTH / 1000},  # l_ref = the body length
        description="Ahmed-type body 1.044 x 0.389 x 0.288 m, front radius 0.1 m, 25 degree slant, no stilts, "
                    "STEP",
        zones=_ahmed_zones(),
    ),
}


def deviations(case: BenchCase, cores: int | None = None) -> list[str]:
    """Every setting of ``case`` that differs from the app's defaults, as readable lines."""
    out = [f"mesh.{k} = {v!r}" for k, v in sorted(case.mesh.items())]
    out += [f"inflow.{k} = {v!r}" for k, v in sorted(case.inflow.items())]
    out += [f"domain.{k} = {v!r}" for k, v in sorted(case.domain.items())]
    out += [f"reports.{k} = {v!r}" for k, v in sorted(case.reports.items())]
    out.append(f"solvers.iterations = {case.iterations} (fixed; stopping criteria removed; indicative y+ run)")
    out.append(f"solvers.write_interval = {case.iterations}")
    if cores is not None:
        out.append(f"solvers.cores = {cores} (the recommended count for the mesh, D-064)")
    return out
