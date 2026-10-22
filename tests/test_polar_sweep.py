"""Angle-of-attack sweep (D-067, D-120): alpha lists, the point sequence with a fake mesher and a fake
solver (one mesh per angle), stop and resume, a failed mesh, the record and the CSV."""

import csv
import math
import shutil
import time
from pathlib import Path

import pytest

from vortexcfd.core.model import PolarSweepSettings
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.foam.mesh_run import MeshRunResult
from vortexcfd.foam.polar_sweep import (
    CRITERIA_MET,
    MESH_FAILED,
    SweepRun,
    export_csv,
    new_record,
    pending,
    point_dir,
    read_record,
    resume_record,
    write_record,
)
from vortexcfd.foam.solver_run import CRASHED, ITERATION_LIMIT, STOPPED, SolverRunResult


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


def _report(cells: int, ok: bool = True) -> MeshReport:
    return MeshReport(points=1, faces=1, cells=cells, max_non_orthogonality=10.0, avg_non_orthogonality=1.0,
                      max_skewness=1.0, failed_checks=0 if ok else 1, mesh_ok=ok,
                      failed_check_lines=() if ok else ("***Zero or negative cell volume detected.",))


class FakeMesher:
    """MeshRun's interface: records the case, its cores and first layer; ``bad`` cases fail checkMesh;
    ``hold`` (a point index) waits for a stop."""

    created: list["FakeMesher"] = []
    bad: set[str] = set()
    hold: str | None = None

    def __init__(self, case, **kwargs):
        self.case, self.kwargs, self.stop = Path(case), kwargs, False
        FakeMesher.created.append(self)

    def start(self):
        pass

    def request_stop(self):
        self.stop = True

    def wait(self, timeout=None):
        if FakeMesher.hold == self.case.name:
            deadline = time.monotonic() + 10
            while not self.stop and time.monotonic() < deadline:
                time.sleep(0.01)
            return MeshRunResult(False, True)
        ok = self.case.name not in FakeMesher.bad
        return MeshRunResult(True, False, report=_report(1000 + len(FakeMesher.created), ok))


def point_alpha(case: Path) -> float:
    """The angle of a point: the test writers' "alpha" file, else the body axes of the solver files (D-120)."""
    if (case / "alpha").is_file():
        return float((case / "alpha").read_text())
    from vortexcfd.foam.dictfile import read_foam_file

    drag = read_foam_file(case / "system" / "controlDict")["functions"]["forceCoeffsBody"]["dragDir"]
    return round(math.degrees(math.atan2(-float(drag[2]), float(drag[0]))), 9)


class FakeSolver:
    """Writes a coefficient file; states per alpha (``states``); ``hold`` (an alpha) waits for a stop."""

    states: dict[float, str] = {}
    created: list["FakeSolver"] = []
    hold: float | None = None

    def __init__(self, case, **kwargs):
        self.case, self.kwargs, self.stop = Path(case), kwargs, False
        self.alpha = point_alpha(self.case)
        FakeSolver.created.append(self)

    def start(self):
        pass

    def request_stop(self):
        self.stop = True

    def wait(self, timeout=None):
        if FakeSolver.hold == self.alpha:
            deadline = time.monotonic() + 10
            while not self.stop and time.monotonic() < deadline:
                time.sleep(0.01)
        state = STOPPED if self.stop else FakeSolver.states.get(self.alpha, CRITERIA_MET)
        if state != CRASHED:
            _coefficient_file(self.case, 0.1 + 0.01 * self.alpha, 0.1 * self.alpha, -0.01 * self.alpha)
        return SolverRunResult(state, 0 if state != CRASHED else 1, 20, duration_s=0.5)


def _reset(states=None, bad=(), mesh_hold=None, solve_hold=None):
    FakeMesher.created, FakeMesher.bad, FakeMesher.hold = [], set(bad), mesh_hold
    FakeSolver.created, FakeSolver.states, FakeSolver.hold = [], dict(states or {}), solve_hold


def _run(tmp_path: Path, record, calls: list, stopping=None, **kwargs) -> SweepRun:
    def prepare(case: Path, alpha: float) -> None:
        calls.append(("mesh", case.name, alpha))
        shutil.rmtree(case, ignore_errors=True)  # as point_preparer: a rerun point starts clean
        case.mkdir(parents=True)

    def write(case: Path, alpha: float) -> None:
        calls.append(("solve", case.name, alpha))
        (case / "alpha").write_text(repr(alpha))

    return SweepRun(tmp_path, record, prepare, write, stopping=stopping, parts=("wing",), mesh_run_factory=FakeMesher,
                    solver_run_factory=FakeSolver, **kwargs)


def _record(alphas, **kwargs):
    return new_record(alphas, 2, mesh_cores=6, inputs_hash="h1", planned_first_layer=(1e-5, 30), **kwargs)


