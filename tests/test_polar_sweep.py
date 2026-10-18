"""Angle-of-attack sweep (D-067): alpha lists, the point sequence with a fake solver, the
initialisation of a point from the previous converged one, the record and the CSV."""

import csv
import shutil
from pathlib import Path

import pytest

from vortexcfd.core.model import Inflow, Physics, PolarSweepSettings, Solvers
from vortexcfd.foam.dictfile import read_foam_file, write_foam_file
from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files
from vortexcfd.foam.polar_sweep import (
    CRITERIA_MET,
    SweepRun,
    copy_mesh,
    export_csv,
    initialise_from,
    latest_time,
    new_record,
    point_dir,
    read_record,
)
from vortexcfd.foam.solver_run import CRASHED, ITERATION_LIMIT, STOPPED, SolverRunResult

DATA = Path(__file__).parent / "data"


def test_alpha_lists() -> None:
    assert PolarSweepSettings(start=0, end=10, step=5).alphas() == [0, 5, 10]
    assert PolarSweepSettings(start=-4, end=4, step=3).alphas() == [-4, -1, 2]
    assert PolarSweepSettings(start=10, end=0, step=5).alphas() == [10, 5, 0]
    assert PolarSweepSettings(start=0, end=1, step=0.1).alphas()[-1] == pytest.approx(1.0)
    assert PolarSweepSettings(mode="list", values=[4, -2, 8]).alphas() == [4, -2, 8]
    with pytest.raises(ValueError):
        PolarSweepSettings(values=[95])
    with pytest.raises(ValueError):
        PolarSweepSettings(step=0)


def _coefficient_file(case: Path, cd: float, cl: float, cm: float) -> None:
    folder = case / "postProcessing" / "forceCoeffs1" / "0"
    folder.mkdir(parents=True)
    (folder / "coefficient.dat").write_text(
        "# Time\tCd\tCd(f)\tCd(r)\tCl\tCl(f)\tCl(r)\tCmPitch\tCmRoll\tCmYaw\tCs\tCs(f)\tCs(r)\n"
        f"1\t{cd}\t0\t0\t{cl}\t0\t0\t{cm}\t0\t0\t0\t0\t0\n")


class FakeSolver:
    """Writes a coefficient file and a latest time directory; states per point."""

    states: list[str] = []
    alphas: list[float] = []
    created: list["FakeSolver"] = []
    hold_index: int | None = None

    def __init__(self, case, **kwargs):
        self.case, self.kwargs = Path(case), kwargs
        self.index = len(FakeSolver.created)
        self.stop = False
        FakeSolver.created.append(self)
        self.zero_u = read_foam_file(self.case / "0" / "U")  # what the point started from

    def start(self):
        pass

    def request_stop(self):
        self.stop = True

    def wait(self, timeout=None):
        import time

        if FakeSolver.hold_index == self.index:
            deadline = time.monotonic() + 10
            while not self.stop and time.monotonic() < deadline:
                time.sleep(0.01)
        state = STOPPED if self.stop else FakeSolver.states[self.index]
        if state != CRASHED:
            alpha = FakeSolver.alphas[self.index]
            _coefficient_file(self.case, 0.1 + 0.01 * alpha, 0.1 * alpha, -0.01 * alpha)
            latest = self.case / "20"
            latest.mkdir()
            for name in ("U", "p", "k", "omega", "nut"):
                shutil.copy(DATA / "results_case" / "5" / name, latest / name)
        return SolverRunResult(state, 0 if state != CRASHED else 1, 20, duration_s=0.5)


def _writer(calls: list):
    def write(case: Path, alpha: float) -> None:
        calls.append((case.name, alpha))
        (case / "0").mkdir(parents=True, exist_ok=True)
        for name in ("U", "p", "k", "omega", "nut"):
            shutil.copy(DATA / "results_case" / "0" / name, case / "0" / name)
    return write


def _sweep(tmp_path: Path, alphas, states, init=True, hold=None):
    (tmp_path / "mesh" / "polyMesh").mkdir(parents=True)
    FakeSolver.states, FakeSolver.alphas, FakeSolver.created, FakeSolver.hold_index = states, list(alphas), [], hold
    calls = []
    run = SweepRun(tmp_path, new_record(alphas, 2, init), _writer(calls), solver_run_factory=FakeSolver)
    return run, calls


