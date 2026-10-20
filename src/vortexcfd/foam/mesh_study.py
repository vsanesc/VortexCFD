"""Mesh independence study: the family of meshes, the record and the GCI tables (no Qt). (D-066)
[NUMERICS-REVIEW]

Three levels (coarse, medium, fine) built from the project's mesh settings with a constant
refinement ratio r in linear cell size: the current settings are the fine or the medium level. A
level with linear size factor f (f = r^k, k = 2, 1, 0 for coarse, medium, fine when the current
settings are the fine level) gets

- the background cell budget divided by f^3 (or an explicit base size multiplied by f);
- the target surface size multiplied by f, so the surface refinement levels, which follow
  log2(base size / target surface size), stay the same and every cell scales by f; explicit level
  overrides are kept;
- the SAME absolute prism-layer stack on every level: the first-layer thickness, expansion ratio
  and number of layers of the reference (current) settings, so the first-cell y+ does not change
  between levels (the flat plate study, D-036, showed Cf moving 2.6 % between first-cell y+ 1 and
  0.5: a y+ change would be mixed into the grid error).

The representative cell size of a level is h = (V_domain / N_cells)^(1/3) with the cell count of
its checkMesh report (the actual cells, not the estimate). Each level runs the project's physics
and stopping criteria in its own directory (<project>/case_study/level_<n>/); a level whose run
did not meet the criteria is flagged and every GCI that uses it is marked unreliable.
"""

import csv
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from vortexcfd.core.model import Mesh
from vortexcfd.foam import gci
from vortexcfd.foam.yplus import layer_cap, plan_layers

STUDY_DIR_NAME = "case_study"
STUDY_JSON = "study.json"
DEFAULT_RATIO = math.sqrt(2.0)
MIN_RATIO = 1.3
LEVEL_NAMES = ("coarse", "medium", "fine")
CURRENT_AS = ("fine", "medium")  # which level the current settings are


def level_factors(ratio: float, current_as: str) -> tuple[float, float, float]:
    """Linear cell-size factors of the coarse, medium and fine levels relative to the current
    settings."""
    if ratio < MIN_RATIO:
        raise ValueError(f"the refinement ratio must be at least {MIN_RATIO}")
    if current_as == "fine":
        return ratio**2, ratio, 1.0
    if current_as == "medium":
        return ratio, 1.0, 1.0 / ratio
    raise ValueError(f"current_as must be one of {CURRENT_AS}")


@dataclass(frozen=True)
class LayerStack:
    """An absolute prism-layer stack (metres)."""

    first: float
    count: int
    expansion: float


def reference_layers(mesh: Mesh, surface_size: float, yplus_first: float | None) -> LayerStack | None:
    """The layer stack of the current settings in absolute terms (None: no layers).

    absolute_yplus: the y+ first layer (``yplus_first``) and the count of foam/yplus.plan_layers for
    the current surface cell size. relative: the count of the settings and the first layer
    final_layer_thickness * surface_size / expansion^(count - 1), i.e. the stack snappyHexMesh builds
    with relativeSizes on a face of the current maximum surface level."""
    if mesh.layer_sizing == "absolute_yplus":
        if yplus_first is None:
            raise ValueError("absolute_yplus needs the y+ first layer")
        plan = plan_layers(yplus_first, mesh.expansion_ratio, surface_size, **layer_cap(mesh.layer_controls))
        return LayerStack(yplus_first, plan.count, plan.expansion)
    if mesh.layers <= 0:
        return None
    first = mesh.final_layer_thickness * surface_size / mesh.expansion_ratio ** (mesh.layers - 1)
    return LayerStack(first, mesh.layers, mesh.expansion_ratio)


def scale_mesh(mesh: Mesh, factor: float) -> Mesh:
    """The mesh settings of a level with linear size factor ``factor`` (> 1 coarser)."""
    update: dict = {
        "background_cells_target": max(1, round(mesh.background_cells_target / factor**3)),
        "target_surface_size": mesh.target_surface_size * factor,
    }
    if mesh.base_size is not None:
        update["base_size"] = mesh.base_size * factor
    return mesh.model_copy(update=update)


@dataclass(frozen=True)
class StudyLevel:
    index: int  # 0 coarse, 1 medium, 2 fine
    name: str
    factor: float
    mesh: Mesh


def study_levels(mesh: Mesh, ratio: float, current_as: str) -> list[StudyLevel]:
    return [StudyLevel(i, LEVEL_NAMES[i], f, scale_mesh(mesh, f))
            for i, f in enumerate(level_factors(ratio, current_as))]


def level_dir(study_dir: Path, index: int) -> Path:
    return Path(study_dir) / f"level_{index + 1}"


def estimate_seconds(seconds_per_cell_iteration: float | None, cells: int, iterations: int,
                     last_cores: int, cores: int) -> float | None:
    """Run time of a level from the last run's time per cell-iteration, assuming ideal scaling
    with the number of cores (an estimate, the stopping criteria usually end runs earlier)."""
    if seconds_per_cell_iteration is None or cells <= 0:
        return None
    return seconds_per_cell_iteration * cells * iterations * max(1, last_cores) / max(1, cores)


