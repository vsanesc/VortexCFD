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

Bounds = tuple[float, float, float, float, float, float]  # xmin, xmax, ymin, ymax, zmin, zmax

# Far-field patches (as the motorBike tutorial's upperWall / frontAndBack): slip for the flow
# fields; nut stays "calculated" there, like the tutorial.
FAR_FIELD = ("sides", "top", "bottom")


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


def flow_direction(alpha_deg: float) -> tuple[float, float, float]:
    """Unit flow direction: +x rotated by the angle of attack about +y (z up)."""
    a = math.radians(alpha_deg)
    return math.cos(a), 0.0, math.sin(a)


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


def reference_values(parts_bounds: Bounds, reports: Reports) -> ReferenceValues:
    """The user's choices where set, the bounding-box values otherwise."""
    auto = auto_reference(parts_bounds)
    basis = reports.reference_area_basis
    area = reports.reference_area if basis == "custom" else bounding_box_area(parts_bounds, basis)
    return ReferenceValues(
        l_ref=reports.reference_length if reports.reference_length is not None else auto.l_ref,
        a_ref=area,
        cofr=tuple(reports.center_of_rotation) if reports.center_of_rotation is not None else auto.cofr,
        a_basis=basis,
        l_auto=reports.reference_length is None,
        cofr_auto=reports.center_of_rotation is None,
    )


def _force_coeffs(inp: SolverCaseInput, patches: tuple[str, ...] | None = None) -> dict:
    """The motorBike tutorial's forceCoeffs entry for the part walls (incompressible: rhoInf).

    v2606 (forces::setCoordinateSystem): with CofR, liftDir is e3 and dragDir e1 of the coefficient
    axes and the pitch axis is e2 = e3 x e1 (+y at any angle of attack); the `pitchAxis` entry is
    not read and is kept only as documentation. Output: postProcessing/forceCoeffs1/<start
    time>/coefficient.dat (foam/postprocessing.py)."""
    ref = reference_values(inp.parts_bounds, inp.reports)
    a = math.radians(inp.inflow.alpha_deg)
    return {
        "type": "forceCoeffs",
        "libs": ["forces"],
        "writeControl": "timeStep",
        "writeInterval": 1,
        "log": patches is None,  # only the total in the solver log
        "patches": list(inp.patches if patches is None else patches),
        "rho": "rhoInf",
        "rhoInf": inp.physics.rho_ref,
        "liftDir": [-math.sin(a), 0.0, math.cos(a)],
        "dragDir": [math.cos(a), 0.0, math.sin(a)],
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
    rho = rhoInf)."""
    ref = reference_values(inp.parts_bounds, inp.reports)
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


def _probe(location) -> dict:
    """One probes object per probe (p and U at one point, cell value), sampled every iteration;
    its results average(p) / average(U) are that probe's values (the runTimeControl source).
    Output: postProcessing/probe_<name>/<start time>/p and U."""
    return {
        "type": "probes",
        "libs": ["sampling"],
        "fields": ["p", "U"],
        "probeLocations": [list(location)],
        "sampleOnExecute": True,
        "writeControl": "timeStep",
        "writeInterval": 1,
    }


def control_dict(inp: SolverCaseInput) -> FoamFileSpec:
    """controlDict: endTime is the iteration limit; the stopping criteria are a runTimeControl
    function object placed after the function objects whose results it reads (D-058)."""
    functions = {
        "forceCoeffs1": _force_coeffs(inp),
        "forces1": _forces(inp),
    }
    if len(inp.patches) > 1:  # per part (D-060); with one part these equal the totals
        for patch in inp.patches:
            functions[force_coeffs_name(patch)] = _force_coeffs(inp, (patch,))
            functions[f"forces_{patch}"] = _forces(inp, (patch,))
    for patch in MASS_FLOW_PATCHES:
        functions[mass_flow_name(patch)] = _mass_flow(patch)
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
    stop = run_time_control(inp.solvers.stopping)
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


def fv_solution(solvers: Solvers) -> FoamFileSpec:
    """motorBike fvSolution (v2606), preset "robust": SIMPLEC (consistent), U 0.9, k/omega 0.7.

    No residualControl: the stop is the runTimeControl function object of the stopping criteria
    (controlDict), which also honours the minimum iterations and the "any" combination;
    residualControl would end the run on its own targets regardless (D-058)."""
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


def _patch_names(inp: SolverCaseInput) -> list[str]:
    names = ["inlet", "outlet", *FAR_FIELD]
    if inp.symmetric:
        names.append("symmetry")
    return names


def _field(inp: SolverCaseInput, cls: str, dimensions: list[int], internal, inlet: dict, outlet: dict,
           far: dict, wall: dict, value_for_walls=None) -> FoamFileSpec:
    boundary: dict[str, dict] = {"inlet": inlet, "outlet": outlet}
    for name in FAR_FIELD:
        boundary[name] = dict(far)
    if inp.symmetric:
        boundary["symmetry"] = {"type": "symmetryPlane"}
    for name in inp.patches:
        boundary[name] = dict(wall)
    return FoamFileSpec(
        content={"dimensions": dimensions, "internalField": internal, "boundaryField": boundary},
        class_name=cls,
    )


def initial_fields(inp: SolverCaseInput) -> dict[str, FoamFileSpec]:
    """0/U, 0/p, 0/k, 0/omega, 0/nut with the external-aerodynamics boundary conditions.

    inlet: U fixedValue V (cos a, 0, sin a); p zeroGradient; k, omega fixedValue; nut calculated.
    outlet: p fixedValue 0; U, k, omega inletOutlet; nut calculated.
    sides/top/bottom: slip (nut calculated); symmetry: symmetryPlane.
    part walls: U noSlip; p zeroGradient; k kqRWallFunction; omega omegaWallFunction;
    nut nutUSpaldingWallFunction.
    """
    d = flow_direction(inp.inflow.alpha_deg)
    velocity = [inp.inflow.speed * c for c in d]
    k, omega = inlet_turbulence(inp.inflow.speed, inp.inflow.turbulence_intensity, inp.physics.nu,
                                inp.inflow.viscosity_ratio)
    slip = {"type": "slip"}
    u = _field(
        inp, "volVectorField", [0, 1, -1, 0, 0, 0, 0], velocity,
        inlet={"type": "fixedValue", "value": velocity},
        outlet={"type": "inletOutlet", "inletValue": [0.0, 0.0, 0.0], "value": velocity},
        far=slip, wall={"type": "noSlip"},
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
    files.update(initial_fields(inp))
    return files
