"""Solver case files for steady incompressible external aerodynamics (no Qt).

Keywords and file names follow the ESI v2606 tutorials incompressible/simpleFoam/motorBike
(fvSchemes, fvSolution, 0.orig/, constant/transportProperties, constant/turbulenceProperties,
system/forceCoeffs) and airFoil2D. [NUMERICS-REVIEW]
"""


def inlet_turbulence(speed: float, intensity: float, nu: float, viscosity_ratio: float) -> tuple[float, float]:
    """Inlet k (m2/s2) and omega (1/s) from the free-stream speed, turbulence intensity and
    eddy-to-molecular viscosity ratio.

    k = 1.5 (V I)^2          turbulence kinetic energy from the intensity I = u' / V
                             (isotropic turbulence, k = 3/2 u'^2)
    omega = k / (nu * ratio) from nut = k / omega and ratio = nut / nu

    Source: the standard estimates of the OpenFOAM user guide (turbulence inlet conditions). The
    motorBike tutorial uses fixed values (k = 0.24, omega = 1.78) instead.
    """
    k = 1.5 * (speed * intensity) ** 2
    omega = k / (nu * viscosity_ratio)
    return k, omega


import math
from dataclasses import dataclass, field

from vortexcfd.core.model import Inflow, Physics, Reports, Solvers
from vortexcfd.foam.case_writer import FoamFileSpec
from vortexcfd.foam.convergence import FUNCTION_NAME as RUN_TIME_CONTROL
from vortexcfd.foam.convergence import force_coeffs_name, probe_function_name, run_time_control
from vortexcfd.foam.mesh_case import FRONT_AND_BACK, GROUND_PATCH
from vortexcfd.foam.parallel import DECOMPOSE_DICT, decompose_par_dict
from vortexcfd.foam.postprocessing import BODY_COEFFS

Bounds = tuple[float, float, float, float, float, float]  # xmin, xmax, ymin, ymax, zmin, zmax

# Far-field patches (as the motorBike tutorial's upperWall / frontAndBack): slip for the flow
# fields; nut stays "calculated" there, like the tutorial. The rounded domain shapes name theirs
# differently and get the same conditions (D-078).
FAR_FIELD = ("sides", "top", "bottom")
FAR_FIELD_BY_SHAPE = {"box": FAR_FIELD, "bullet": ("farfield",), "c_type": ("farfield", "sides")}


@dataclass(frozen=True)
class SolverCaseInput:
    """Everything the solver files depend on (plain data, metres)."""

    physics: Physics
    inflow: Inflow
    solvers: Solvers
    patches: tuple[str, ...]  # part wall patches (safe names)
    parts_bounds: Bounds  # union of the parts' bounding boxes
    symmetric: bool = False  # a symmetry plane patch exists
    reports: Reports = field(default_factory=Reports)  # reference value overrides (None = auto)
    # (part key, its patches) for every part with several patches (mesh_case.part_force_groups):
    # the per-part force objects sum all of the part's patches.
    part_groups: tuple[tuple[str, tuple[str, ...]], ...] = ()
    far_field: tuple[str, ...] = FAR_FIELD  # the domain's far-field patches (FAR_FIELD_BY_SHAPE)
    # The ground plane's motion ("stationary" or "moving"; None: no ground, D-116). Its patch is
    # GROUND_PATCH and replaces "bottom" in ``far_field`` (far_field_patches).
    ground: str | None = None
    # The 2D mode (D-121): the span of the one-cell mesh (metres); the empty patch "frontAndBack" gets every
    # field and the reference area is chord x span. None: 3D.
    span: float | None = None
    # The two-stage turbulence scheme of the wall-resolved mode (D-126): first-order k and omega until the switch,
    # then TURBULENCE_STAGE2's bounded second-order scheme; the criteria are evaluated by the app.
    two_stage: bool = False
    # Internal flow (D-129): the inlets, outlets and cutting planes; ``patches`` are then the walls only, there is no
    # far field and no force object. None: external flow.
    internal: "InternalSetup | None" = None


@dataclass(frozen=True)
class InternalInlet:
    """An internal-flow inlet as the solver files need it (D-129): ``kind`` "velocity" (``speed`` m/s normal to the
    patch), "mass_flow" (``flow_rate`` m3/s: the mass flow over the reference density) or "total_pressure"
    (``total_pressure`` kinematic, m2/s2: Pa over the reference density); the turbulence ``intensity`` and the
    mixing ``length_scale`` (m)."""

    patch: str
    kind: str
    intensity: float
    length_scale: float
    speed: float = 0.0
    flow_rate: float = 0.0
    total_pressure: float = 0.0