def test_every_angle_is_meshed_then_solved_in_order(tmp_path: Path) -> None:
    _reset({5.0: ITERATION_LIMIT, 10.0: CRASHED})
    calls: list = []
    run = _run(tmp_path, _record([0.0, 5.0, 10.0]), calls)
    run.start()
    rec = run.wait(10)
    assert rec.status == "finished"
    assert calls == [("mesh", "point_1", 0.0), ("solve", "point_1", 0.0), ("mesh", "point_2", 5.0),
                     ("solve", "point_2", 5.0), ("mesh", "point_3", 10.0), ("solve", "point_3", 10.0)]
    assert [m.case for m in FakeMesher.created] == [point_dir(tmp_path, i) for i in range(3)]
    assert all(m.kwargs["cores"] == 6 and m.kwargs["first_layer"] == (1e-5, 30) and m.kwargs["parts"] == ("wing",)
               for m in FakeMesher.created)
    assert all(s.kwargs["cores"] == 2 for s in FakeSolver.created)
    assert [p.state for p in rec.points] == [CRITERIA_MET, ITERATION_LIMIT, CRASHED]
    assert [p.flagged for p in rec.points] == [False, True, True]
    assert [p.cells for p in rec.points] == [1001, 1002, 1003]
    assert rec.points[1].cl == pytest.approx(0.5) and rec.points[1].cd == pytest.approx(0.15)
    assert rec.points[2].cl is None  # crashed: no coefficients
    assert read_record(tmp_path) == rec
    out = tmp_path / "polar.csv"
    export_csv(rec, out)
    rows = list(csv.reader(out.open()))
    assert rows[0] == ["alpha_deg", "CL", "CD", "CM", "L_D", "iterations", "status", "criteria_met", "cells"]
    assert rows[2][6] == "Iteration limit" and rows[2][7] == "false" and rows[3][1] == "" and rows[1][8] == "1001"


def test_a_failed_mesh_is_recorded_and_the_sweep_goes_on(tmp_path: Path) -> None:
    _reset(bad={"point_2"})
    calls: list = []
    run = _run(tmp_path, _record([0.0, 5.0, 10.0]), calls)
    run.start()
    rec = run.wait(10)
    assert rec.status == "finished"
    assert [p.state for p in rec.points] == [CRITERIA_MET, MESH_FAILED, CRITERIA_MET]
    assert ("solve", "point_2", 5.0) not in calls and rec.points[1].error
    assert rec.points[1].flagged and rec.points[1].finished


def test_stop_while_solving_then_resume(tmp_path: Path) -> None:
    """A stop during the second angle's run ends the sweep; running it again keeps the first angle and meshes
    and solves only the second and third."""
    _reset(solve_hold=5.0)
    calls: list = []
    run = _run(tmp_path, _record([0.0, 5.0, 10.0]), calls)
    run.start()
    deadline = time.monotonic() + 10
    while len(FakeSolver.created) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    run.request_stop()
    rec = run.wait(10)
    assert rec.status == "stopped"
    assert [p.state for p in rec.points] == [CRITERIA_MET, STOPPED, None]
    assert [p.alpha for p in pending(rec)] == [5.0, 10.0]
    saved = read_record(tmp_path)
    resumed = resume_record(saved, _record([0.0, 5.0, 10.0]))
    assert resumed.points[0] == saved.points[0] and [p.alpha for p in pending(resumed)] == [5.0, 10.0]
    _reset()
    calls2: list = []
    run2 = _run(tmp_path, resumed, calls2)
    run2.start()
    rec2 = run2.wait(10)
    assert rec2.status == "finished"
    assert [c for c in calls2 if c[0] == "mesh"] == [("mesh", "point_2", 5.0), ("mesh", "point_3", 10.0)]
    assert [p.state for p in rec2.points] == [CRITERIA_MET] * 3
    assert rec2.points[0].cl == pytest.approx(0.0) and rec2.points[2].cl == pytest.approx(1.0)


def test_stop_while_meshing(tmp_path: Path) -> None:
    _reset(mesh_hold="point_2")
    calls: list = []
    run = _run(tmp_path, _record([0.0, 5.0]), calls)
    run.start()
    deadline = time.monotonic() + 10
    while len(FakeMesher.created) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    run.request_stop()
    rec = run.wait(10)
    assert rec.status == "stopped" and [p.state for p in rec.points] == [CRITERIA_MET, None]
    assert ("solve", "point_2", 5.0) not in calls


def test_resume_only_the_same_sweep() -> None:
    old = _record([0.0, 5.0])
    old.points[0].state = CRITERIA_MET
    assert resume_record(old, _record([0.0, 5.0])).points[0].state == CRITERIA_MET
    assert resume_record(old, _record([0.0, 6.0])).points[0].state is None  # other angles
    changed = new_record([0.0, 5.0], 2, mesh_cores=6, inputs_hash="h2")
    assert resume_record(old, changed) is changed  # other inputs
    assert resume_record(None, changed) is changed
    other_cores = new_record([0.0, 5.0], 4, inputs_hash="h1")
    assert resume_record(old, other_cores) is other_cores