def test_points_run_in_order_and_flagged_points_are_kept(tmp_path: Path) -> None:
    run, calls = _sweep(tmp_path, [0.0, 5.0, 10.0], [CRITERIA_MET, ITERATION_LIMIT, CRASHED])
    run.start()
    rec = run.wait(10)
    assert rec.status == "finished"
    assert [c[1] for c in calls] == [0.0, 5.0, 10.0]
    assert [p.state for p in rec.points] == [CRITERIA_MET, ITERATION_LIMIT, CRASHED]
    assert [p.flagged for p in rec.points] == [False, True, True]
    assert rec.points[1].cl == pytest.approx(0.5) and rec.points[1].cd == pytest.approx(0.15)
    assert rec.points[1].lift_to_drag == pytest.approx(0.5 / 0.15)
    assert rec.points[2].cl is None  # crashed: no coefficients
    assert all(s.kwargs["cores"] == 2 for s in FakeSolver.created)
    assert (point_dir(tmp_path, 0) / "constant" / "polyMesh").is_symlink()
    assert read_record(tmp_path) == rec
    out = tmp_path / "polar.csv"
    export_csv(rec, out)
    rows = list(csv.reader(out.open()))
    assert rows[0] == ["alpha_deg", "CL", "CD", "CM", "L_D", "iterations", "status", "criteria_met", "initialised_from"]
    assert rows[2][6] == "Iteration limit" and rows[2][7] == "false" and rows[3][1] == ""


def test_each_point_starts_from_the_last_converged_point(tmp_path: Path) -> None:
    """Point 2 starts from point 1 (criteria met); point 3 too, because point 2 only reached the
    iteration limit; with the option off every point starts from the free stream."""
    run, _ = _sweep(tmp_path, [0.0, 5.0, 10.0], [CRITERIA_MET, ITERATION_LIMIT, CRITERIA_MET])
    run.start()
    rec = run.wait(10)
    assert [p.initialised_from for p in rec.points] == [None, "point_1 at time 20", "point_1 at time 20"]
    started = [s.zero_u["internalField"] for s in FakeSolver.created]
    import numpy as np

    assert np.asarray(started[1]).shape == (128, 3)  # the previous point's field
    assert np.asarray(started[0]).size == 3  # uniform free stream
    run2, _ = _sweep(tmp_path / "off", [0.0, 5.0], [CRITERIA_MET, CRITERIA_MET], init=False)
    run2.start()
    assert [p.initialised_from for p in run2.wait(10).points] == [None, None]


def test_initialise_keeps_the_new_boundary_conditions(tmp_path: Path) -> None:
    """The new 0/U gets the previous internal field and keeps its own inlet (the new direction)."""
    prev = tmp_path / "prev"
    shutil.copytree(DATA / "results_case", prev)
    case = tmp_path / "case"
    inp = SolverCaseInput(Physics(), Inflow(alpha_deg=10.0), Solvers(), ("Sphere",), (-0.5, 0.5, -0.5, 0.5, -0.5, 0.5))
    for rel, spec in build_solver_files(inp).items():
        write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    assert latest_time(prev) == "5"
    assert initialise_from(prev, case) == "5"
    u = read_foam_file(case / "0" / "U")
    previous = read_foam_file(prev / "5" / "U")
    import numpy as np

    assert np.allclose(np.asarray(u["internalField"]), np.asarray(previous["internalField"]))
    inlet = np.asarray(u["boundaryField"]["inlet"]["value"])
    assert inlet.ravel()[:3] == pytest.approx([20 * np.cos(np.radians(10)), 0, 20 * np.sin(np.radians(10))])
    assert initialise_from(tmp_path / "missing", case) is None


def test_stop_ends_the_current_point_and_the_sweep(tmp_path: Path) -> None:
    import time

    run, calls = _sweep(tmp_path, [0.0, 5.0, 10.0], [CRITERIA_MET] * 3, hold=1)
    run.start()
    deadline = time.monotonic() + 10
    while len(FakeSolver.created) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    run.request_stop()
    rec = run.wait(10)
    assert rec.status == "stopped"
    assert [p.state for p in rec.points] == [CRITERIA_MET, STOPPED, None]
    assert len(calls) == 2


