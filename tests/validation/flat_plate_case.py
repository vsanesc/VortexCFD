"""2D zero-pressure-gradient turbulent flat plate for the validation: mesh from blockMesh (not
from the app's snappy path), everything else from foam/physics_case.py (the app's own builder).

Geometry (x streamwise, z wall-normal, y one empty cell): a slip leading section upstream of the
leading edge, then the plate (no-slip wall) from x = 0. The wall-normal grading starts with the
first cell height of the y+ estimator.
"""

from dataclasses import dataclass
from pathlib import Path

from vortexcfd.core.model import Inflow, Physics, Solvers
from vortexcfd.foam.case_writer import FoamFileSpec, write_case
from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files, inlet_turbulence
from vortexcfd.foam.yplus import first_layer_thickness

RESIDUAL_TARGET = 1e-5
MAX_ITERATIONS = 3000
THICKNESS_Y = 0.01  # the single empty cell


@dataclass(frozen=True)
class PlateSetup:
    """A flat-plate case: geometry, resolution and free stream (physical set-up, not app numerics).

    Defaults are Case A (low Re): U = 10 m/s, 2 m plate, Re_L = 1.3e6, free stream from the app's
    defaults (I = 1 %, viscosity ratio 10), first cell from the y+ estimator with target 2 at L.
    """

    speed: float = 10.0
    nu: float = 1.5e-5
    plate_length: float = 2.0
    slip_length: float = 0.3  # slip section upstream of the leading edge
    height: float = 0.5
    cells_plate: int = 200
    cells_slip: int = 30
    cells_normal: int = 100
    x_grading: float = 1.0  # last / first cell length along the plate (> 1 coarsens downstream)
    intensity: float = 0.01
    viscosity_ratio: float = 10.0
    yplus_target: float = 2.0  # estimator target: the cell-CENTRE y+ is about half of it at yplus_length
    yplus_length: float = 2.0  # the station (length) at which the estimator is evaluated
    max_iterations: int = MAX_ITERATIONS


CASE_A = PlateSetup()
# Case B: TMR-like, Re = 5e6 per metre, Re_L = 1e7, Menter's SST free stream (see the README).
CASE_B = PlateSetup(
    speed=75.0, slip_length=0.3, height=1.0, cells_plate=300, cells_slip=30, cells_normal=150,
    x_grading=10.0,
    intensity=(1.5e-6 * 75.0**2 / 1.5) ** 0.5 / 75.0,  # k = 1e-6 U^2 = 1.5 (U I)^2
    viscosity_ratio=1.0,  # omega = 5 U / L = 375 1/s then gives nut / nu = k / (omega nu) = 1.0
    yplus_target=2.0, yplus_length=1.0,  # cell-centre y+ about 1 at x = 1 m
)


@dataclass(frozen=True)
class PlateCase:
    case_dir: Path
    first_cell: float  # first wall-normal cell height, metres
    grading: float  # last / first cell height ratio in the wall-normal direction
    expansion: float  # cell-to-cell growth ratio
    setup: PlateSetup = CASE_A


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


def first_cell_height(setup: PlateSetup) -> float:
    return first_layer_thickness(setup.yplus_target, setup.speed, setup.nu, setup.yplus_length)


def block_mesh_dict(setup: PlateSetup = CASE_A) -> FoamFileSpec:
    first = first_cell_height(setup)
    r = growth_ratio(first, setup.height, setup.cells_normal)
    grading = r ** (setup.cells_normal - 1)
    xs = [-setup.slip_length, 0.0, setup.plate_length]

    def vid(ix: int, iy: int, iz: int) -> int:
        return ix * 4 + iy * 2 + iz

    vertices = [[xs[ix], THICKNESS_Y * iy, setup.height * iz]
                for ix in range(3) for iy in range(2) for iz in range(2)]
    blocks: list = []
    for ix, nx, gx in ((0, setup.cells_slip, 1.0 / setup.x_grading), (1, setup.cells_plate, setup.x_grading)):
        corners = [vid(ix, 0, 0), vid(ix + 1, 0, 0), vid(ix + 1, 1, 0), vid(ix, 1, 0),
                   vid(ix, 0, 1), vid(ix + 1, 0, 1), vid(ix + 1, 1, 1), vid(ix, 1, 1)]
        blocks += ["hex", corners, [nx, 1, setup.cells_normal], "simpleGrading", [gx, 1, grading]]

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


def build_plate_case(case_dir: Path, setup: PlateSetup = CASE_A) -> PlateCase:
    """Write the case: blockMeshDict from this module, every solver file from the app's builder
    (sides become `empty` for the 2D case; the stopping criterion is the app's residualControl)."""
    inp = SolverCaseInput(
        physics=Physics(nu=setup.nu),
        inflow=Inflow(speed=setup.speed, turbulence_intensity=setup.intensity,
                      viscosity_ratio=setup.viscosity_ratio),
        solvers=Solvers(iterations=setup.max_iterations, write_interval=setup.max_iterations,
                        residual_p=RESIDUAL_TARGET, residual_u=RESIDUAL_TARGET,
                        residual_k=RESIDUAL_TARGET, residual_omega=RESIDUAL_TARGET),
        patches=("plate",), parts_bounds=(0.0, setup.plate_length, 0.0, THICKNESS_Y, 0.0, 0.0),
        symmetric=False,
    )
    files = build_solver_files(inp)
    for name in ("0/U", "0/p", "0/k", "0/omega", "0/nut"):
        files[name].content["boundaryField"]["sides"] = {"type": "empty"}
    files["system/blockMeshDict"] = block_mesh_dict(setup)
    write_case(case_dir, files)
    first = first_cell_height(setup)
    r = growth_ratio(first, setup.height, setup.cells_normal)
    return PlateCase(case_dir, first, r ** (setup.cells_normal - 1), r, setup)


