"""Angle-of-attack sweep (polar): points, record, CSV and the runner (no Qt). (D-067, D-120)
[NUMERICS-REVIEW]

The angle of attack rotates the parts (D-120), so every angle has its own mesh: point n is a marker-
protected case <project dir>/case_sweep/point_<n>/ (case/ is never touched) holding the meshing case of
the parts rotated to that angle (written by the caller, workflow/polar_sweep.py), then its mesh (MeshRun on
the record's meshing cores, D-111), the solver files of a normal run and the run itself from the uniform
free stream. The angles run one at a time, in order. Each point keeps its own case, results and record
entry. A stop ends the running step cleanly (the point is "stopped") and the sweep; running the same
sweep again resumes it: the points that finished (criteria met, iteration limit or crashed) are kept and
the others are meshed and run again (``resume_record``).
"""

import csv
import json
import math
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from vortexcfd.core.atomic_io import write_text_atomic

SWEEP_DIR_NAME = "case_sweep"
SWEEP_JSON = "sweep.json"


def point_dir(sweep_dir: Path, index: int) -> Path:
    return Path(sweep_dir) / f"point_{index + 1}"


# -- record ------------------------------------------------------------------------------------

CRITERIA_MET = "criteria_met"
STOPPED = "stopped"  # foam/solver_run.STOPPED
MESH_FAILED = "mesh_failed"  # the point's mesh is invalid or meshing failed: not solved
# A point in one of these states has its result: a resumed sweep keeps it.
FINISHED_STATES = ("criteria_met", "iteration_limit", "crashed", MESH_FAILED)


@dataclass
class SweepPoint:
    index: int
    alpha: float
    cl: float | None = None
    cd: float | None = None
    cm: float | None = None
    iterations: int | None = None
    state: str | None = None  # solver_run state, or MESH_FAILED; None until run
    state_label: str | None = None
    duration_s: float | None = None  # solver
    cells: int | None = None
    mesh_duration_s: float | None = None
    error: str | None = None

    @property
    def lift_to_drag(self) -> float | None:
        if self.cl is None or self.cd is None or self.cd == 0:
            return None
        return self.cl / self.cd

    @property
    def flagged(self) -> bool:
        """Run, but its stopping criteria were not met (kept in the polar, drawn hollow)."""
        return self.state is not None and self.state != CRITERIA_MET

    @property
    def finished(self) -> bool:
        return self.state in FINISHED_STATES


@dataclass
class SweepRecord:
    alphas: list[float]
    cores: int
    points: list[SweepPoint]
    status: str = "not run"  # not run, running, finished, stopped, failed
    mesh_cores: int = 1
    # Hash of everything a point's mesh and result depend on, but the angle (workflow/polar_sweep.py):
    # a sweep resumes only when it is unchanged.
    inputs_hash: str = ""
    planned_first_layer: list[float] = field(default_factory=list)  # (first layer m, count) for D-109; [] none


def write_record(sweep_dir: Path, record: SweepRecord) -> None:
    Path(sweep_dir).mkdir(parents=True, exist_ok=True)
    write_text_atomic(Path(sweep_dir) / SWEEP_JSON, json.dumps(asdict(record), indent=2) + "\n")


def read_record(sweep_dir: Path) -> SweepRecord | None:
    """The sweep record, None when missing or unreadable (also a record of the shared-mesh sweeps before
    D-120, whose points have no meshes of their own)."""
    try:
        data = json.loads((Path(sweep_dir) / SWEEP_JSON).read_text(encoding="utf-8"))
        data.pop("init_from_previous", None)
        points = []
        for p in data.pop("points"):
            p.pop("initialised_from", None)
            points.append(SweepPoint(**p))
        return SweepRecord(points=points, **data)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def new_record(alphas: list[float], cores: int, mesh_cores: int = 1, inputs_hash: str = "",
               planned_first_layer: tuple[float, int] | None = None) -> SweepRecord:
    return SweepRecord(list(alphas), cores, [SweepPoint(i, a) for i, a in enumerate(alphas)],
                       mesh_cores=mesh_cores, inputs_hash=inputs_hash,
                       planned_first_layer=list(planned_first_layer) if planned_first_layer else [])