def test_point_labels_name_the_criteria(tmp_path: Path) -> None:
    from vortexcfd.core.model import AsymptoticCriterion, StoppingCriteria

    class MetSolver(FakeSolver):
        def wait(self, timeout=None):
            result = super().wait(timeout)
            result.criteria_met = ("c1_asymptotic_Cd",)
            return result

    (tmp_path / "mesh" / "polyMesh").mkdir(parents=True)
    FakeSolver.states, FakeSolver.alphas, FakeSolver.created, FakeSolver.hold_index = [CRITERIA_MET], [2.0], [], None
    run = SweepRun(tmp_path, new_record([2.0], 1, True), _writer([]), solver_run_factory=MetSolver,
                   stopping=StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd")]))
    run.start()
    assert run.wait(10).points[0].state_label == "Criteria met: Cd asymptotic"


def test_copy_mesh(tmp_path: Path) -> None:
    src = tmp_path / "case" / "constant" / "polyMesh"
    src.mkdir(parents=True)
    (src / "points").write_text("x")
    copy_mesh(tmp_path / "case", tmp_path / "sweep")
    assert (tmp_path / "sweep" / "mesh" / "polyMesh" / "points").read_text() == "x"


# -- real sweep (marker long) ---------------------------------------------------------------------------

@pytest.mark.long
@pytest.mark.slow
def test_real_sweep_on_the_flattened_ellipsoid(tmp_path: Path) -> None:
    """The app's polar sweep on the flattened ellipsoid (semi-axes 0.5 x 0.5 x 0.15 m, default
    domain and mesh, meshed once in case/) at 20 m/s, alpha 0, 5, 10 deg, 4 cores, each point
    initialised from the previous converged one; stopping criteria Cd and Cl asymptotic (window 50,
    tolerance 1 %), limit 600 iterations. CL increases with alpha; prints the polar table.

        .venv/bin/pytest -m long -s tests/test_polar_sweep.py
    """
    from tests.real_cases import flattened_ellipsoid
    from vortexcfd.core.model import AsymptoticCriterion, Part, StoppingCriteria
    from vortexcfd.core.project import Project
    from vortexcfd.foam.mesh_run import MeshRun
    from vortexcfd.foam.polar_sweep import SweepRun
    from vortexcfd.gui.meshing import prepare_job
    from vortexcfd.gui.polar_sweep import point_writer, prepare_sweep

    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    flattened_ellipsoid().save(str(folder / "geometry" / "body.stl"))
    project = Project.new("sweep")
    project.add_part(Part(name="Body", source_file="geometry/body.stl", units="m"))
    project.save(folder / "p.json")
    stopping = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=50, tolerance=0.01),
                                          AsymptoticCriterion(quantity="Cl", window=50, tolerance=0.01)])
    project.update_solver(iterations=600, write_interval=600, stopping=stopping.model_dump())
    project.update_study("polar", mode="list", values=[0.0, 5.0, 10.0], cores=4, init_from_previous=True)
    job = prepare_job(project)
    mesh = MeshRun(job.case_dir, step_timeout_s=600, parts=job.inputs.parts)
    mesh.start()
    meshed = mesh.wait(1200)
    assert meshed is not None and meshed.success and meshed.report.valid
    case_files = sorted(p.name for p in job.case_dir.iterdir())
    sweep_dir, record = prepare_sweep(project)
    run = SweepRun(sweep_dir, record, point_writer(project), stopping=project.sim.solvers.stopping,
                   solver_timeout_s=1800)
    run.start()
    try:
        rec = run.wait(5400)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(120)
    assert rec is not None and rec.status == "finished", rec
    print(f"\n{meshed.report.cells} cells")
    print("| alpha [deg] | CL | CD | CM | L/D | Iterations | Status | Initialised from |")
    print("|---|---|---|---|---|---|---|---|")
    for p in rec.points:
        print(f"| {p.alpha:g} | {p.cl:.5g} | {p.cd:.5g} | {p.cm:.5g} | {p.lift_to_drag:.4g} | {p.iterations} | "
              f"{p.state_label} | {p.initialised_from or 'free stream'} |")
    cls = [p.cl for p in rec.points]
    assert cls[0] < cls[1] < cls[2]
    assert sorted(p.name for p in job.case_dir.iterdir()) == case_files  # case/ untouched
    assert (sweep_dir / "sweep.json").is_file()
