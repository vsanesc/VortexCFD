"""Solver run: simpleFoam through FoamRun with clean stop, live log parsing and the end state (no Qt).

Everything runs on a worker thread. ``on_line`` and ``on_step`` are called from FoamRun's reader
thread and ``on_done`` from the worker thread, so a GUI must forward them through Qt signals only.

End states (D-046), decided from the exit code and the LogParser events:

- ``crashed``: a ``SolverCrash`` (stack trace) or ``FatalError`` block, or a non-zero exit code that
  the user did not cause by stopping;
- ``stopped``: the user (or the timeout) stopped the run;
- ``converged``: the solution control printed "SIMPLE solution converged" (residualControl reached);
- ``iteration_limit``: the solver ended normally at endTime without converging.
"""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from vortexcfd.foam.logparse import LogParser, TimeStep
from vortexcfd.foam.runner import FoamRun, RunResult

SOLVER = "simpleFoam"
LOG_NAME = f"log.{SOLVER}"

CONVERGED = "converged"
ITERATION_LIMIT = "iteration_limit"
STOPPED = "stopped"
CRASHED = "crashed"
STATE_LABELS = {
    CONVERGED: "Converged",
    ITERATION_LIMIT: "Iteration limit",
    STOPPED: "Stopped",
    CRASHED: "Crashed",
}


@dataclass
class SolverRunResult:
    """Outcome of a solver run."""

    state: str  # one of STATE_LABELS
    exit_code: int | None
    iterations: int  # last completed iteration (0 if none)
    final_residuals: dict[str, float] = field(default_factory=dict)  # last initial residual per field
    crash: str | None = None  # the crash or fatal-error block, if any
    log_file: Path | None = None
    duration_s: float = 0.0

    @property
    def label(self) -> str:
        return STATE_LABELS[self.state]


def final_residuals(steps: Iterable[TimeStep]) -> dict[str, float]:
    """The last initial residual of every field (the first solve of the field in its last step)."""
    out: dict[str, float] = {}
    for step in steps:
        seen: set[str] = set()
        for name, initial, _final, _iters in step.residuals:
            if name not in seen:
                seen.add(name)
                out[name] = initial
    return out


def classify(exit_code: int | None, stop_requested: bool, parser: LogParser) -> str:
    """The end state of a finished run (see the module docstring)."""
    if parser.crash is not None or parser.fatal_error is not None:
        return CRASHED
    if stop_requested:
        return STOPPED
    if exit_code != 0:
        return CRASHED
    if parser.converged is not None:
        return CONVERGED
    return ITERATION_LIMIT


def _iterations(parser: LogParser) -> int:
    return int(parser.time_steps[-1].time) if parser.time_steps else 0


class SolverRun:
    """Runs the solver in ``case_dir`` on a background thread (clean stop enabled).

    ``runner_factory`` builds the process runner (FoamRun; tests pass a fake with the same
    start/wait/result/request_stop interface).
    """

    def __init__(
        self,
        case_dir: Path,
        *,
        on_line: Callable[[str], None] | None = None,
        on_step: Callable[[TimeStep], None] | None = None,
        on_done: Callable[[SolverRunResult], None] | None = None,
        timeout_s: float | None = None,
        runner_factory: Callable[[], FoamRun] = FoamRun,
    ) -> None:
        self.case_dir = Path(case_dir)
        self._on_line, self._on_step, self._on_done = on_line, on_step, on_done
        self._timeout = timeout_s
        self._factory = runner_factory
        self._lock = threading.Lock()
        self._stop = False
        self._runner: FoamRun | None = None
        self._thread: threading.Thread | None = None
        self._result: SolverRunResult | None = None
        self.parser = LogParser()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("SolverRun can only be started once")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        """Clean stop (SIGUSR1: write the current iteration and end), escalating if ignored."""
        with self._lock:
            self._stop = True
            runner = self._runner
        if runner is not None:
            runner.request_stop()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout: float | None = None) -> SolverRunResult | None:
        if self._thread is not None:
            self._thread.join(timeout)
        return self._result

    def _line(self, text: str) -> None:
        """Reader thread: forward the line, then parse it and forward completed steps."""
        if self._on_line is not None:
            self._on_line(text)
        self._forward(self.parser.feed(text))

    def _forward(self, events: list) -> None:
        if self._on_step is None:
            return
        for event in events:
            if isinstance(event, TimeStep):
                self._on_step(event)

    def _run(self) -> None:
        log_file = self.case_dir / LOG_NAME
        runner = self._factory()
        res: RunResult | None = None
        error: str | None = None
        try:
            runner.start([SOLVER], self.case_dir, log_file, on_line=self._line,
                         timeout_s=self._timeout, clean_stop=True)
            with self._lock:
                self._runner = runner
                stop = self._stop
            if stop:  # requested while starting
                runner.request_stop()
            runner.wait()
            res = runner.result()
        except (OSError, ValueError, RuntimeError) as exc:
            error = f"Could not run {SOLVER}: {exc}"
        self._forward(self.parser.close())
        with self._lock:
            self._runner = None
            stop = self._stop
        if res is None:
            result = SolverRunResult(CRASHED, None, _iterations(self.parser),
                                     final_residuals(self.parser), error, log_file)
        else:
            stopped = stop or res.stop_requested or res.timed_out
            state = classify(res.exit_code, stopped, self.parser)
            result = SolverRunResult(
                state, res.exit_code, _iterations(self.parser), final_residuals(self.parser),
                self.parser.crash or self.parser.fatal_error, res.log_file, res.duration_s,
            )
        self._result = result
        if self._on_done is not None:
            self._on_done(result)
