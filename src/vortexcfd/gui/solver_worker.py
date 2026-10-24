"""Qt wrapper that runs the solver in the background and reports through signals.

``SolverRun`` calls its callbacks from reader and worker threads. They only emit signals here;
connect them to methods of a QObject living in the GUI thread so slots run there (queued).
"""

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from vortexcfd.foam.runner import FoamRun
from vortexcfd.foam.solver_run import SolverRun
from vortexcfd.gui.thread_gate import ThreadGate


class SolverWorker(QObject):
    line = Signal(str)  # one line of solver output
    step = Signal(object)  # logparse.TimeStep of a completed iteration
    finished = Signal(object)  # solver_run.SolverRunResult
    stage = Signal(int, int, str)  # the second turbulence stage began: (stage, switch iteration, reason), D-126

    def __init__(self, parent: QObject | None = None, runner_factory=FoamRun) -> None:
        super().__init__(parent)
        self.runner_factory = runner_factory  # tests replace it with a fake runner
        self._run: SolverRun | None = None
        self.gate = ThreadGate()  # the run's threads emit through it (D-164)

    def start(self, case_dir: Path, timeout_s: float | None = None, stopping=None, cores: int = 1) -> None:
        """``stopping``: the run's StoppingCriteria (evaluated by SolverRun when OpenFOAM cannot);
        ``cores``: MPI ranks (1: serial)."""
        if self.is_running():
            raise RuntimeError("the solver is already running")
        self._run = SolverRun(
            case_dir, on_line=self.gate.emitter(self.line), on_step=self.gate.emitter(self.step),
            on_done=self.gate.emitter(self.finished), on_stage=self.gate.emitter(self.stage),
            timeout_s=timeout_s, runner_factory=self.runner_factory, stopping=stopping, cores=cores,
        )
        self._run.start()

    def request_stop(self) -> None:
        """Clean stop with the runner's escalation (SIGUSR1, then SIGTERM, then SIGKILL)."""
        if self._run is not None:
            self._run.request_stop()

    def is_running(self) -> bool:
        return self._run is not None and self._run.is_running()

    def shutdown(self) -> None:
        """Before the owner is deleted: stop a run and never emit again (D-164)."""
        self.request_stop()
        self.gate.close()

    def wait(self, timeout: float | None = None):
        return self._run.wait(timeout) if self._run is not None else None
