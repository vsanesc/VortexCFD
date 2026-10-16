"""Sequential meshing run (blockMesh, surfaceFeatureExtract, snappyHexMesh, checkMesh).

No Qt. Everything runs on a worker thread; ``on_line``, ``on_step`` and ``on_done`` are called
from worker/reader threads, so a GUI must forward them through Qt signals only.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from vortexcfd.foam.mesh_case import MESH_COMMANDS
from vortexcfd.foam.mesh_report import MeshReport, parse_check_mesh, parse_layer_table
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


class MeshRun:
    """Runs the meshing steps one after another on a background thread."""

    def __init__(
        self,
        case_dir: Path,
        *,
        on_line: Callable[[str], None] | None = None,
        on_step: Callable[[str], None] | None = None,
        on_done: Callable[[MeshRunResult], None] | None = None,
        steps: tuple[tuple[str, list[str]], ...] = MESH_COMMANDS,
        step_timeout_s: float | None = 3600.0,
    ) -> None:
        self.case_dir = Path(case_dir)
        self._on_line, self._on_step, self._on_done = on_line, on_step, on_done
        self._steps = steps
        self._timeout = step_timeout_s
        self._lock = threading.Lock()
        self._stop = False
        self._current: FoamRun | None = None
        self._thread: threading.Thread | None = None
        self._result: MeshRunResult | None = None

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

    def _run(self) -> None:
        log_dir = self.case_dir / "logs"
        codes: dict[str, int | None] = {}
        report: MeshReport | None = None
        layers: tuple = ()
        extruded: float | None = None
        failed: str | None = None
        for name, command in self._steps:
            with self._lock:
                if self._stop:
                    break
            if name == "surfaceFeatureExtract" and not (self.case_dir / "system" / "surfaceFeatureExtractDict").is_file():
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
                report = replace(report, layers=layers, extruded_percent=extruded)
            elif res.exit_code != 0:
                failed = name
                break
        with self._lock:
            stopped = self._stop
        result = MeshRunResult(
            success=failed is None and not stopped and report is not None,
            stopped=stopped, failed_step=failed, exit_codes=codes, report=report, log_dir=log_dir,
        )
        self._result = result
        if self._on_done is not None:
            self._on_done(result)