def test_old_records_read(tmp_path: Path) -> None:
    """A record of the shared-mesh sweep (before D-120) still reads; its extra keys are dropped."""
    import json

    (tmp_path / "sweep.json").write_text(json.dumps({
        "alphas": [0.0], "cores": 1, "init_from_previous": True, "status": "finished",
        "points": [{"index": 0, "alpha": 0.0, "cl": 0.1, "state": "criteria_met", "initialised_from": None}]}))
    rec = read_record(tmp_path)
    assert rec is not None and rec.points[0].cl == 0.1 and rec.points[0].finished


def test_a_record_that_cannot_be_written_still_ends_the_sweep(tmp_path: Path, monkeypatch) -> None:
    """R-02: on_done is called even when sweep.json cannot be written."""
    from vortexcfd.foam import polar_sweep

    def broken(*a, **k):
        raise OSError(28, "No space left on device")

    _reset()
    monkeypatch.setattr(polar_sweep, "write_record", broken)
    done, said = [], []
    run = _run(tmp_path, _record([0.0]), [], on_done=done.append, on_line=said.append)
    run.start()
    out = run.wait(10)
    assert done == [out] and out.status == "failed" and FakeMesher.created == []
    assert any("No space left on device" in line for line in said)


def test_point_labels_name_the_criteria(tmp_path: Path) -> None:
    from vortexcfd.core.model import AsymptoticCriterion, StoppingCriteria

    class MetSolver(FakeSolver):
        def wait(self, timeout=None):
            result = super().wait(timeout)
            result.criteria_met = ("c1_asymptotic_Cd",)
            return result

    _reset()
    run = SweepRun(tmp_path, _record([2.0]), lambda case, a: case.mkdir(parents=True, exist_ok=True),
                   lambda case, a: (case / "alpha").write_text(repr(a)), mesh_run_factory=FakeMesher,
                   solver_run_factory=MetSolver, stopping=StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd")]))
    run.start()
    assert run.wait(10).points[0].state_label == "Criteria met: Cd asymptotic"
    write_record(tmp_path, run.record)


# -- real sweep (marker long) ---------------------------------------------------------------------------

@pytest.mark.long
@pytest.mark.slow
def test_real_sweep_on_the_flattened_ellipsoid(tmp_path: Path) -> None:
    """The app's polar sweep on the flattened ellipsoid (semi-axes 0.5 x 0.5 x 0.15 m, default domain and
    mesh) at 20 m/s, alpha 0, 5, 10 deg, one mesh per angle (the body rotated, D-120), 4 cores; stopping
    criteria Cd and Cl asymptotic (window 50, tolerance 1 %), limit 600 iterations. CL increases with alpha;
    prints the polar table. Not run by the agents (marker long).

        .venv/bin/pytest -m long -s tests/test_polar_sweep.py
    """
    from tests.real_cases import flattened_ellipsoid
    from vortexcfd.core.model import AsymptoticCriterion, Part, StoppingCriteria
    from vortexcfd.core.project import Project
    from vortexcfd.workflow import meshing
    from vortexcfd.workflow.polar_sweep import point_preparer, point_writer, prepare_sweep

    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    flattened_ellipsoid().save(str(folder / "geometry" / "body.stl"))
    project = Project.new("sweep")
    project.add_part(Part(name="Body", source_file="geometry/body.stl", units="m"))
    project.save(folder / "p.json")
    from vortexcfd.core.project_io import V9_MESH_BEHAVIOUR

    project.update_mesh(**V9_MESH_BEHAVIOUR)  # the set-up this sweep was designed with (D-085, D-086)
    stopping = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=50, tolerance=0.01),
                                          AsymptoticCriterion(quantity="Cl", window=50, tolerance=0.01)])
    project.update_solver(iterations=600, write_interval=600, stopping=stopping.model_dump())
    project.update_study("polar", mode="list", values=[0.0, 5.0, 10.0], cores=4)
    sweep_dir, record = prepare_sweep(project)
    run = SweepRun(sweep_dir, record, point_preparer(project), point_writer(project),
                   stopping=project.sim.solvers.stopping, parts=meshing.mesh_inputs(project)[0].patches,
                   solver_timeout_s=1800)
    run.start()
    try:
        rec = run.wait(5400)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(120)
    assert rec is not None and rec.status == "finished", rec
    print("| alpha [deg] | cells | CL | CD | CM | L/D | Iterations | Status |")
    print("|---|---|---|---|---|---|---|---|")
    for p in rec.points:
        print(f"| {p.alpha:g} | {p.cells} | {p.cl:.5g} | {p.cd:.5g} | {p.cm:.5g} | {p.lift_to_drag:.4g} | "
              f"{p.iterations} | {p.state_label} |")
    cls = [p.cl for p in rec.points]
    assert cls[0] < cls[1] < cls[2]
    assert not (folder / "case").exists()  # case/ untouched
