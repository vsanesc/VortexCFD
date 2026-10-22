"""Sequential meshing run (blockMesh, surfaceFeatureExtract, snappyHexMesh, checkMesh; the optional steps
run only when their dictionary was written).

With ``cores`` N > 1 (D-111) the snappyHexMesh passes run on N ranks: decomposePar after
surfaceFeatureExtract (system/decomposeParDict written here), ``mpirun -np N snappyHexMesh -parallel``
for every pass and reconstructParMesh -constant after the last one, so createPatch, checkMesh, the
lost-part guard and the first-cell walk read the usual serial mesh. The master rank prints the log in
the serial format. The processor* directories are removed after the reconstruction and after a
stopped or failed run.

No Qt. Everything runs on a worker thread; ``on_line``, ``on_step`` and ``on_done`` are called
from worker/reader threads, so a GUI must forward them through Qt signals only.
"""

import json
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from vortexcfd.foam import layer_walk
from vortexcfd.foam.dictfile import write_foam_file
from vortexcfd.foam.mesh_case import DOMAIN_GUARD_FILE, RECONSTRUCT_STEP, STEP_DICTS, mesh_commands
from vortexcfd.foam.mesh_report import FirstCell, MeshReport, parse_check_mesh, parse_layer_table
from vortexcfd.foam.parallel import DECOMPOSE_DICT, decompose_par_dict, processor_dirs
from vortexcfd.foam.polymesh import PolyMesh
from vortexcfd.foam.postprocessing import patch_face_counts
from vortexcfd.foam.runner import FoamRun

CHECK_MESH = "checkMesh"
SNAPPY = "snappyHexMesh"


@dataclass
class MeshRunResult:
    """Outcome of a meshing run."""

    success: bool  # every step finished and checkMesh ran
    stopped: bool  # the user requested a stop
    failed_step: str | None = None
    exit_codes: dict[str, int | None] = field(default_factory=dict)
    report: MeshReport | None = None  # from checkMesh, if it ran
    log_dir: Path | None = None
    cores: int = 1  # snappyHexMesh ranks (D-111)
    error: str | None = None  # the failed step and its log, for the console


def lost_parts(case_dir: Path, parts: tuple[str, ...]) -> tuple[str, ...]:
    """Part patches missing from constant/polyMesh/boundary or with 0 faces (D-052). An unreadable
    boundary file loses every part."""
    counts = patch_face_counts(case_dir)
    return tuple(p for p in parts if counts.get(p, 0) <= 0)


def domain_problems(case_dir: Path) -> tuple[str, ...]:
    """The domain guard (D-078) from case/vortexcfd_domain.json: a background-box patch that still has
    faces, or an expected domain patch with no faces. Empty without the file (cases before D-078)."""
    try:
        data = json.loads((Path(case_dir) / DOMAIN_GUARD_FILE).read_text(encoding="utf-8"))
        expected, background = list(data.get("expected", ())), list(data.get("background", ()))
    except (OSError, ValueError, AttributeError):
        return ()
    counts = patch_face_counts(case_dir)
    out = [f"The background box patch {name} still has {counts[name]} faces: the domain surface does not "
           "close the fluid region" for name in background if counts.get(name, 0) > 0]
    out += [f"Domain patch {name} has no faces" for name in expected if counts.get(name, 0) <= 0]
    return tuple(out)


def measure_first_cell(case_dir: Path, patches: tuple[str, ...], first_layer: float, layer_count: int) -> FirstCell:
    """The achieved first cell on ``patches`` of the final mesh (D-109): the layer walk of the benchmark
    (foam/layer_walk) from every wall face; the area-weighted mean and 95th percentile of the
    wall-adjacent cell height. Any failure is recorded as ``error``, never raised: a measurement must
    not fail the mesh step."""
    try:
        walked = layer_walk.walk_layers(PolyMesh.read(case_dir), patches, max(1, layer_count) + 5)
        if not walked:
            return FirstCell(planned_m=first_layer, error="no wall patch in the mesh")
        area, cell, layers = (np.concatenate([d[k] for d in walked.values()]) for k in ("area", "first_cell", "layers"))
        stats = layer_walk.first_cell_stats(area, cell, layers)
        over = float(area[cell > 2.0 * first_layer].sum() / area.sum()) if float(area.sum()) > 0 else None
        return FirstCell(mean_m=stats["mean_m"], p95_m=stats["p95_m"], planned_m=first_layer, share_over_2x=over)
    except Exception as exc:  # noqa: BLE001 - recorded, see the docstring
        return FirstCell(planned_m=first_layer, error=f"{type(exc).__name__}: {exc}")