def resume_record(previous: SweepRecord | None, fresh: SweepRecord) -> SweepRecord:
    """``fresh`` with the finished points of ``previous`` kept, when ``previous`` is the same sweep (same
    angles, solver cores and inputs hash); otherwise ``fresh`` itself. The kept points are not run again."""
    if (previous is None or previous.alphas != fresh.alphas or previous.inputs_hash != fresh.inputs_hash
            or previous.cores != fresh.cores or not fresh.inputs_hash):
        return fresh
    points = [old if old.finished else new for old, new in zip(previous.points, fresh.points)]
    return SweepRecord(list(fresh.alphas), fresh.cores, points, mesh_cores=fresh.mesh_cores,
                       inputs_hash=fresh.inputs_hash, planned_first_layer=list(fresh.planned_first_layer))


def pending(record: SweepRecord) -> list[SweepPoint]:
    """The points a run of ``record`` meshes and solves, in order."""
    return [p for p in record.points if not p.finished]


CSV_HEADER = ["alpha_deg", "CL", "CD", "CM", "L_D", "iterations", "status", "criteria_met", "cells"]


def export_csv(record: SweepRecord, path: Path) -> None:
    def num(v):
        return "" if v is None else repr(float(v))

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for p in record.points:
            writer.writerow([num(p.alpha), num(p.cl), num(p.cd), num(p.cm), num(p.lift_to_drag),
                             "" if p.iterations is None else p.iterations, p.state_label or "not run",
                             "" if p.state is None else str(p.state == CRITERIA_MET).lower(),
                             "" if p.cells is None else p.cells])


# -- runner -------------------------------------------------------------------------------------

def coefficients(case: Path) -> tuple[float | None, float | None, float | None]:
    """(CL, CD, CM pitch) of the last iteration of a finished point (forceCoeffs1, wind axes)."""
    from vortexcfd.foam.postprocessing import ReportMonitor

    monitor = ReportMonitor(case)
    monitor.poll()

    def last(q):
        rows = monitor.series(q)
        return float(rows[-1][1]) if rows and math.isfinite(rows[-1][1]) else None

    return last("Cl"), last("Cd"), last("CmPitch")


