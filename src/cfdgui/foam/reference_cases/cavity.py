"""Lid-driven cavity reference case generator matching OpenFOAM ESI v2606."""

from dataclasses import dataclass

from cfdgui.foam.case_writer import FoamFileSpec


@dataclass
class CavityParams:
    """Parameters for the 2D lid-driven cavity case with OpenFOAM v2606 defaults."""

    nu: float = 0.01
    end_time: float = 0.5
    delta_t: float = 0.005
    write_interval: int = 20
    cells_x: int = 20
    cells_y: int = 20
    lid_velocity: float = 1.0


def build_cavity_files(params: CavityParams | None = None) -> dict[str, FoamFileSpec]:
    """Build the dictionary set for the OpenFOAM cavity reference case.

    Note on skipped tutorial files:
    - system/PDRblockMeshDict is skipped because it is an alternative mesh definition for PDRblockMesh.
    - system/decomposeParDict is skipped because it is only needed for parallel runs and will be added by a later task.

    Args:
        params: Simulation parameters. If None, default CavityParams is used.

    Returns:
        Mapping of relative file paths to their FoamFileSpec objects.
    """
    if params is None:
        params = CavityParams()

    return {
        "system/controlDict": FoamFileSpec(
            content={
                "application": "icoFoam",
                "startFrom": "startTime",
                "startTime": 0,
                "stopAt": "endTime",
                "endTime": params.end_time,
                "deltaT": params.delta_t,
                "writeControl": "timeStep",
                "writeInterval": params.write_interval,
                "purgeWrite": 0,
                "writeFormat": "ascii",
                "writePrecision": 6,
                "writeCompression": False,
                "timeFormat": "general",
                "timePrecision": 6,
                "runTimeModifiable": True,
            },
            class_name="dictionary",
        ),
        "system/fvSchemes": FoamFileSpec(
            content={
                "ddtSchemes": {
                    "default": "Euler",
                },
                "gradSchemes": {
                    "default": ("Gauss", "linear"),
                    "grad(p)": ("Gauss", "linear"),
                },
                "divSchemes": {
                    "default": "none",
                    "div(phi,U)": ("Gauss", "linear"),
                },
                "laplacianSchemes": {
                    "default": ("Gauss", "linear", "orthogonal"),
                },
                "interpolationSchemes": {
                    "default": "linear",
                },
                "snGradSchemes": {
                    "default": "orthogonal",
                },
            },
            class_name="dictionary",
        ),
        "system/fvSolution": FoamFileSpec(
            content={
                "solvers": {
                    "p": {
                        "solver": "PCG",
                        "preconditioner": "DIC",
                        "tolerance": 1e-06,
                        "relTol": 0.05,
                    },
                    "pFinal": {
                        "solver": "PCG",
                        "preconditioner": "DIC",
                        "tolerance": 1e-06,
                        "relTol": 0,
                    },
                    "U": {
                        "solver": "smoothSolver",
                        "smoother": "symGaussSeidel",
                        "tolerance": 1e-05,
                        "relTol": 0,
                    },
                },
                "PISO": {
                    "nCorrectors": 2,
                    "nNonOrthogonalCorrectors": 0,
                    "pRefCell": 0,
                    "pRefValue": 0,
                },
            },
            class_name="dictionary",
        ),
        "system/blockMeshDict": FoamFileSpec(
            content={
                "scale": 0.1,
                "vertices": [
                    [0, 0, 0],
                    [1, 0, 0],
                    [1, 1, 0],
                    [0, 1, 0],
                    [0, 0, 0.1],
                    [1, 0, 0.1],
                    [1, 1, 0.1],
                    [0, 1, 0.1],
                ],
                "blocks": [
                    "hex",
                    [0, 1, 2, 3, 4, 5, 6, 7],
                    [params.cells_x, params.cells_y, 1],
                    "simpleGrading",
                    [1, 1, 1],
                ],
                "edges": [],
                "boundary": [
                    (
                        "movingWall",
                        {
                            "type": "wall",
                            "faces": [[3, 7, 6, 2]],
                        },
                    ),
                    (
                        "fixedWalls",
                        {
                            "type": "wall",
                            "faces": [
                                [0, 4, 7, 3],
                                [2, 6, 5, 1],
                                [1, 5, 4, 0],
                            ],
                        },
                    ),
                    (
                        "frontAndBack",
                        {
                            "type": "empty",
                            "faces": [
                                [0, 3, 2, 1],
                                [4, 5, 6, 7],
                            ],
                        },
                    ),
                ],
            },
            class_name="dictionary",
        ),
        "constant/transportProperties": FoamFileSpec(
            content={
                "nu": params.nu,
            },
            class_name="dictionary",
        ),
        "0/p": FoamFileSpec(
            content={
                "dimensions": [0, 2, -2, 0, 0, 0, 0],
                "internalField": 0.0,
                "boundaryField": {
                    "movingWall": {
                        "type": "zeroGradient",
                    },
                    "fixedWalls": {
                        "type": "zeroGradient",
                    },
                    "frontAndBack": {
                        "type": "empty",
                    },
                },
            },
            class_name="volScalarField",
        ),
        "0/U": FoamFileSpec(
            content={
                "dimensions": [0, 1, -1, 0, 0, 0, 0],
                "internalField": [0.0, 0.0, 0.0],
                "boundaryField": {
                    "movingWall": {
                        "type": "fixedValue",
                        "value": [params.lid_velocity, 0.0, 0.0],
                    },
                    "fixedWalls": {
                        "type": "noSlip",
                    },
                    "frontAndBack": {
                        "type": "empty",
                    },
                },
            },
            class_name="volVectorField",
        ),
    }