@dataclass(frozen=True)
class PlateResult:
    x: "object"  # face-centre x of the plate patch
    cf: "object"  # local skin friction coefficient from wallShearStress
    yplus: "object"  # y+ of the first cell centre
    iterations: int  # iterations until the residualControl was met (or the limit)
    converged: bool
    wall_time_s: float


def latest_time_dir(case_dir: Path) -> Path:
    return max((d for d in case_dir.iterdir() if d.is_dir() and d.name.replace(".", "").isdigit()),
               key=lambda d: float(d.name))


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
    # A wall-resolved boundary-layer mesh legitimately trips the aspect ratio check (limit 1000).
    assert "Mesh OK" in check or (check.count("***") == 1 and "High aspect ratio" in check), check[-800:]
    t0 = time.monotonic()
    log = run(["simpleFoam"], "simpleFoam", timeout_s)
    wall = time.monotonic() - t0
    match = re.search(r"SIMPLE solution converged in (\d+) iterations", log)
    last = re.findall(r"^Time = (\d+)", log, re.MULTILINE)
    run(["simpleFoam", "-postProcess", "-func", "wallShearStress", "-latestTime"], "wallShearStress", 120)
    run(["postProcess", "-func", "writeCellCentres", "-latestTime"], "writeCellCentres", 120)
    latest = latest_time_dir(case.case_dir)

    def plate(field: str):
        return np.asarray(read_foam_file(latest / field)["boundaryField"]["plate"]["value"])

    tau = plate("wallShearStress")
    cf = np.linalg.norm(tau, axis=1) / (0.5 * case.setup.speed**2)  # kinematic shear / (0.5 U^2)
    return PlateResult(plate("C")[:, 0], cf, plate("yPlus"),
                       int(match.group(1)) if match else int(last[-1]), bool(match), wall)


def laws(x, setup: PlateSetup = CASE_A):
    """(Re_x, Cf = 0.0592 Re_x^-0.2, Cf = 0.455 / ln^2(0.06 Re_x)) at the positions ``x``."""
    import numpy as np

    re = setup.speed * np.asarray(x, dtype=float) / setup.nu
    return re, 0.0592 * re ** (-0.2), 0.455 / np.log(0.06 * np.maximum(re, 1.0)) ** 2


def diagnose(case: PlateCase, result: PlateResult, stations=(3e5, 6e5, 1e6, 1.3e6)) -> dict:
    """Diagnostics of a converged case: Cf against both laws with the sign of the error, the decay
    of the free stream between the inlet and the leading edge, and the maximum eddy viscosity ratio
    nut / nu in the boundary layer (over the cells of the column) at each station."""
    import numpy as np

    from vortexcfd.foam.dictfile import read_foam_file

    setup = case.setup
    latest = latest_time_dir(case.case_dir)

    def internal(name: str):
        return np.asarray(read_foam_file(latest / name)["internalField"])

    centres, k, omega, nut = internal("C"), internal("k"), internal("omega"), internal("nut")
    k_in, omega_in = inlet_turbulence(setup.speed, setup.intensity, setup.nu, setup.viscosity_ratio)
    # Free stream just upstream of the leading edge: the last cell column before x = 0, at 75 % of the
    # domain height (well above the boundary layer).
    col = np.isclose(centres[:, 0], centres[centres[:, 0] < 0][:, 0].max())
    idx = np.where(col)[0][np.argmin(np.abs(centres[col, 2] - 0.75 * setup.height))]
    rows = []
    for re in stations:
        i = int(np.argmin(np.abs(result.x - re * setup.nu / setup.speed)))
        xi = float(result.x[i])
        re_x, power, white = (float(v[0]) for v in laws([xi], setup))
        column = np.isclose(centres[:, 0], centres[np.argmin(np.abs(centres[:, 0] - xi)), 0])
        rows.append({
            "Re_x": re_x, "x": xi, "cf_sim": float(result.cf[i]), "cf_power": power, "cf_white": white,
            "err_power": float((result.cf[i] - power) / power), "err_white": float((result.cf[i] - white) / white),
            "nut_ratio_max": float(nut[column].max() / setup.nu),
        })
    return {
        "rows": rows, "k_in": k_in, "omega_in": omega_in,
        "k_le": float(k[idx]), "omega_le": float(omega[idx]),
        "k_decay": float(k[idx] / k_in), "omega_decay": float(omega[idx] / omega_in),
        "probe": (float(centres[idx, 0]), float(centres[idx, 2])),
    }
