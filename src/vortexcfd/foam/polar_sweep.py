"""Angle-of-attack sweep (polar): points, initialisation, record, CSV and the runner (no Qt). (D-067)
[NUMERICS-REVIEW]

Every point runs the project's physics, stopping criteria and the CURRENT mesh at its own angle of
attack in <project dir>/case_sweep/point_<n>/ (case/ is never touched): the mesh is copied once into
case_sweep/mesh/polyMesh and each point's constant/polyMesh is a relative symbolic link to it. The
solver files of a point are those of a normal run with Inflow.alpha_deg = alpha, so the inlet
velocity, the freestream far field and the forceCoeffs lift and drag directions all follow alpha
(D-050). With ``init_from_previous`` a point starts from the latest solution of the last point
that met its stopping criteria: the internal fields of U, p, k, omega and nut are copied from that
point's latest time into the new 0/ files, whose boundary conditions are the new point's (the new
inlet direction); a point after a point that did not meet its criteria starts from the last one
that did, or from the uniform free stream when none did.
"""

import csv
import json
import math
import os
import shutil
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

SWEEP_DIR_NAME = "case_sweep"
SWEEP_JSON = "sweep.json"
MESH_DIR = "mesh"
INIT_FIELDS = ("U", "p", "k", "omega", "nut")


def point_dir(sweep_dir: Path, index: int) -> Path:
    return Path(sweep_dir) / f"point_{index + 1}"


def link_mesh(sweep_dir: Path, case: Path) -> None:
    """case/constant/polyMesh -> ../../mesh/polyMesh (relative, so the sweep directory can move)."""
    constant = Path(case) / "constant"
    constant.mkdir(parents=True, exist_ok=True)
    link = constant / "polyMesh"
    if link.is_symlink() or link.exists():
        if link.is_symlink() or link.is_file():
            link.unlink()
        else:
            shutil.rmtree(link)
    os.symlink(Path("..") / ".." / MESH_DIR / "polyMesh", link, target_is_directory=True)


def copy_mesh(source_case: Path, sweep_dir: Path) -> None:
    """Copy the current mesh (source_case/constant/polyMesh) into sweep_dir/mesh/polyMesh."""
    target = Path(sweep_dir) / MESH_DIR / "polyMesh"
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path(source_case) / "constant" / "polyMesh", target)


def latest_time(case: Path) -> str | None:
    """The latest time directory after 0 that holds U (None: none)."""
    best, name = None, None
    for child in Path(case).iterdir() if Path(case).is_dir() else ():
        try:
            t = float(child.name)
        except ValueError:
            continue
        if t > 0 and (child / "U").is_file() and (best is None or t > best):
            best, name = t, child.name
    return name


def initialise_from(previous: Path, case: Path) -> str | None:
    """Copy the internal fields of the latest time of ``previous`` into ``case``/0 (whose files,
    with the new boundary conditions, must exist). Returns the time used, None when there is none."""
    from foamlib import FoamFieldFile

    time = latest_time(previous)
    if time is None:
        return None
    for name in INIT_FIELDS:
        source, target = Path(previous) / time / name, Path(case) / "0" / name
        if source.is_file() and target.is_file():
            FoamFieldFile(target).internal_field = FoamFieldFile(source).internal_field
    return time


# -- record ------------------------------------------------------------------------------------

CRITERIA_MET = "criteria_met"


@dataclass
class SweepPoint:
    index: int
    alpha: float
    cl: float | None = None
    cd: float | None = None
    cm: float | None = None
    iterations: int | None = None
    state: str | None = None  # solver_run state; None until run
    state_label: str | None = None
    initialised_from: str | None = None  # "point_<n> at time <t>" or None (uniform free stream)
    duration_s: float | None = None

    @property
    def lift_to_drag(self) -> float | None:
        if self.cl is None or self.cd is None or self.cd == 0:
            return None
        return self.cl / self.cd

    @property
    def flagged(self) -> bool:
        """Run, but its stopping criteria were not met (kept in the polar, drawn hollow)."""
        return self.state is not None and self.state != CRITERIA_MET


@dataclass
class SweepRecord:
    alphas: list[float]
    cores: int
    init_from_previous: bool
    points: list[SweepPoint]
    status: str = "not run"  # not run, running, finished, stopped, failed


