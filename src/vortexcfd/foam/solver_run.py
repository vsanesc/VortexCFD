"""Solver run: simpleFoam through FoamRun with clean stop, live log parsing and the end state (no Qt).

Everything runs on a worker thread. ``on_line`` and ``on_step`` are called from FoamRun's reader
thread and ``on_done`` from the worker thread, so a GUI must forward them through Qt signals only.

End states (D-046), decided from the exit code and the LogParser events:

- ``crashed``: a ``SolverCrash`` (stack trace) or ``FatalError`` block, or a non-zero exit code that
  the user did not cause by stopping;
- ``stopped``: the user (or the timeout) stopped the run;
- ``criteria_met``: the stopping criteria were met: runTimeControl printed "Stopping calculation"
  (residual criteria only), the app's own evaluation met them and stopped the solver cleanly (an
  asymptotic criterion exists, D-058) or, in logs written before them, the SIMPLE residualControl
  printed "SIMPLE solution converged". Run records written before D-058 was revised say
  "converged"; they are read as ``criteria_met``;
- ``iteration_limit``: the solver ended normally at endTime without converging.
"""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from vortexcfd.core.model import StoppingCriteria
from vortexcfd.foam import convergence
from vortexcfd.foam.logparse import LogParser, TimeStep
from vortexcfd.foam.postprocessing import ReportMonitor
from vortexcfd.foam.residuals import ResidualHistory
from vortexcfd.foam.runner import FoamRun, RunResult

SOLVER = "simpleFoam"
LOG_NAME = f"log.{SOLVER}"

CRITERIA_MET = "criteria_met"
ITERATION_LIMIT = "iteration_limit"
STOPPED = "stopped"
CRASHED = "crashed"
STATE_LABELS = {
    CRITERIA_MET: "Criteria met",
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
    criteria_met: tuple[str, ...] = ()  # condition names (convergence.condition_name) that stopped the run
    met_iteration: int | None = None  # the iteration at which they were met

    @property
    def label(self) -> str:
        return STATE_LABELS[self.state]


def state_label(state: str, met: tuple[str, ...] = ()) -> str:
    """The run state as shown: "Criteria met: <criterion names>" when the names are known."""
    if state == CRITERIA_MET and met:
        return f"{STATE_LABELS[state]}: " + ", ".join(met)
    return STATE_LABELS[state]


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


def classify(exit_code: int | None, stop_requested: bool, parser: LogParser, criteria_stop: bool = False) -> str:
    """The end state of a finished run (see the module docstring). ``criteria_stop``: the app
    stopped the solver because its criteria were met (not a user stop)."""
    if parser.crash is not None or parser.fatal_error is not None:
        return CRASHED
    if criteria_stop and exit_code == 0:
        return CRITERIA_MET
    if stop_requested:
        return STOPPED
    if exit_code != 0:
        return CRASHED
    if parser.criteria_met is not None or parser.converged is not None:
        return CRITERIA_MET
    return ITERATION_LIMIT


def _iterations(parser: LogParser) -> int:
    return int(parser.time_steps[-1].time) if parser.time_steps else 0


class SolverRun:
    """Runs the solver in ``case_dir`` on a background thread (clean stop enabled).

    ``runner_factory`` builds the process runner (FoamRun; tests pass a fake with the same
    start/wait/result/request_stop interface). ``stopping``: the run's criteria; when the app must
    evaluate them (convergence.app_side: an asymptotic criterion exists), every completed
    iteration is checked from the log's residuals and the postProcessing files, and once they
    are met the solver is stopped with the clean stop (it writes the iteration it is in and ends).
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
        stopping: StoppingCriteria | None = None,
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
        self._stopping = stopping if convergence.app_side(stopping) else None
        self._history = ResidualHistory()
        self._reports = ReportMonitor(self.case_dir) if self._stopping is not None else None
        self._met: tuple[str, ...] = ()
        self._met_iteration: int | None = None
        self._pending: TimeStep | None = None  # completed iteration whose criteria are not checked yet

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
        if self._pending is not None and (text.startswith("Time = ") or text.strip() == "End"):
            self._check_criteria()
        self._forward(self.parser.feed(text))

    def _forward(self, events: list) -> None:
        for event in events:
            if isinstance(event, TimeStep):
                if self._stopping is not None and not self._met:
                    self._history.add(event)
                    self._pending = event
                if self._on_step is not None:
                    self._on_step(event)

    def _check_criteria(self) -> None:
        """Reader thread: evaluate the app-side criteria of the last completed iteration; once met,
        remember them and stop the solver cleanly.

        Called on the line after the iteration (the next "Time = " or "End"): v2606 runs the
        function objects of iteration n after its ExecutionTime line (Time::run, at the start of
        the next loop), so only then are its rows in the postProcessing files. That line is
        printed after the time increment to n + 1, and v2606 applies the stop signal at the next
        increment (Time::operator++, stopAt writeNow: endTime = the new time), so the solver runs
        and writes iteration n + 2, then ends (measured on the coarse sphere)."""
        step, self._pending = self._pending, None
        if self._stopping is None or self._met or step is None:
            return
        assert self._reports is not None
        self._reports.poll()
        reports = self._reports

        def upto(quantity: str):  # the rows up to this iteration (a file is never ahead of the log)
            return [row for row in reports.series(quantity) if row[0] <= step.time]

        statuses = convergence.evaluate(self._stopping, self._history.series, upto)
        met = convergence.criteria_met(self._stopping, statuses, step.time)
        if not met:
            return
        with self._lock:
            self._met, self._met_iteration = met, int(step.time)
            runner = self._runner
        if runner is not None:
            runner.request_stop()

    @property
    def criteria_met(self) -> tuple[str, ...]:
        """The app-side criteria met so far (names), () before."""
        return self._met

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
            if stop or self._met:  # requested while starting
                runner.request_stop()
            runner.wait()
            res = runner.result()
        except (OSError, ValueError, RuntimeError) as exc:
            error = f"Could not run {SOLVER}: {exc}"
        self._forward(self.parser.close())
        with self._lock:
            self._runner = None
            stop = self._stop
            met, met_iteration = self._met, self._met_iteration
        if not met and self.parser.criteria_met is not None:  # runTimeControl stopped it
            met = self.parser.criteria_met.conditions
            after = self.parser.criteria_met.after
            met_iteration = int(after) if after is not None else _iterations(self.parser)
        if res is None:
            result = SolverRunResult(CRASHED, None, _iterations(self.parser),
                                     final_residuals(self.parser), error, log_file)
        else:
            criteria_stop = bool(self._met) and not stop and not res.timed_out
            stopped = stop or res.stop_requested or res.timed_out
            state = classify(res.exit_code, stopped, self.parser, criteria_stop)
            if state != CRITERIA_MET:
                met, met_iteration = (), None
            result = SolverRunResult(
                state, res.exit_code, _iterations(self.parser), final_residuals(self.parser),
                self.parser.crash or self.parser.fatal_error, res.log_file, res.duration_s,
                met, met_iteration,
            )
        self._result = result
        if self._on_done is not None:
            self._on_done(result)