# -- record ------------------------------------------------------------------------------------

@dataclass
class LevelResult:
    """One level as run (persisted in study.json)."""

    index: int
    name: str
    factor: float
    estimated_cells: int | None = None
    cells: int | None = None  # checkMesh
    h: float | None = None  # (V / N)^(1/3), metres
    mesh_ok: bool | None = None
    state: str | None = None  # solver_run state, None until run
    state_label: str | None = None
    criteria_met: bool | None = None
    iterations: int | None = None
    duration_s: float | None = None
    values: dict[str, float] = field(default_factory=dict)  # report id -> final value
    error: str | None = None

    @property
    def reliable(self) -> bool:
        return bool(self.mesh_ok) and bool(self.criteria_met)


@dataclass
class StudyRecord:
    ratio: float
    current_as: str
    quantities: list[str]
    cores: int
    domain_volume: float
    levels: list[LevelResult]
    status: str = "not run"  # not run, running, finished, stopped, failed
    inputs_hash: str = ""
    mesh_cores: int = 1  # snappyHexMesh ranks of every level (D-111; records before it: 1)


def write_record(study_dir: Path, record: StudyRecord) -> None:
    Path(study_dir).mkdir(parents=True, exist_ok=True)
    data = asdict(record)
    (Path(study_dir) / STUDY_JSON).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_record(study_dir: Path) -> StudyRecord | None:
    try:
        data = json.loads((Path(study_dir) / STUDY_JSON).read_text(encoding="utf-8"))
        levels = [LevelResult(**lv) for lv in data.pop("levels")]
        return StudyRecord(levels=levels, **data)
    except (OSError, ValueError, TypeError, KeyError):
        return None


# -- results ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class QuantityRow:
    """The GCI table row of one quantity."""

    quantity: str
    sizes: tuple[float | None, ...]  # h per level, coarse first
    values: tuple[float | None, ...]  # per level, coarse first
    result: gci.GciResult | None  # None: a level has no value
    reliable: bool  # every level met its stopping criteria and has a valid mesh
    note: str  # why there is no GCI, or "" / "unreliable: ..." notes


def quantity_rows(record: StudyRecord) -> list[QuantityRow]:
    rows = []
    unreliable = [lv.name for lv in record.levels if not lv.reliable]
    for q in record.quantities:
        sizes = tuple(lv.h for lv in record.levels)
        values = tuple(lv.values.get(q) for lv in record.levels)
        result, note = None, ""
        if any(v is None for v in values) or any(h is None for h in sizes):
            note = "incomplete: a level has no value"
        elif len(set(sizes)) < 3:
            note = "two levels have the same cell size"
        else:
            result = gci.study(list(values), list(sizes))
            note = "" if result.applicable else result.text
        if unreliable:
            flag = "unreliable: " + ", ".join(unreliable) + " did not meet the stopping criteria"
            note = f"{note}; {flag}" if note else flag
        rows.append(QuantityRow(q, sizes, values, result, not unreliable, note))
    return rows


CSV_HEADER = ["quantity", "h_coarse_m", "h_medium_m", "h_fine_m", "value_coarse", "value_medium", "value_fine",
              "convergence", "order_p", "extrapolated", "gci_fine_percent", "gci_medium_percent",
              "asymptotic_ratio", "in_asymptotic_range", "reliable", "note"]


def export_csv(record: StudyRecord, path: Path) -> None:
    def num(v):
        return "" if v is None else repr(float(v))

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for row in quantity_rows(record):
            r = row.result
            writer.writerow([
                row.quantity, *(num(h) for h in row.sizes), *(num(v) for v in row.values),
                r.convergence if r else "", num(r.order if r else None), num(r.extrapolated if r else None),
                num(100 * r.gci_fine if r and r.gci_fine is not None else None),
                num(100 * r.gci_medium if r and r.gci_medium is not None else None),
                num(r.asymptotic_ratio if r else None),
                "" if r is None or r.in_asymptotic_range is None else str(r.in_asymptotic_range).lower(),
                str(row.reliable).lower(), row.note,
            ])


# -- runner -------------------------------------------------------------------------------------

def final_values(case_dir: Path, quantities: list[str]) -> dict[str, float]:
    """The last value of every scalar report of a finished run (ReportMonitor, D-060)."""
    from vortexcfd.foam.postprocessing import ReportMonitor

    monitor = ReportMonitor(case_dir)
    monitor.poll()
    out = {}
    for q in quantities:
        try:
            rows = monitor.series(q)
        except KeyError:
            continue
        if rows and isinstance(rows[-1][1], (int, float)):
            out[q] = float(rows[-1][1])
    return out