class MeshRun:
    """Runs the meshing steps one after another on a background thread."""

    def __init__(
        self,
        case_dir: Path,
        *,
        on_line: Callable[[str], None] | None = None,
        on_step: Callable[[str], None] | None = None,
        on_done: Callable[[MeshRunResult], None] | None = None,
        steps: tuple[tuple[str, list[str]], ...] | None = None,
        step_timeout_s: float | None = 3600.0,
        parts: tuple[str, ...] = (),
        first_layer: tuple[float, int] | None = None,
        cores: int = 1,
    ) -> None:
        self.case_dir = Path(case_dir)
        self._on_line, self._on_step, self._on_done = on_line, on_step, on_done
        self.cores = max(1, int(cores))
        self._steps = steps if steps is not None else mesh_commands(self.cores)
        self._parts = tuple(parts)  # part patches that must be in the final mesh (lost-part guard)
        # (planned first layer in metres, layer count) of absolute (y+) layers: the achieved first cell is
        # measured on the part patches after checkMesh (D-109); None: not measured
        self._first_layer = first_layer
        self._timeout = step_timeout_s
        self._lock = threading.Lock()
        self._stop = False
        self._current: FoamRun | None = None
        self._thread: threading.Thread | None = None
        self._result: MeshRunResult | None = None
        self._step_name: str | None = None  # the step running or last started

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("MeshRun can only be started once")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        """Stop the running step (SIGTERM escalation, not a clean stop) and skip the rest."""
        with self._lock:
            self._stop = True
            current = self._current
        if current is not None:
            current.request_stop()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout: float | None = None) -> MeshRunResult | None:
        if self._thread is not None:
            self._thread.join(timeout)
        return self._result

    def _clean_processors(self) -> None:
        """Remove the decomposed copy of the mesh (processor*/) and the meshing decomposeParDict."""
        if self.cores <= 1:
            return
        for path in processor_dirs(self.case_dir):
            shutil.rmtree(path, ignore_errors=True)
        (self.case_dir / DECOMPOSE_DICT).unlink(missing_ok=True)

    def _run(self) -> None:
        try:
            self._run_steps()
        except Exception as exc:  # noqa: BLE001 - a step that cannot start, a log or dictionary I/O error
            with self._lock:
                stopped = self._stop
            step = self._step_name
            self._result = MeshRunResult(success=False, stopped=stopped, failed_step=step, log_dir=self.case_dir / "logs",
                                         cores=self.cores, error=f"{step or 'Meshing'} failed: {type(exc).__name__}: {exc}")
        try:
            self._clean_processors()  # also after a stop, a failure or an exception (D-111)
        except OSError:
            pass
        if self._on_done is not None and self._result is not None:
            self._on_done(self._result)

    def _run_steps(self) -> None:
        log_dir = self.case_dir / "logs"
        codes: dict[str, int | None] = {}
        report: MeshReport | None = None
        layers: tuple = ()
        extruded: float | None = None
        failed: str | None = None
        error: str | None = None
        if self.cores > 1:
            self._clean_processors()  # a decomposed mesh of an earlier run or solve
            spec = decompose_par_dict(self.cores)
            write_foam_file(self.case_dir / DECOMPOSE_DICT, spec.content, object_name="decomposeParDict",
                            class_name=spec.class_name)
        for name, command in self._steps:
            with self._lock:
                if self._stop:
                    break
            self._step_name = name
            if name in STEP_DICTS and not (self.case_dir / STEP_DICTS[name]).is_file():
                continue
            if self._on_step is not None:
                self._on_step(name)
            run = FoamRun()
            with self._lock:
                self._current = run
            run.start(command, self.case_dir, log_dir / f"log.{name}", on_line=self._on_line,
                      timeout_s=self._timeout)
            run.wait()
            res = run.result()
            codes[name] = res.exit_code
            with self._lock:
                self._current = None
                stopped = self._stop
            if stopped:
                break
            if name == SNAPPY:
                layers, extruded = parse_layer_table(res.log_file.read_text(encoding="utf-8", errors="replace"))
            if name == CHECK_MESH:
                # checkMesh may exit non-zero when checks fail: the report tells.
                report = parse_check_mesh(res.log_file.read_text(encoding="utf-8", errors="replace"))
                report = replace(report, layers=layers, extruded_percent=extruded,
                                 lost_parts=lost_parts(self.case_dir, self._parts),
                                 domain_errors=domain_problems(self.case_dir))
                if self._first_layer is not None and self._parts:
                    if self._on_step is not None:
                        self._on_step("first cell")
                    report = replace(report, first_cell=measure_first_cell(self.case_dir, self._parts,
                                                                           *self._first_layer))
            elif res.exit_code != 0:
                failed = name
                error = f"{name} failed (exit code {res.exit_code}): see {res.log_file}"
                break
            if name == RECONSTRUCT_STEP:
                self._clean_processors()  # the serial mesh is in constant/polyMesh
        with self._lock:
            stopped = self._stop
        result = MeshRunResult(
            success=failed is None and not stopped and report is not None,
            stopped=stopped, failed_step=failed, exit_codes=codes, report=report, log_dir=log_dir,
            cores=self.cores, error=error,
        )
        self._result = result