def write_record(sweep_dir: Path, record: SweepRecord) -> None:
    Path(sweep_dir).mkdir(parents=True, exist_ok=True)
    (Path(sweep_dir) / SWEEP_JSON).write_text(json.dumps(asdict(record), indent=2) + "\n", encoding="utf-8")


def read_record(sweep_dir: Path) -> SweepRecord | None:
    try:
        data = json.loads((Path(sweep_dir) / SWEEP_JSON).read_text(encoding="utf-8"))
        points = [SweepPoint(**p) for p in data.pop("points")]
        return SweepRecord(points=points, **data)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def new_record(alphas: list[float], cores: int, init_from_previous: bool) -> SweepRecord:
    return SweepRecord(list(alphas), cores, init_from_previous,
                       [SweepPoint(i, a) for i, a in enumerate(alphas)])


CSV_HEADER = ["alpha_deg", "CL", "CD", "CM", "L_D", "iterations", "status", "criteria_met", "initialised_from"]


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
                             p.initialised_from or ""])


# -- runner -------------------------------------------------------------------------------------

def coefficients(case: Path) -> tuple[float | None, float | None, float | None]:
    """(CL, CD, CM pitch) of the last iteration of a finished point (forceCoeffs1)."""
    from vortexcfd.foam.postprocessing import ReportMonitor

    monitor = ReportMonitor(case)
    monitor.poll()

    def last(q):
        rows = monitor.series(q)
        return float(rows[-1][1]) if rows and math.isfinite(rows[-1][1]) else None

    return last("Cl"), last("Cd"), last("CmPitch")


class SweepRun:
    """Runs the points of ``record`` in order on a worker thread (no Qt).

    ``write_point(case, alpha)`` writes a point's solver files (0/ with that alpha's boundary
    conditions) into ``case``; the mesh must already be in sweep_dir/mesh/polyMesh. The record is
    written to sweep.json after every point. ``request_stop`` stops the running point cleanly (its
    state is "stopped") and ends the sweep; the points after it stay unrun. Callbacks are called
    from worker threads.
    """

    def __init__(self, sweep_dir: Path, record: SweepRecord, write_point, *, stopping=None,
                 on_line=None, on_point=None, on_step=None, on_done=None, solver_timeout_s: float | None = None,
                 solver_run_factory=None) -> None:
        from vortexcfd.foam.solver_run import SolverRun

        self.sweep_dir = Path(sweep_dir)
        self.record = record
        self._write_point = write_point
        self._stopping = stopping
        self._on_line, self._on_point, self._on_step, self._on_done = on_line, on_point, on_step, on_done
        self._timeout = solver_timeout_s
        self._factory = solver_run_factory or SolverRun
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

    def _run(self) -> None:
        from vortexcfd.foam.solver_run import CRASHED, state_label

        self.record.status = "running"
        failed = False
        source: Path | None = None  # the last point that met its criteria
        source_name = ""
        try:
            self._save()
            for point in self.record.points:
                if self._stopped():
                    break
                case = point_dir(self.sweep_dir, point.index)
                if case.exists():
                    shutil.rmtree(case)
                case.mkdir(parents=True)
                link_mesh(self.sweep_dir, case)
                self._write_point(case, point.alpha)
                if self.record.init_from_previous and source is not None:
                    time = initialise_from(source, case)
                    point.initialised_from = f"{source_name} at time {time}" if time is not None else None
                self._say(f"Polar sweep: point {point.index + 1}/{len(self.record.points)}, alpha = {point.alpha:g} deg"
                          + (f", initialised from {point.initialised_from}" if point.initialised_from else ""))
                run = self._factory(case, stopping=self._stopping, cores=self.record.cores, timeout_s=self._timeout,
                                    on_line=self._on_line, on_step=self._on_step)
                with self._lock:
                    self._current = run
                    stop = self._stop
                run.start()
                if stop:
                    run.request_stop()
                result = run.wait()
                with self._lock:
                    self._current = None
                if result is None:
                    failed = True
                    break
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
                if result.state == CRITERIA_MET:
                    source, source_name = case, case.name
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