class StudyRun:
    """Meshes and solves the levels of ``record`` in order on a worker thread (no Qt).

    Every level directory must already hold its meshing case (dictionaries and surfaces, written by
    the caller). Per level: MeshRun (blockMesh, surfaceFeatureExtract, snappyHexMesh, checkMesh; on
    ``record.mesh_cores`` ranks, decomposed and reconstructed within the level, its processor*/ removed
    by MeshRun after the level, a stop or a failure, D-111), then
    ``write_solver(level_dir)`` writes the solver files, then SolverRun with the run's stopping
    criteria and cores, then the final values of the study quantities. The record is written to
    study.json after every step. ``on_line`` / ``on_level`` / ``on_done`` are called from worker
    threads (a GUI forwards them through signals). ``request_stop`` stops the running step cleanly
    and ends the study ("stopped"); the levels not run keep no result.
    """

    def __init__(self, study_dir: Path, record: StudyRecord, write_solver, *, stopping=None,
                 parts: tuple[str, ...] = (), binding: str | None = None,
                 on_line=None, on_level=None, on_done=None, mesh_timeout_s: float | None = 3600.0,
                 solver_timeout_s: float | None = None, mesh_run_factory=None, solver_run_factory=None) -> None:
        import threading

        from vortexcfd.foam.mesh_run import MeshRun
        from vortexcfd.foam.solver_run import SolverRun

        self.study_dir = Path(study_dir)
        self.record = record
        self._write_solver = write_solver
        self._stopping, self._parts, self._binding = stopping, tuple(parts), binding
        self._on_line, self._on_level, self._on_done = on_line, on_level, on_done
        self._mesh_timeout, self._solver_timeout = mesh_timeout_s, solver_timeout_s
        self._mesh_factory = mesh_run_factory or MeshRun
        self._solver_factory = solver_run_factory or SolverRun
        self._lock = threading.Lock()
        self._stop = False
        self._current = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import threading

        if self._thread is not None:
            raise RuntimeError("StudyRun can only be started once")
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

    def wait(self, timeout: float | None = None) -> StudyRecord | None:
        if self._thread is not None:
            self._thread.join(timeout)
        return None if self.is_running() else self.record

    def _say(self, text: str) -> None:
        if self._on_line is not None:
            self._on_line(text if text.endswith("\n") else text + "\n")

    def _stopped(self) -> bool:
        with self._lock:
            return self._stop

    def _save(self, level: LevelResult | None = None) -> None:
        write_record(self.study_dir, self.record)
        if level is not None and self._on_level is not None:
            self._on_level(level)

    def _attach(self, run) -> None:
        with self._lock:
            self._current = run
            stop = self._stop
        if stop:
            run.request_stop()

    def _run(self) -> None:
        from vortexcfd.foam.solver_run import CRITERIA_MET, state_label

        self.record.status = "running"
        self._save()
        failed = False
        try:
            for level in self.record.levels:
                if self._stopped():
                    break
                case = level_dir(self.study_dir, level.index)
                self._say(f"Mesh study: meshing level {level.index + 1} ({level.name}) in {case}")
                mesh_run = self._mesh_factory(case, on_line=self._on_line, step_timeout_s=self._mesh_timeout,
                                              parts=self._parts, cores=self.record.mesh_cores)
                mesh_run.start()
                self._attach(mesh_run)
                mesh = mesh_run.wait()
                with self._lock:
                    self._current = None
                if self._stopped():
                    break
                report = mesh.report if mesh is not None else None
                level.cells = report.cells if report is not None else None
                level.mesh_ok = bool(mesh is not None and mesh.success and report is not None and report.valid)
                if level.cells:
                    level.h = gci.cell_size(self.record.domain_volume, level.cells)
                if not level.mesh_ok:
                    level.error = "meshing failed" if report is None else (report.summary() or "invalid mesh")
                    self._save(level)
                    failed = True
                    break
                self._save(level)
                self._write_solver(case)
                self._say(f"Mesh study: solving level {level.index + 1} ({level.name}), {level.cells} cells")
                kwargs = {"stopping": self._stopping, "cores": self.record.cores, "timeout_s": self._solver_timeout,
                          "on_line": self._on_line}
                if self._binding is not None:
                    kwargs["binding"] = self._binding
                solver = self._solver_factory(case, **kwargs)
                solver.start()
                self._attach(solver)
                result = solver.wait()
                with self._lock:
                    self._current = None
                if result is None:
                    level.error = "the solver did not finish"
                    failed = True
                    self._save(level)
                    break
                level.state = result.state
                names = result.criteria_met
                if self._stopping is not None:  # "Cd asymptotic", not the condition names
                    from vortexcfd.foam.convergence import met_labels

                    names = met_labels(self._stopping, names)
                level.state_label = state_label(result.state, names)
                level.criteria_met = result.state == CRITERIA_MET
                level.iterations = result.iterations
                level.duration_s = round(result.duration_s, 1)
                level.values = final_values(case, self.record.quantities)
                if result.state == "crashed":
                    level.error = "the solver crashed"
                self._save(level)
                if self._stopped():
                    break
        except Exception as exc:  # noqa: BLE001 - reported in the record and the console
            self._say(f"Mesh study failed: {exc}")
            failed = True
        self.record.status = "stopped" if self._stopped() else ("failed" if failed else "finished")
        self._save()
        self._say(f"Mesh study {self.record.status}")
        if self._on_done is not None:
            self._on_done(self.record)