@dataclass(frozen=True)
class InternalOutlet:
    """A static-pressure outlet (D-129): ``pressure`` kinematic (m2/s2)."""

    patch: str
    pressure: float = 0.0


@dataclass(frozen=True)
class InternalSetup:
    """The internal-flow boundaries and reports (D-129): the initial field's k and omega (from the reference inlet's
    bulk speed, intensity and length scale) and the cutting planes (name, point, unit normal)."""

    inlets: tuple[InternalInlet, ...]
    outlets: tuple[InternalOutlet, ...]
    k0: float
    omega0: float
    planes: tuple[tuple[str, tuple[float, float, float], tuple[float, float, float]], ...] = ()

    @property
    def open_patches(self) -> tuple[str, ...]:
        return tuple(i.patch for i in self.inlets) + tuple(o.patch for o in self.outlets)


# The model coefficient of the mixing-length omega (turbulentMixingLengthFrequencyInlet, v2606: omega =
# k^0.5 / (Cmu^0.25 L), Cmu = 0.09).
CMU = 0.09


def internal_turbulence(speed: float, intensity: float, length_scale: float) -> tuple[float, float]:
    """k = 1.5 (I U)^2 and omega = sqrt(k) / (Cmu^0.25 L): the values the inlet conditions
    turbulentIntensityKineticEnergyInlet and turbulentMixingLengthFrequencyInlet give at the speed ``speed``
    (v2606 headers); used for the initial field. [NUMERICS-REVIEW]"""
    k = 1.5 * (speed * intensity) ** 2
    return k, math.sqrt(k) / (CMU ** 0.25 * length_scale)


def far_field_patches(shape: str, ground: bool, slip_strip: bool = False, two_d: bool = False) -> tuple[str, ...]:
    """The far-field (slip) patches of a domain shape; the ground plane replaces the box's bottom (D-116),
    and its slip strip ahead of the wall start, "ground_slip", takes the far field's slip conditions
    (D-118). In 2D the spanwise "sides" are not in the mesh (the empty "frontAndBack" is, D-121). [NUMERICS-REVIEW]"""
    names = tuple(n for n in FAR_FIELD_BY_SHAPE[shape] if not (two_d and n == "sides"))
    if not (ground and shape == "box"):
        return names
    return tuple(n for n in names if n != "bottom") + (("ground_slip",) if slip_strip else ())


# The free stream is always along +x; the angle of attack rotates the parts (D-120).
FLOW_DIRECTION = (1.0, 0.0, 0.0)
# Wind axes of the force coefficients (D-120): drag along the free stream, lift +z normal to it.
DRAG_DIR = (1.0, 0.0, 0.0)
LIFT_DIR = (0.0, 0.0, 1.0)
# The body-axis coefficients of all walls (D-120): a second forceCoeffs object (postprocessing.BODY_COEFFS)
# whose drag and lift directions are the parts' own x and z axes at the angle of attack, so its Cd and Cl are
# the axial and normal force coefficients (C_A, C_N) and its header carries the body axes (foam/forces.py).


def flow_direction() -> tuple[float, float, float]:
    """Unit flow direction: always +x (the angle of attack turns the parts, D-120)."""
    return FLOW_DIRECTION