class SweepRun:
    """Meshes and solves the pending points of ``record`` (``pending``) in order on a worker thread (no Qt).

    ``prepare_point(case, alpha)`` writes the point's meshing case (the parts rotated to ``alpha``) into
    ``case``; ``write_solver(case, alpha)`` writes its solver files once the mesh is valid. Per point:
    MeshRun on ``record.mesh_cores`` (with the lost-part guard on ``parts`` and the first-cell report when
    ``record.planned_first_layer`` is set, D-109), then SolverRun with the stopping criteria and
    ``record.cores``. A point whose mesh fails is recorded (MESH_FAILED) and the sweep goes on with the next
    angle. The record is written to sweep.json after every step. ``request_stop`` stops the running step
    (meshing: its processes are ended; solving: the clean stop) and ends the sweep; the stopped point and
    the ones after it stay pending. Callbacks are called from worker threads.
    """

    def __init__(self, sweep_dir: Path, record: SweepRecord, prepare_point, write_solver, *, stopping=None,
                 parts: tuple[str, ...] = (), on_line=None, on_point=None, on_step=None, on_done=None,
                 mesh_timeout_s: float | None = 3600.0, solver_timeout_s: float | None = None,
                 mesh_run_factory=None, solver_run_factory=None) -> None:
        from vortexcfd.foam.mesh_run import MeshRun
        from vortexcfd.foam.solver_run import SolverRun

        self.sweep_dir = Path(sweep_dir)
        self.record = record
        self._prepare_point, self._write_solver = prepare_point, write_solver
        self._stopping, self._parts = stopping, tuple(parts)
        self._on_line, self._on_point, self._on_step, self._on_done = on_line, on_point, on_step, on_done
        self._mesh_timeout, self._solver_timeout = mesh_timeout_s, solver_timeout_s
        self._mesh_factory = mesh_run_factory or MeshRun
        self._solver_factory = solver_run_factory or SolverRun
        self._lock = threading.Lock()
        self._stop = False
        self._current = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("SweepRun can only be started once")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        with self._lock:
            self._stop = True
            current = self._current
        if current is not None:
            current.request_stop()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout: float | None = None) -> SweepRecord | None:
        if self._thread is not None:
            self._thread.join(timeout)
        return None if self.is_running() else self.record

    def _say(self, text: str) -> None:
        if self._on_line is not None:
            self._on_line(text if text.endswith("\n") else text + "\n")

    def _stopped(self) -> bool:
        with self._lock:
            return self._stop

    def _save(self, point: SweepPoint | None = None) -> None:
        write_record(self.sweep_dir, self.record)
        if point is not None and self._on_point is not None:
            self._on_point(point)

    def _attach(self, run) -> None:
        with self._lock:
            self._current = run
            stop = self._stop
        if stop:
            run.request_stop()

    def _detach(self) -> None:
        with self._lock:
            self._current = None

    def _mesh(self, point: SweepPoint, case: Path) -> bool:
        """Mesh the point; False when the sweep must stop (a stop request)."""
        first = self.record.planned_first_layer
        started = time.monotonic()
        run = self._mesh_factory(case, on_line=self._on_line, step_timeout_s=self._mesh_timeout, parts=self._parts,
                                 first_layer=(float(first[0]), int(first[1])) if first else None,
                                 cores=self.record.mesh_cores)
        run.start()
        self._attach(run)
        result = run.wait()
        self._detach()
        if self._stopped():
            point.state, point.state_label = None, None
            return False
        report = result.report if result is not None else None
        point.cells = report.cells if report is not None else None
        point.mesh_duration_s = round(time.monotonic() - started, 1)
        if result is None or not result.success or report is None or not report.valid:
            point.state, point.state_label = MESH_FAILED, "mesh failed"
            point.error = ("meshing failed" if report is None else (report.summary() or "invalid mesh"))
            if result is not None and result.error:
                point.error = result.error
        return True

    def _solve(self, point: SweepPoint, case: Path) -> bool:
        """Solve the point; False when the solver did not finish (the sweep fails)."""
        from vortexcfd.foam.solver_run import CRASHED, state_label

        self._write_solver(case, point.alpha)
        run = self._solver_factory(case, stopping=self._stopping, cores=self.record.cores, timeout_s=self._solver_timeout,
                                   on_line=self._on_line, on_step=self._on_step)
        run.start()
        self._attach(run)
        result = run.wait()
        self._detach()
        if result is None:
            point.error = "the solver did not finish"
            return False
        point.state = result.state
        names = result.criteria_met
        if self._stopping is not None:  # "Cd asymptotic", not the condition names
            from vortexcfd.foam.convergence import met_labels

            names = met_labels(self._stopping, names)
        point.state_label = state_label(result.state, names)
        point.iterations = result.iterations
        point.duration_s = round(result.duration_s, 1)
        if result.state != CRASHED:
            point.cl, point.cd, point.cm = coefficients(case)
        return True

    def _run(self) -> None:
        self.record.status = "running"
        failed = False
        todo = pending(self.record)
        try:
            self._save()
            for n, point in enumerate(todo, start=1):
                if self._stopped():
                    break
                case = point_dir(self.sweep_dir, point.index)
                for attr in ("cl", "cd", "cm", "iterations", "state", "state_label", "duration_s", "cells",
                             "mesh_duration_s", "error"):
                    setattr(point, attr, None)
                self._say(f"Polar sweep: point {point.index + 1}/{len(self.record.points)} ({n} of {len(todo)} to run), "
                          f"alpha = {point.alpha:g} deg: meshing in {case}")
                self._prepare_point(case, point.alpha)
                if not self._mesh(point, case):
                    break
                self._save(point)
                if point.state == MESH_FAILED:
                    self._say(f"Polar sweep: alpha = {point.alpha:g} deg: {point.error}; next angle")
                    continue
                self._say(f"Polar sweep: alpha = {point.alpha:g} deg: solving, {point.cells} cells")
                if not self._solve(point, case):
                    failed = True
                    self._save(point)
                    break
                self._save(point)
        except Exception as exc:  # noqa: BLE001 - reported in the record and the console
            self._say(f"Polar sweep failed: {exc}")
            failed = True
        self.record.status = "stopped" if self._stopped() else ("failed" if failed else "finished")
        try:
            self._save()
        except Exception as exc:  # noqa: BLE001 - the end is still reported (R-02)
            self._say(f"Polar sweep: could not save the record: {exc}")
        self._say(f"Polar sweep {self.record.status}")
        if self._on_done is not None:
            self._on_done(self.record)
