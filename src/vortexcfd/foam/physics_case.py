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
from dataclasses import dataclass

from vortexcfd.core.model import Inflow, Physics, Solvers
from vortexcfd.foam.case_writer import FoamFileSpec

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


def flow_direction(alpha_deg: float) -> tuple[float, float, float]:
    """Unit flow direction: +x rotated by the angle of attack about +y (z up)."""
    a = math.radians(alpha_deg)
    return math.cos(a), 0.0, math.sin(a)


def _force_coeffs(inp: SolverCaseInput) -> dict:
    """The motorBike tutorial's forceCoeffs entry for the part walls (incompressible: rhoInf)."""
    b = inp.parts_bounds
    a = math.radians(inp.inflow.alpha_deg)
    centre = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]
    l_ref = b[1] - b[0]
    return {
        "type": "forceCoeffs",
        "libs": ["forces"],
        "writeControl": "timeStep",
        "writeInterval": 1,
        "log": True,
        "patches": list(inp.patches),
        "rho": "rhoInf",
        "rhoInf": inp.physics.rho_ref,
        "liftDir": [-math.sin(a), 0.0, math.cos(a)],
        "dragDir": [math.cos(a), 0.0, math.sin(a)],
        "CofR": centre,
        "pitchAxis": [0.0, 1.0, 0.0],
        "magUInf": inp.inflow.speed,
        "lRef": l_ref,
        "Aref": l_ref * (b[3] - b[2]),
    }


def control_dict(inp: SolverCaseInput) -> FoamFileSpec:
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
        "functions": {
            "forceCoeffs1": _force_coeffs(inp),
            "yPlus1": {
                "type": "yPlus",
                "libs": ["fieldFunctionObjects"],
                "writeFields": True,
                "executeControl": "writeTime",
                "writeControl": "writeTime",
            },
        },
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
    """motorBike fvSolution (v2606), preset "robust": SIMPLEC (consistent), U 0.9, k/omega 0.7."""
    p = {"solver": "GAMG", "smoother": "GaussSeidel", "tolerance": 1e-7, "relTol": 0.01}
    smooth = {"solver": "smoothSolver", "smoother": "GaussSeidel", "tolerance": 1e-8, "relTol": 0.1,
              "nSweeps": 1}
    return FoamFileSpec(content={
        "solvers": {"p": p, "Phi": dict(p), "U": dict(smooth), "k": dict(smooth), "omega": dict(smooth)},
        "SIMPLE": {"nNonOrthogonalCorrectors": 0, "consistent": True},
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
