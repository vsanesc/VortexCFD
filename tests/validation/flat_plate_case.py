"""2D zero-pressure-gradient turbulent flat plate for the validation: mesh from blockMesh (not
from the app's snappy path), everything else from foam/physics_case.py (the app's own builder).

Geometry (x streamwise, z wall-normal, y one empty cell): a slip leading section from
x = -0.3 to 0 and the plate (no-slip wall) from x = 0 to 2 m. U = 10 m/s, nu = 1.5e-5, so
Re_L = 1.33e6. The wall-normal grading starts with the first cell height of the y+ estimator.
"""

from dataclasses import dataclass
from pathlib import Path

from vortexcfd.core.model import Inflow, Physics, Solvers
from vortexcfd.foam.case_writer import FoamFileSpec, write_case
from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files
from vortexcfd.foam.yplus import first_layer_thickness

PLATE_LENGTH = 2.0
SLIP_LENGTH = 0.3
HEIGHT = 0.5  # domain height, > 10 boundary layer thicknesses (delta ~ 0.044 m at x = 2 m)
SPEED = 10.0
NU = 1.5e-5
CELLS_PLATE = 200
CELLS_SLIP = 30
CELLS_WALL_NORMAL = 100
THICKNESS_Y = 0.01  # the single empty cell
TARGET_YPLUS = 2.0  # estimator target: cell-CENTRE y+ is then about 1 at the plate end
RESIDUAL_TARGET = 1e-5
MAX_ITERATIONS = 3000


@dataclass(frozen=True)
class PlateSetup:
    """The case's mesh resolution and free-stream turbulence (physical setup, not app numerics)."""

    cells_plate: int = CELLS_PLATE
    cells_slip: int = CELLS_SLIP
    cells_normal: int = CELLS_WALL_NORMAL
    intensity: float = 0.01  # the app's default Inflow values
    viscosity_ratio: float = 10.0


@dataclass(frozen=True)
class PlateCase:
    case_dir: Path
    first_cell: float  # first wall-normal cell height, metres
    grading: float  # last / first cell height ratio in the wall-normal direction
    expansion: float  # cell-to-cell growth ratio


def growth_ratio(first: float, total: float, n: int) -> float:
    """Cell-to-cell ratio r with first * (r^n - 1) / (r - 1) = total (bisection)."""
    lo, hi = 1.0 + 1e-9, 2.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if first * (mid**n - 1) / (mid - 1) > total:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def block_mesh_dict(first: float, setup: PlateSetup = PlateSetup()) -> FoamFileSpec:
    r = growth_ratio(first, HEIGHT, setup.cells_normal)
    grading = r ** (setup.cells_normal - 1)
    xs = [-SLIP_LENGTH, 0.0, PLATE_LENGTH]

    def vid(ix: int, iy: int, iz: int) -> int:
        return ix * 4 + iy * 2 + iz

    vertices = [[xs[ix], THICKNESS_Y * iy, HEIGHT * iz] for ix in range(3) for iy in range(2) for iz in range(2)]
    blocks: list = []
    for ix, nx in ((0, setup.cells_slip), (1, setup.cells_plate)):
        corners = [vid(ix, 0, 0), vid(ix + 1, 0, 0), vid(ix + 1, 1, 0), vid(ix, 1, 0),
                   vid(ix, 0, 1), vid(ix + 1, 0, 1), vid(ix + 1, 1, 1), vid(ix, 1, 1)]
        blocks += ["hex", corners, [nx, 1, setup.cells_normal], "simpleGrading", [1, 1, grading]]

    def face(ix: int, kind: str) -> list[int]:
        v = lambda a, b, c: vid(ix + a, b, c)  # noqa: E731
        return {
            "xmin": [v(0, 0, 0), v(0, 0, 1), v(0, 1, 1), v(0, 1, 0)],
            "xmax": [v(1, 0, 0), v(1, 1, 0), v(1, 1, 1), v(1, 0, 1)],
            "zmin": [v(0, 0, 0), v(0, 1, 0), v(1, 1, 0), v(1, 0, 0)],
            "zmax": [v(0, 0, 1), v(1, 0, 1), v(1, 1, 1), v(0, 1, 1)],
            "ymin": [v(0, 0, 0), v(1, 0, 0), v(1, 0, 1), v(0, 0, 1)],
            "ymax": [v(0, 1, 0), v(0, 1, 1), v(1, 1, 1), v(1, 1, 0)],
        }[kind]

    return FoamFileSpec(content={
        "scale": 1,
        "vertices": vertices,
        "blocks": blocks,
        "edges": [],
        "boundary": [
            ("inlet", {"type": "patch", "faces": [face(0, "xmin")]}),
            ("outlet", {"type": "patch", "faces": [face(1, "xmax")]}),
            ("top", {"type": "patch", "faces": [face(0, "zmax"), face(1, "zmax")]}),
            ("bottom", {"type": "patch", "faces": [face(0, "zmin")]}),
            ("plate", {"type": "wall", "faces": [face(1, "zmin")]}),
            ("sides", {"type": "empty", "faces": [face(0, "ymin"), face(1, "ymin"), face(0, "ymax"), face(1, "ymax")]}),
        ],
        "mergePatchPairs": [],
    })