def body_axes(alpha_deg: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """(x_body, z_body) in the wind axes: the parts' x and z axes turned nose up by alpha about +y,
    (cos a, 0, -sin a) and (sin a, 0, cos a) (geometry/attitude.py, D-120)."""
    a = math.radians(alpha_deg)
    return (math.cos(a), 0.0, -math.sin(a)), (math.sin(a), 0.0, math.cos(a))


# A_ref bases: label of the auto value (stated exactly in the GUI).
AREA_BASIS_LABELS = {
    "planform": "auto: bounding-box planform, x * y",
    "frontal": "auto: bounding-box frontal, y * z",
}
LENGTH_AUTO_LABEL = "auto: bounding-box length, x extent"
CENTRE_AUTO_LABEL = "auto: bounding-box centre"


@dataclass(frozen=True)
class ReferenceValues:
    """forceCoeffs reference values and how each was obtained.

    A_ref by basis: planform = x extent * y extent, frontal = y extent * z extent of the parts'
    bounding box, or the user's custom value; l_ref = x extent and CofR = the box centre unless
    overridden. [NUMERICS-REVIEW] (D-047)
    """

    l_ref: float
    a_ref: float
    cofr: tuple[float, float, float]
    a_basis: str = "planform"  # planform, frontal or custom
    l_auto: bool = True
    cofr_auto: bool = True

    @property
    def a_auto(self) -> bool:
        return self.a_basis != "custom"


def bounding_box_area(parts_bounds: Bounds, basis: str) -> float:
    b = parts_bounds
    dx, dy, dz = b[1] - b[0], b[3] - b[2], b[5] - b[4]
    if basis == "planform":
        return dx * dy
    if basis == "frontal":
        return dy * dz
    raise ValueError(f"no bounding-box area for basis {basis!r}")


def auto_reference(parts_bounds: Bounds) -> ReferenceValues:
    b = parts_bounds
    return ReferenceValues(b[1] - b[0], bounding_box_area(b, "planform"),
                           ((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2))


SECTION_AREA_LABEL = "auto: 2D section, chord (x extent) * span"


def reference_values(parts_bounds: Bounds, reports: Reports, span: float | None = None) -> ReferenceValues:
    """The user's choices where set, the bounding-box values otherwise. ``span``: a 2D section's mesh span
    (D-121): the automatic area is then the chord (x extent) times the span, whatever the basis, so the
    coefficients are those of the section per unit span."""
    auto = auto_reference(parts_bounds)
    basis = reports.reference_area_basis
    if basis == "custom":
        area = reports.reference_area
    elif span is not None:
        area = (parts_bounds[1] - parts_bounds[0]) * span
    else:
        area = bounding_box_area(parts_bounds, basis)
    return ReferenceValues(
        l_ref=reports.reference_length if reports.reference_length is not None else auto.l_ref,
        a_ref=area,
        cofr=tuple(reports.center_of_rotation) if reports.center_of_rotation is not None else auto.cofr,
        a_basis=basis,
        l_auto=reports.reference_length is None,
        cofr_auto=reports.center_of_rotation is None,
    )


def _force_coeffs(inp: SolverCaseInput, patches: tuple[str, ...] | None = None, body: bool = False) -> dict:
    """The motorBike tutorial's forceCoeffs entry for the part walls (incompressible: rhoInf), in the wind
    axes: drag along the free stream (+x), lift +z (D-120); ``body``: the body axes (BODY_COEFFS).

    v2606 (forces::setCoordinateSystem): with CofR, liftDir is e3 and dragDir e1 of the coefficient
    axes and the pitch axis is e2 = e3 x e1 (+y in both axis sets: a positive pitching moment is nose up);
    the `pitchAxis` entry is not read and is kept only as documentation. Output:
    postProcessing/forceCoeffs1/<start time>/coefficient.dat (foam/postprocessing.py). The CofR is the
    rotation centre of the parts, so the moment is about the same point at every angle."""
    ref = reference_values(inp.parts_bounds, inp.reports, inp.span)
    drag, lift = body_axes(inp.inflow.alpha_deg) if body else (DRAG_DIR, LIFT_DIR)
    return {
        "type": "forceCoeffs",
        "libs": ["forces"],
        "writeControl": "timeStep",
        "writeInterval": 1,
        "log": patches is None and not body,  # only the total in the solver log
        "patches": list(inp.patches if patches is None else patches),
        "rho": "rhoInf",
        "rhoInf": inp.physics.rho_ref,
        "liftDir": list(lift),
        "dragDir": list(drag),
        "CofR": list(ref.cofr),
        "pitchAxis": [0.0, 1.0, 0.0],
        "magUInf": inp.inflow.speed,
        "lRef": ref.l_ref,
        "Aref": ref.a_ref,
    }


def _forces(inp: SolverCaseInput, patches: tuple[str, ...] | None = None) -> dict:
    """Total, pressure and viscous force and moment on the part walls in the GLOBAL axes (CofR with
    no direction entries: e1 = x, e3 = z), next to forceCoeffs so its projection can be checked
    (D-050). Output: postProcessing/forces1/<start time>/force.dat and moment.dat (N and N m with
    rho = rhoInf; in 2D the force on the span, D-121)."""
    ref = reference_values(inp.parts_bounds, inp.reports, inp.span)
    return {
        "type": "forces",
        "libs": ["forces"],
        "writeControl": "timeStep",
        "writeInterval": 1,
        "log": False,
        "patches": list(inp.patches if patches is None else patches),
        "rho": "rhoInf",
        "rhoInf": inp.physics.rho_ref,
        "CofR": list(ref.cofr),
    }


# Open boundaries whose flux is summed for the mass balance; the far-field patches are slip and
# the symmetry plane is symmetryPlane, so their flux is zero by construction (D-060).
MASS_FLOW_PATCHES = ("inlet", "outlet")


def mass_flow_name(patch: str) -> str:
    return f"massFlow_{patch}"


def _mass_flow(patch: str) -> dict:
    """sum(phi) over a patch every iteration (surfaceFieldValue, v2606 keywords): m3/s, positive out
    of the domain. Output: postProcessing/massFlow_<patch>/<start time>/surfaceFieldValue.dat."""
    return {
        "type": "surfaceFieldValue",
        "libs": ["fieldFunctionObjects"],
        "regionType": "patch",
        "name": patch,
        "operation": "sum",
        "fields": ["phi"],
        "writeFields": False,
        "writeControl": "timeStep",
        "writeInterval": 1,
        "log": False,
    }


def _wall_shear_stress(inp: SolverCaseInput) -> dict:
    """The kinematic wall shear stress field on the part walls at write times (wallShearStress,
    v2606): tau = n_in . devReff, the wall's stress on the fluid (foam/wall_fields.py)."""
    return {
        "type": "wallShearStress",
        "libs": ["fieldFunctionObjects"],
        "patches": list(inp.patches),
        "writeFields": True,
        "executeControl": "writeTime",
        "writeControl": "writeTime",
    }


# Probe values interpolated to the point (cell value corrected with the point values,
# interpolationCellPoint, TypeName "cellPoint"), not the containing cell's value (D-060).
PROBE_INTERPOLATION = "cellPoint"


def _probe(location) -> dict:
    """One probes object per probe (p and U at one point, interpolated with cellPoint), sampled
    every iteration; its results average(p) / average(U) are that probe's values.
    Output: postProcessing/probe_<name>/<start time>/p and U."""
    return {
        "type": "probes",
        "libs": ["sampling"],
        "fields": ["p", "U"],
        "probeLocations": [list(location)],
        "interpolationScheme": PROBE_INTERPOLATION,
        "sampleOnExecute": True,
        "writeControl": "timeStep",
        "writeInterval": 1,
    }


def control_dict(inp: SolverCaseInput) -> FoamFileSpec:
    """controlDict: endTime is the iteration limit; residual-only stopping criteria are a
    runTimeControl function object placed last; with an asymptotic criterion none is written and
    the app evaluates the criteria and stops the solver (D-058)."""
    if inp.internal is not None:
        functions = _internal_functions(inp)
    else:
        functions = _external_functions(inp)
    functions["yPlus1"] = {
        "type": "yPlus",
        "libs": ["fieldFunctionObjects"],
        "writeFields": True,
        "executeControl": "writeTime",
        "writeControl": "writeTime",
    }
    functions["wallShearStress1"] = _wall_shear_stress(inp)
    for probe in inp.reports.probes:
        functions[probe_function_name(probe.name)] = _probe(probe.location)
    stop = None if inp.two_stage else run_time_control(inp.solvers.stopping)  # two stages: app-side (D-126)
    if stop is not None:
        functions[RUN_TIME_CONTROL] = stop
    return FoamFileSpec(content={
        "application": "simpleFoam",
        "startFrom": "startTime",
        "startTime": 0,
        "stopAt": "endTime",
        "endTime": inp.solvers.iterations,
        "deltaT": 1,
        "writeControl": "timeStep",
        "writeInterval": inp.solvers.write_interval,
        "purgeWrite": 0,
        "writeFormat": "ascii",
        "writePrecision": 6,
        "writeCompression": False,
        "timeFormat": "general",
        "timePrecision": 6,
        "runTimeModifiable": True,
        "functions": functions,
    })


def _external_functions(inp: SolverCaseInput) -> dict:
    """The force objects (all walls, body axes, per patch and per part) and the inlet / outlet mass flow."""
    functions = {
        "forceCoeffs1": _force_coeffs(inp),
        BODY_COEFFS: _force_coeffs(inp, body=True),
        "forces1": _forces(inp),
    }
    if len(inp.patches) > 1:  # per patch (D-060); with one patch these equal the totals
        for patch in inp.patches:
            functions[force_coeffs_name(patch)] = _force_coeffs(inp, (patch,))
            functions[f"forces_{patch}"] = _forces(inp, (patch,))
    for key, patches in inp.part_groups:  # per part over ALL its patches (D-071)
        functions[force_coeffs_name(key)] = _force_coeffs(inp, tuple(patches))
        functions[f"forces_{key}"] = _forces(inp, tuple(patches))
    for patch in MASS_FLOW_PATCHES:
        functions[mass_flow_name(patch)] = _mass_flow(patch)
    return functions


# Internal-flow reports (D-129) [NUMERICS-REVIEW]: the pressure function object (v2606 functionObjects/field/
# pressure: a kinematic p is multiplied by rhoInf) writes the static and total pressure in Pa as the fields
# STATIC_P and TOTAL_P; per inlet and outlet and per cutting plane, surfaceFieldValue (v2606 fieldValues/
# surfaceFieldValue) averages them by area (areaAverage) and by mass flux (weightedAreaAverage with the vector
# weightField U: the weight is U . Sf, surfaceFieldValueTemplates.C), and gives the flow: sum(phi) on a patch
# (massFlow_<patch>, m3/s, positive out of the domain), the integral of U . n dA on a plane (areaNormalIntegrate).
# The pressure objects come first: function objects run in their order.
STATIC_P, TOTAL_P = "p_static", "p_total"
PRESSURE_AVERAGES = {"area": "areaAverage", "mass": "weightedAreaAverage"}


def area_average_name(location: str) -> str:
    """The area-average object of a location ("patch:<name>" or "plane:<name>")."""
    kind, _, name = location.partition(":")
    return f"{'pArea' if kind == 'patch' else 'planePArea'}_{name}"


def mass_average_name(location: str) -> str:
    kind, _, name = location.partition(":")
    return f"{'pMass' if kind == 'patch' else 'planePMass'}_{name}"


def plane_flow_name(plane: str) -> str:
    return f"planeFlow_{plane}"


def _pressure_field(inp: SolverCaseInput, mode: str, result: str) -> dict:
    return {
        "type": "pressure",
        "libs": ["fieldFunctionObjects"],
        "mode": mode,
        "rho": "rhoInf",
        "rhoInf": inp.physics.rho_ref,
        "result": result,
        "executeControl": "timeStep",
        "executeInterval": 1,
        "writeControl": "writeTime",
    }


def _plane_surface(point, normal) -> dict:
    return {"type": "plane", "planeType": "pointAndNormal",
            "pointAndNormalDict": {"point": list(point), "normal": list(normal)}}


def _surface_values(region: dict, operation: str, fields: list[str], weight: str | None = None) -> dict:
    entry = {
        "type": "surfaceFieldValue",
        "libs": ["fieldFunctionObjects"],
        **region,
        "operation": operation,
        "fields": fields,
        "writeFields": False,
        "writeControl": "timeStep",
        "writeInterval": 1,
        "log": False,
    }
    if weight is not None:
        entry["weightField"] = weight
    return entry


# The report definitions of an internal-flow case (foam/postprocessing.INTERNAL_REPORTS_FILE).
INTERNAL_REPORTS_FILE = "system/internalReports"


def internal_reports(inp: SolverCaseInput) -> FoamFileSpec:
    """The reference density and the pressure drops (name: upstream and downstream location)."""
    drops = {d.name: {"upstream": d.upstream, "downstream": d.downstream} for d in inp.reports.pressure_drops}
    return FoamFileSpec(content={"rho": inp.physics.rho_ref, "pressureDrops": drops})


def _internal_functions(inp: SolverCaseInput) -> dict:
    """The internal-flow report objects (D-129): no force objects (the walls of a duct carry no meaningful
    coefficient; their friction is in the pressure drop)."""
    setup = inp.internal
    functions = {"pStatic": _pressure_field(inp, "static", STATIC_P), "pTotal": _pressure_field(inp, "total", TOTAL_P)}
    pressures = [STATIC_P, TOTAL_P]
    for patch in setup.open_patches:
        region = {"regionType": "patch", "name": patch}
        functions[mass_flow_name(patch)] = _mass_flow(patch)
        functions[area_average_name(f"patch:{patch}")] = _surface_values(region, "areaAverage", pressures)
        functions[mass_average_name(f"patch:{patch}")] = _surface_values(region, "weightedAreaAverage", pressures, "U")
    for name, point, normal in setup.planes:
        region = {"regionType": "sampledSurface", "name": name, "sampledSurfaceDict": _plane_surface(point, normal)}
        functions[plane_flow_name(name)] = _surface_values(region, "areaNormalIntegrate", ["U"])
        functions[area_average_name(f"plane:{name}")] = _surface_values(region, "areaAverage", pressures)
        functions[mass_average_name(f"plane:{name}")] = _surface_values(region, "weightedAreaAverage", pressures, "U")
    return functions


def fv_schemes() -> FoamFileSpec:
    """motorBike fvSchemes (v2606): bounded steady schemes, linearUpwindV for U, upwind for k/omega."""
    # Tuples, not lists: a scheme is a bare token sequence (a list would be written in parentheses).
    upwind = ("bounded", "Gauss", "upwind")
    return FoamFileSpec(content={
        "ddtSchemes": {"default": "steadyState"},
        "gradSchemes": {"default": ("Gauss", "linear"), "grad(U)": ("cellLimited", "Gauss", "linear", 1)},
        "divSchemes": {
            "default": "none",
            "div(phi,U)": ("bounded", "Gauss", "linearUpwindV", "grad(U)"),
            "div(phi,k)": upwind,
            "div(phi,omega)": upwind,
            "div((nuEff*dev2(T(grad(U)))))": ("Gauss", "linear"),
        },
        "laplacianSchemes": {"default": ("Gauss", "linear", "corrected")},
        "interpolationSchemes": {"default": "linear"},
        "snGradSchemes": {"default": "corrected"},
        "wallDist": {"method": "meshWave"},
    })


# The two-stage turbulence scheme of the wall-resolved mode (D-126) [NUMERICS-REVIEW]: stage 2 replaces the k and
# omega convection of fv_schemes (bounded first-order upwind) with bounded Gauss linearUpwind on cell-limited
# gradients, the scheme of the NACA 0012 round 2 (docs/validation/naca0012/RESULT.md). Written into the case as
# STAGES_FILE, which foam/solver_run.SolverRun reads; OpenFOAM ignores it.
STAGES_FILE = "system/turbulenceStages"
TURBULENCE_STAGE2 = {
    "divSchemes": {"div(phi,k)": ("bounded", "Gauss", "linearUpwind", "grad(k)"),
                   "div(phi,omega)": ("bounded", "Gauss", "linearUpwind", "grad(omega)")},
    "gradSchemes": {"grad(k)": ("cellLimited", "Gauss", "linear", 1),
                    "grad(omega)": ("cellLimited", "Gauss", "linear", 1)},
}


def turbulence_stages() -> FoamFileSpec:
    """STAGES_FILE: the fvSchemes entries of stage 2 (merged into system/fvSchemes at the switch)."""
    return FoamFileSpec(content={"stage2": {key: dict(entries) for key, entries in TURBULENCE_STAGE2.items()}})


def fv_solution(solvers: Solvers) -> FoamFileSpec:
    """motorBike fvSolution (v2606), preset "robust": SIMPLEC (consistent), U 0.9, k/omega 0.7.

    No residualControl: the stop is the runTimeControl function object of the stopping criteria
    (controlDict) or the app's own evaluation, which honour the minimum iterations and the "any"
    combination; residualControl would end the run on its own targets regardless (D-058)."""
    p = {"solver": "GAMG", "smoother": "GaussSeidel", "tolerance": 1e-7, "relTol": 0.01}
    smooth = {"solver": "smoothSolver", "smoother": "GaussSeidel", "tolerance": 1e-8, "relTol": 0.1,
              "nSweeps": 1}
    return FoamFileSpec(content={
        "solvers": {"p": p, "Phi": dict(p), "U": dict(smooth), "k": dict(smooth), "omega": dict(smooth)},
        "SIMPLE": {
            "nNonOrthogonalCorrectors": 0,
            "consistent": True,
        },
        "potentialFlow": {"nNonOrthogonalCorrectors": 10},
        "relaxationFactors": {"equations": {"U": 0.9, "k": 0.7, "omega": 0.7}},
    })


def transport_properties(physics: Physics) -> FoamFileSpec:
    return FoamFileSpec(content={"transportModel": "Newtonian", "nu": physics.nu})


def turbulence_properties(physics: Physics) -> FoamFileSpec:
    return FoamFileSpec(content={
        "simulationType": "RAS",
        "RAS": {"RASModel": physics.turbulence_model, "turbulence": True, "printCoeffs": True},
    })


def ground_velocity(inp: SolverCaseInput) -> tuple[float, float, float]:
    """The moving ground's velocity (D-116): the free-stream velocity, +x at every angle of attack (the
    app turns the parts, never the free stream, D-120)."""
    return inp.inflow.speed, 0.0, 0.0


def _patch_names(inp: SolverCaseInput) -> list[str]:
    names = ["inlet", "outlet", *inp.far_field]
    if inp.symmetric:
        names.append("symmetry")
    return names


def _field(inp: SolverCaseInput, cls: str, dimensions: list[int], internal, inlet: dict, outlet: dict,
           far: dict, wall: dict, value_for_walls=None, ground: dict | None = None) -> FoamFileSpec:
    """A field file; the ground plane (if any) takes ``ground``, else the part walls' ``wall``."""
    boundary: dict[str, dict] = {"inlet": inlet, "outlet": outlet}
    for name in inp.far_field:
        boundary[name] = dict(far)
    if inp.symmetric:
        boundary["symmetry"] = {"type": "symmetryPlane"}
    if inp.span is not None:  # 2D (D-121)
        boundary[FRONT_AND_BACK] = {"type": "empty"}
    if inp.ground is not None:
        boundary[GROUND_PATCH] = dict(ground if ground is not None else wall)
    for name in inp.patches:
        boundary[name] = dict(wall)
    return FoamFileSpec(
        content={"dimensions": dimensions, "internalField": internal, "boundaryField": boundary},
        class_name=cls,
    )


def internal_fields(inp: SolverCaseInput) -> dict[str, FoamFileSpec]:
    """0/U, 0/p, 0/k, 0/omega, 0/nut of internal flow (D-129) [NUMERICS-REVIEW]; types confirmed in the v2606 sources
    (src/finiteVolume/fields/fvPatchFields/derived, src/TurbulenceModels/.../derivedFvPatchFields) and the tutorial
    incompressible/pimpleFoam/RAS/TJunction:

    velocity inlet: U surfaceNormalFixedValue refValue -V (positive outwards); p zeroGradient.
    mass-flow inlet: U flowRateInletVelocity volumetricFlowRate Q = m / rho_ref (a uniform velocity normal to the
    patch matching Q); p zeroGradient.
    total-pressure inlet: p totalPressure p0 (kinematic: p = p0 - 0.5 |U|^2 on inflow); U
    pressureInletOutletVelocity (inflow from the patch-normal component of the internal value, zero gradient on
    outflow), as TJunction.
    every inlet: k turbulentIntensityKineticEnergyInlet (k = 1.5 (I |U|)^2), omega turbulentMixingLengthFrequencyInlet
    (omega = k^0.5 / (Cmu^0.25 L)); both zero gradient on backflow; nut calculated.
    static-pressure outlet: p fixedValue; U, k, omega inletOutlet (zero gradient out, zero velocity and the inlet
    turbulence on backflow); nut calculated.
    walls: the external walls' conditions (noSlip, kqRWallFunction, omegaWallFunction, nutUSpaldingWallFunction).
    The internal field starts at rest (U 0) with the reference inlet's k and omega."""
    setup = inp.internal
    k0, omega0 = setup.k0, setup.omega0
    zero = [0.0, 0.0, 0.0]
    u_b, p_b, k_b, om_b, nut_b = {}, {}, {}, {}, {}
    for inlet in setup.inlets:
        if inlet.kind == "velocity":
            u_b[inlet.patch] = {"type": "surfaceNormalFixedValue", "refValue": -inlet.speed,
                                "value": zero}
            p_b[inlet.patch] = {"type": "zeroGradient"}
        elif inlet.kind == "mass_flow":
            u_b[inlet.patch] = {"type": "flowRateInletVelocity", "volumetricFlowRate": inlet.flow_rate,
                                "extrapolateProfile": False, "value": zero}
            p_b[inlet.patch] = {"type": "zeroGradient"}
        else:
            u_b[inlet.patch] = {"type": "pressureInletOutletVelocity", "value": zero}
            p_b[inlet.patch] = {"type": "totalPressure", "p0": ("uniform", inlet.total_pressure),
                                "value": inlet.total_pressure}
        k_b[inlet.patch] = {"type": "turbulentIntensityKineticEnergyInlet", "intensity": inlet.intensity,
                            "value": k0}
        om_b[inlet.patch] = {"type": "turbulentMixingLengthFrequencyInlet", "mixingLength": inlet.length_scale,
                             "value": omega0}
        nut_b[inlet.patch] = {"type": "calculated", "value": 0.0}
    for outlet in setup.outlets:
        u_b[outlet.patch] = {"type": "inletOutlet", "inletValue": zero, "value": zero}
        p_b[outlet.patch] = {"type": "fixedValue", "value": outlet.pressure}
        k_b[outlet.patch] = {"type": "inletOutlet", "inletValue": k0, "value": k0}
        om_b[outlet.patch] = {"type": "inletOutlet", "inletValue": omega0, "value": omega0}
        nut_b[outlet.patch] = {"type": "calculated", "value": 0.0}
    walls = {"U": {"type": "noSlip"}, "p": {"type": "zeroGradient"},
             "k": {"type": "kqRWallFunction", "value": k0},
             "omega": {"type": "omegaWallFunction", "value": omega0},
             "nut": {"type": "nutUSpaldingWallFunction", "value": 0.0}}

    def spec(name: str, cls: str, dims: list[int], internal, boundary: dict) -> FoamFileSpec:
        out = dict(boundary)
        for wall in inp.patches:
            out[wall] = dict(walls[name])
        if inp.span is not None:  # 2D (D-121)
            out[FRONT_AND_BACK] = {"type": "empty"}
        return FoamFileSpec(content={"dimensions": dims, "internalField": internal, "boundaryField": out},
                            class_name=cls)

    return {
        "0/U": spec("U", "volVectorField", [0, 1, -1, 0, 0, 0, 0], zero, u_b),
        "0/p": spec("p", "volScalarField", [0, 2, -2, 0, 0, 0, 0], 0.0, p_b),
        "0/k": spec("k", "volScalarField", [0, 2, -2, 0, 0, 0, 0], k0, k_b),
        "0/omega": spec("omega", "volScalarField", [0, 0, -1, 0, 0, 0, 0], omega0, om_b),
        "0/nut": spec("nut", "volScalarField", [0, 2, -1, 0, 0, 0, 0], 0.0, nut_b),
    }


def initial_fields(inp: SolverCaseInput) -> dict[str, FoamFileSpec]:
    """0/U, 0/p, 0/k, 0/omega, 0/nut with the external-aerodynamics boundary conditions.

    inlet: U fixedValue (V, 0, 0) at every angle of attack (D-120); p zeroGradient; k, omega fixedValue;
    nut calculated.
    outlet: p fixedValue 0; U, k, omega inletOutlet; nut calculated.
    sides/top/bottom: slip (nut calculated); symmetry: symmetryPlane.
    part walls: U noSlip; p zeroGradient; k kqRWallFunction; omega omegaWallFunction;
    nut nutUSpaldingWallFunction.
    ground plane (D-116): the part walls' conditions; a moving ground has U fixedValue
    ``ground_velocity`` instead of noSlip (the motorBike tutorial's lowerWall). [NUMERICS-REVIEW]
    """
    velocity = [inp.inflow.speed * c for c in FLOW_DIRECTION]
    k, omega = inlet_turbulence(inp.inflow.speed, inp.inflow.turbulence_intensity, inp.physics.nu,
                                inp.inflow.viscosity_ratio)
    slip = {"type": "slip"}
    u = _field(
        inp, "volVectorField", [0, 1, -1, 0, 0, 0, 0], velocity,
        inlet={"type": "fixedValue", "value": velocity},
        outlet={"type": "inletOutlet", "inletValue": [0.0, 0.0, 0.0], "value": velocity},
        far=slip, wall={"type": "noSlip"},
        ground=({"type": "fixedValue", "value": list(ground_velocity(inp))} if inp.ground == "moving" else None),
    )
    p = _field(
        inp, "volScalarField", [0, 2, -2, 0, 0, 0, 0], 0.0,
        inlet={"type": "zeroGradient"}, outlet={"type": "fixedValue", "value": 0.0},
        far=slip, wall={"type": "zeroGradient"},
    )
    kf = _field(
        inp, "volScalarField", [0, 2, -2, 0, 0, 0, 0], k,
        inlet={"type": "fixedValue", "value": k},
        outlet={"type": "inletOutlet", "inletValue": k, "value": k},
        far=slip, wall={"type": "kqRWallFunction", "value": k},
    )
    of = _field(
        inp, "volScalarField", [0, 0, -1, 0, 0, 0, 0], omega,
        inlet={"type": "fixedValue", "value": omega},
        outlet={"type": "inletOutlet", "inletValue": omega, "value": omega},
        far=slip, wall={"type": "omegaWallFunction", "value": omega},
    )
    calc = {"type": "calculated", "value": 0.0}
    nut = _field(
        inp, "volScalarField", [0, 2, -1, 0, 0, 0, 0], 0.0,
        inlet=dict(calc), outlet=dict(calc), far=dict(calc),
        wall={"type": "nutUSpaldingWallFunction", "value": 0.0},
    )
    return {"0/U": u, "0/p": p, "0/k": kf, "0/omega": of, "0/nut": nut}


def build_solver_files(inp: SolverCaseInput) -> dict[str, FoamFileSpec]:
    """All solver dictionaries and initial fields: relative path -> spec."""
    files = {
        "system/controlDict": control_dict(inp),
        "system/fvSchemes": fv_schemes(),
        "system/fvSolution": fv_solution(inp.solvers),
        "constant/transportProperties": transport_properties(inp.physics),
        "constant/turbulenceProperties": turbulence_properties(inp.physics),
    }
    if inp.two_stage:  # D-126
        files[STAGES_FILE] = turbulence_stages()
    if inp.internal is not None:  # the report definitions for the monitors (D-129); OpenFOAM ignores the file
        files[INTERNAL_REPORTS_FILE] = internal_reports(inp)
    files.update(internal_fields(inp) if inp.internal is not None else initial_fields(inp))
    if inp.solvers.cores > 1:  # parallel run (D-063)
        files[DECOMPOSE_DICT] = decompose_par_dict(inp.solvers.cores)
    return files
