"""2D zero-pressure-gradient turbulent flat plate for the validation: mesh from blockMesh (not
from the app's snappy path), everything else from foam/physics_case.py (the app's own builder).

Geometry (x streamwise, z wall-normal, y one empty cell): a slip leading section upstream of the
leading edge, then the plate (no-slip wall) from x = 0. The wall-normal grading starts with the
first cell height of the y+ estimator.
"""

import math
from dataclasses import dataclass, replace
from pathlib import Path

from vortexcfd.core.model import Inflow, Physics, ResidualCriterion, Solvers, StoppingCriteria
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
    defaults (I = 1 %, viscosity ratio 10), first cell from the y+ estimator with target 1 at the first
    cell centre at L (the wall-resolved requirement; D-107).
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
    # Estimator target at the first cell CENTRE at yplus_length (the app's convention since D-107). The recorded
    # study used target 2 with the target distance as the cell height, which is the same first cell: the
    # validation applies by equivalence (tests/test_flat_plate_grids.py).
    yplus_target: float = 1.0
    yplus_length: float = 2.0  # the station (length) at which the estimator is evaluated
    max_iterations: int = MAX_ITERATIONS
    first_cell: float | None = None  # explicit first wall-normal cell height (overrides the estimator)


CASE_A = PlateSetup()
# Case B: TMR-like, Re = 5e6 per metre, Re_L = 1e7, Menter's SST free stream (see the README). This is
# the coarse grid of the wall-normal grid study (CASE_B_GRIDS).
CASE_B = PlateSetup(
    speed=75.0, slip_length=0.3, height=1.0, cells_plate=300, cells_slip=30, cells_normal=128,
    x_grading=10.0,
    # (U I)^2 = 1e-6 U^2, so k = 1.5 (U I)^2 = 1.5e-6 U^2 = 8.4375e-3 m2/s2 (the earlier comment said
    # 1e-6 U^2; the case was always run with 8.4375e-3, written in 0/k).
    intensity=(1.5e-6 * 75.0**2 / 1.5) ** 0.5 / 75.0,
    viscosity_ratio=1.0,  # omega = k / nu = 562.5 1/s = 7.5 U / L, nut / nu = 1.0
    yplus_target=1.0, yplus_length=1.0,  # cell-centre y+ about 1 at x = 1 m
    max_iterations=10000,  # the finest grid needs about 5000 iterations to reach the residual targets
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
    if setup.first_cell is not None:
        return setup.first_cell
    return first_layer_thickness(setup.yplus_target, setup.speed, setup.nu, setup.yplus_length, "cell_centre")


def wall_normal_family(coarse: PlateSetup, levels: int = 3) -> list[PlateSetup]:
    """Nested wall-normal refinements of ``coarse`` (coarse first), streamwise cells unchanged.

    Each level splits every wall-normal cell of the previous one in two geometrically: twice the
    cells, growth ratio sqrt(r) and first cell h1 / (1 + sqrt(r)) (about half, so the first-cell y+
    halves too). The domain height is filled exactly, so the grids are nested and the refinement
    ratio is exactly 2 in the wall-normal direction.
    """
    family = [replace(coarse, first_cell=first_cell_height(coarse))]
    for _ in range(levels - 1):
        prev = family[-1]
        r = math.sqrt(growth_ratio(prev.first_cell, prev.height, prev.cells_normal))
        family.append(replace(prev, cells_normal=2 * prev.cells_normal, first_cell=prev.first_cell / (1 + r)))
    return family


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


def build_plate_case(case_dir: Path, setup: PlateSetup = CASE_A, k_wall: dict | None = None) -> PlateCase:
    """Write the case: blockMeshDict from this module, every solver file from the app's builder
    (sides become `empty` for the 2D case; the stop is the app's residual stopping criteria on p, U, k
    and omega combined with "all", D-058).

    ``k_wall`` replaces the plate's k boundary condition (wall-BC sensitivity diagnostics only; the
    app's default, kqRWallFunction, is used when it is None)."""
    inp = SolverCaseInput(
        physics=Physics(nu=setup.nu),
        inflow=Inflow(speed=setup.speed, turbulence_intensity=setup.intensity,
                      viscosity_ratio=setup.viscosity_ratio),
        solvers=Solvers(iterations=setup.max_iterations, write_interval=setup.max_iterations,
                        stopping=StoppingCriteria(criteria=[
                            ResidualCriterion(field=f, threshold=RESIDUAL_TARGET) for f in ("p", "U", "k", "omega")])),
        patches=("plate",), parts_bounds=(0.0, setup.plate_length, 0.0, THICKNESS_Y, 0.0, 0.0),
        symmetric=False,
    )
    files = build_solver_files(inp)
    for name in ("0/U", "0/p", "0/k", "0/omega", "0/nut"):
        files[name].content["boundaryField"]["sides"] = {"type": "empty"}
    if k_wall is not None:
        files["0/k"].content["boundaryField"]["plate"] = dict(k_wall)
    files["system/blockMeshDict"] = block_mesh_dict(setup)
    write_case(case_dir, files)
    first = first_cell_height(setup)
    r = growth_ratio(first, setup.height, setup.cells_normal)
    return PlateCase(case_dir, first, r ** (setup.cells_normal - 1), r, setup)


CASE_B_GRIDS = wall_normal_family(CASE_B)  # first-cell y+ about 1, 0.5, 0.25 (coarse first)


@dataclass(frozen=True)
class PlateResult:
    x: "object"  # face-centre x of the plate patch
    cf: "object"  # local skin friction coefficient from wallShearStress
    yplus: "object"  # y+ of the first cell centre
    iterations: int  # iterations until the residual criteria were met (or the limit)
    converged: bool
    wall_time_s: float


def latest_time_dir(case_dir: Path) -> Path:
    return max((d for d in case_dir.iterdir() if d.is_dir() and d.name.replace(".", "").isdigit()),
               key=lambda d: float(d.name))


def run_plate_case(case: PlateCase, timeout_s: float = 600.0) -> PlateResult:
    """blockMesh, checkMesh, simpleFoam to convergence, then wallShearStress and cell centres."""
    import time

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
    run(["simpleFoam"], "simpleFoam", timeout_s)
    wall = time.monotonic() - t0
    run(["simpleFoam", "-postProcess", "-func", "wallShearStress", "-latestTime"], "wallShearStress", 120)
    run(["postProcess", "-func", "writeCellCentres", "-latestTime"], "writeCellCentres", 120)
    return read_plate_result(case, wall)


def read_plate_result(case: PlateCase, wall_time_s: float | None = None) -> PlateResult:
    """The result of a finished case (simpleFoam, wallShearStress and writeCellCentres have run):
    Cf, y+ and face centres at the latest time, iterations from log.simpleFoam. Without
    ``wall_time_s`` the last ClockTime of the log is used."""
    import re

    import numpy as np

    from vortexcfd.foam.dictfile import read_foam_file

    from vortexcfd.foam.logparse import parse_log_text

    log = (case.case_dir / "log.simpleFoam").read_text()
    met = parse_log_text(log).criteria_met  # runTimeControl stopped the run (D-058)
    last = re.findall(r"^Time = (\d+)", log, re.MULTILINE)
    if wall_time_s is None:
        wall_time_s = float(re.findall(r"ClockTime = ([\d.]+) s", log)[-1])
    latest = latest_time_dir(case.case_dir)

    def plate(field: str):
        return np.asarray(read_foam_file(latest / field)["boundaryField"]["plate"]["value"])

    tau = plate("wallShearStress")
    cf = np.linalg.norm(tau, axis=1) / (0.5 * case.setup.speed**2)  # kinematic shear / (0.5 U^2)
    return PlateResult(plate("C")[:, 0], cf, plate("yPlus"),
                       int(met.after) if met and met.after else int(last[-1]), met is not None, wall_time_s)


def case_matches(case_dir: Path, setup: PlateSetup, k_wall: dict | None = None) -> bool:
    """True when ``case_dir`` holds a finished run of exactly this set-up: every file the builder
    writes (system/, constant/, 0/) is identical to a fresh build, and the post-processing ran."""
    import filecmp
    import tempfile

    if not (case_dir / "log.writeCellCentres").is_file():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        fresh = build_plate_case(Path(tmp) / "case", setup, k_wall=k_wall).case_dir
        files = [f.relative_to(fresh) for f in fresh.rglob("*") if f.is_file()]
        return all((case_dir / f).is_file() and filecmp.cmp(fresh / f, case_dir / f, shallow=False)
                   for f in files)


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


def cf_at(result: PlateResult, x: float) -> float:
    """Cf linearly interpolated between the plate face centres at ``x``."""
    import numpy as np

    order = np.argsort(result.x)
    return float(np.interp(x, result.x[order], result.cf[order]))


def boundary_layer_cells(case: PlateCase, x: float) -> tuple[float, int]:
    """(delta99, number of cells below it) in the cell column nearest to ``x``: delta99 is the first
    cell-centre height where Ux reaches 0.99 U (latest time; needs the written cell centres)."""
    import numpy as np

    from vortexcfd.foam.dictfile import read_foam_file

    latest = latest_time_dir(case.case_dir)
    centres = np.asarray(read_foam_file(latest / "C")["internalField"])
    u = np.asarray(read_foam_file(latest / "U")["internalField"])
    column = np.isclose(centres[:, 0], centres[np.argmin(np.abs(centres[:, 0] - x)), 0])
    z, ux = centres[column, 2], u[column, 0]
    order = np.argsort(z)
    z, ux = z[order], ux[order]
    i = int(np.argmax(ux >= 0.99 * case.setup.speed))
    return float(z[i]), i + 1