def build_plate_case(case_dir: Path, iterations: int = MAX_ITERATIONS, setup: PlateSetup = PlateSetup()) -> PlateCase:
    """Write the case: blockMeshDict from this module, every solver file from the app's builder
    (sides become `empty` for the 2D case; residualControl is added as the stopping criterion)."""
    first = first_layer_thickness(TARGET_YPLUS, SPEED, NU, PLATE_LENGTH)
    inp = SolverCaseInput(
        physics=Physics(nu=NU), inflow=Inflow(speed=SPEED, turbulence_intensity=setup.intensity,
                                                    viscosity_ratio=setup.viscosity_ratio), solvers=Solvers(iterations=iterations,
                                                                            write_interval=iterations),
        patches=("plate",), parts_bounds=(0.0, PLATE_LENGTH, 0.0, THICKNESS_Y, 0.0, 0.0), symmetric=False,
    )
    files = build_solver_files(inp)
    for name in ("0/U", "0/p", "0/k", "0/omega", "0/nut"):
        files[name].content["boundaryField"]["sides"] = {"type": "empty"}
    solution = files["system/fvSolution"].content
    solution["SIMPLE"] = dict(solution["SIMPLE"], residualControl={
        "p": RESIDUAL_TARGET, "U": RESIDUAL_TARGET, "k": RESIDUAL_TARGET, "omega": RESIDUAL_TARGET})
    files["system/blockMeshDict"] = block_mesh_dict(first, setup)
    write_case(case_dir, files)
    r = growth_ratio(first, HEIGHT, setup.cells_normal)
    return PlateCase(case_dir, first, r ** (setup.cells_normal - 1), r)


@dataclass(frozen=True)
class PlateResult:
    x: "object"  # face-centre x of the plate patch
    cf: "object"  # local skin friction coefficient from wallShearStress
    yplus: "object"  # y+ of the first cell centre
    iterations: int  # iterations until the residualControl was met (or the limit)
    converged: bool
    wall_time_s: float


def run_plate_case(case: PlateCase, timeout_s: float = 600.0) -> PlateResult:
    """blockMesh, checkMesh, simpleFoam to convergence, then wallShearStress and cell centres."""
    import re
    import time

    import numpy as np

    from vortexcfd.foam.dictfile import read_foam_file
    from vortexcfd.foam.runner import FoamRun

    def run(command: list[str], name: str, timeout: float) -> str:
        r = FoamRun()
        r.start(command, case.case_dir, case.case_dir / f"log.{name}", timeout_s=timeout)
        r.wait(timeout + 10)
        res = r.result()
        text = (case.case_dir / f"log.{name}").read_text()
        assert res.exit_code == 0 and not res.timed_out, f"{name} failed ({res.exit_code}):\n{text[-1500:]}"
        return text

    run(["blockMesh"], "blockMesh", 120)
    check = run(["checkMesh"], "checkMesh", 120)
    assert "Mesh OK" in check
    t0 = time.monotonic()
    log = run(["simpleFoam"], "simpleFoam", timeout_s)
    wall = time.monotonic() - t0
    match = re.search(r"SIMPLE solution converged in (\d+) iterations", log)
    last = re.findall(r"^Time = (\d+)", log, re.MULTILINE)
    run(["simpleFoam", "-postProcess", "-func", "wallShearStress", "-latestTime"], "wallShearStress", 120)
    run(["postProcess", "-func", "writeCellCentres", "-latestTime"], "writeCellCentres", 120)
    latest = max((d for d in case.case_dir.iterdir() if d.is_dir() and d.name.replace(".", "").isdigit()),
                 key=lambda d: float(d.name))

    def plate(field: str):
        return np.asarray(read_foam_file(latest / field)["boundaryField"]["plate"]["value"])

    tau = plate("wallShearStress")
    cf = np.linalg.norm(tau, axis=1) / (0.5 * SPEED**2)  # kinematic shear / (0.5 U^2)
    return PlateResult(plate("C")[:, 0], cf, plate("yPlus"),
                       int(match.group(1)) if match else int(last[-1]), bool(match), wall)


def correlation(x):
    """Cf = 0.0592 Re_x^(-0.2) and Re_x."""
    import numpy as np

    re = SPEED * np.asarray(x) / NU
    return 0.0592 * re ** (-0.2), re
