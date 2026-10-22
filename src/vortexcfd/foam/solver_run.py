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

Parallel runs (``cores`` > 1, D-063): ``decomposePar -force`` first (log.decomposePar; its output
and a one-line summary go to ``on_line``), then ``mpirun -np N simpleFoam -parallel`` (the clean
stop's SIGUSR1 goes to mpirun, which forwards it to the ranks), then ``reconstructPar
-latestTime`` (log.reconstructPar) whenever the solver ended with exit code 0 (iteration limit,
criteria met or a clean stop), so the case holds a reconstructed latest time.

Two turbulence stages (D-126; the wall-resolved mode writes physics_case.STAGES_FILE into the case): stage 1 runs
with the case's first-order k and omega convection; the app evaluates the run's stopping criteria and, when they
are met (or at half the iteration limit, if earlier), stops the solver with the clean stop: that is the switch.
The stage-2 entries are then merged into system/fvSchemes, controlDict starts from the latest time, and the same
solver command continues (the same decomposition; the log is appended) to the criteria, which may be met no
earlier than the switch plus the iterations their first evaluation needs (``stage2_criteria``). A stop in either
stage ends the run with its latest time written; the result keeps both stages (``SolverRunResult.stages``).
"""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from vortexcfd.core.model import StoppingCriteria
from vortexcfd.foam.dictfile import read_foam_file, set_foam_entry
from vortexcfd.foam import convergence
from vortexcfd.foam.logparse import LogParser, TimeStep
from vortexcfd.foam.parallel import (
    DECOMPOSE_COMMAND,
    DEFAULT_BINDING,
    RECONSTRUCT_COMMAND,
    parse_decomposition,
    solver_command,
)
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
    cores: int = 1
    decomposition: str | None = None  # decomposePar's summary (parallel runs)
    reconstructed: bool | None = None  # reconstructPar succeeded (None: serial or not attempted)
    # The turbulence stages of a two-stage run (D-126), one dict each: stage, k_omega (the scheme), first and last
    # iteration, and for stage 1 the switch ("criteria met" / "half the iteration limit") and the iteration at
    # which its condition was met. Empty for a single-stage run.
    stages: tuple[dict, ...] = ()
    switch_iteration: int | None = None  # the last iteration of stage 1 (stage 2 starts after it)

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


STAGES_FILE = "system/turbulenceStages"  # physics_case.STAGES_FILE (D-126)
STAGE1_SCHEME = "first order (bounded Gauss upwind)"
STAGE2_SCHEME = "second order (bounded Gauss linearUpwind, cellLimited gradients)"
SWITCH_CRITERIA = "criteria met"
SWITCH_HALF_LIMIT = "half the iteration limit"


def read_stages(case_dir: Path) -> dict | None:
    """The stage-2 fvSchemes entries of a two-stage case ({"divSchemes": ..., "gradSchemes": ...}), None when the
    case has one stage."""
    path = Path(case_dir) / STAGES_FILE
    if not path.is_file():
        return None
    data = read_foam_file(path).get("stage2")
    return dict(data) if isinstance(data, dict) else None


def stage2_criteria(stopping: StoppingCriteria, switch: int) -> StoppingCriteria:
    """The criteria of stage 2: the run's, not met before ``switch`` plus the iterations every criterion needs
    from its first value (convergence.earliest_iteration with the run's minimum: its window, two for mean
    stable, the first residual check), so no window reaches back into stage 1."""
    offset = max((convergence.earliest_iteration(c, stopping.min_iterations) for c in stopping.criteria),
                 default=stopping.min_iterations)
    return stopping.model_copy(update={"min_iterations": switch + offset})


def apply_stage2(case_dir: Path, stage2: dict) -> None:
    """Merge the stage-2 entries into system/fvSchemes and start the next solver run from the latest time."""
    case_dir = Path(case_dir)
    schemes = read_foam_file(case_dir / "system" / "fvSchemes")
    for key, entries in stage2.items():
        merged = dict(schemes.get(key, {}))
        merged.update(entries)
        set_foam_entry(case_dir / "system" / "fvSchemes", key, merged)
    set_foam_entry(case_dir / "system" / "controlDict", "startFrom", "latestTime")


def _end_time(case_dir: Path) -> int | None:
    try:
        return int(read_foam_file(Path(case_dir) / "system" / "controlDict")["endTime"])
    except (OSError, KeyError, TypeError, ValueError):
        return None


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
        on_stage: Callable[[int, int, str], None] | None = None,
        timeout_s: float | None = None,
        runner_factory: Callable[[], FoamRun] = FoamRun,
        stopping: StoppingCriteria | None = None,
        cores: int = 1,
        binding: str = DEFAULT_BINDING,
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
        self.cores = max(1, int(cores))
        self.binding = binding  # mpirun placement (foam/parallel.BINDINGS, D-064)
        self._on_stage = on_stage  # (stage, the switch iteration, the switch reason): the second stage began
        self._stage2 = read_stages(self.case_dir)  # D-126: None for a single-stage case
        self._stage = 1
        self._switching = False  # stage 1's switch condition was met; the clean stop is on its way
        self._switch_reason: str | None = None
        self._switch_met_at: int | None = None
        self._stage1_end: int | None = None  # the last iteration of stage 1 once stage 2 runs
        self._stage1_duration = 0.0  # stage 1's solver time (s), added to the result's
        self._half_limit = (lambda end: end // 2 if end else None)(_end_time(self.case_dir)) if self._stage2 else None
        two_stage_criteria = self._stage2 is not None and stopping is not None and bool(stopping.criteria)
        self._stopping = stopping if convergence.app_side(stopping) or two_stage_criteria else None
        self._run_stopping = self._stopping  # stage 2 replaces it by stage2_criteria
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
                if (self._stopping is not None or self._stage2 is not None) and not self._met and not self._switching:
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
        if self._met or self._switching or step is None:
            return
        met: tuple[str, ...] = ()
        if self._stopping is not None:
            assert self._reports is not None
            self._reports.poll()
            reports = self._reports

            def upto(quantity: str):  # the rows up to this iteration (a file is never ahead of the log)
                return [row for row in reports.series(quantity) if row[0] <= step.time]

            statuses = convergence.evaluate(self._stopping, self._history.series, upto)
            met = convergence.criteria_met(self._stopping, statuses, step.time)
        if self._stage2 is not None and self._stage == 1:  # D-126: the switch, not the end
            half = self._half_limit is not None and step.time >= self._half_limit
            if met or half:
                with self._lock:
                    self._switching = True
                    self._switch_reason = SWITCH_CRITERIA if met else SWITCH_HALF_LIMIT
                    self._switch_met_at = int(step.time)
                    runner = self._runner
                if runner is not None:
                    runner.request_stop()
            return
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

    def _step(self, command: list[str], log_name: str, on_line, clean_stop: bool = False,
              stoppable: bool = True, append: bool = False) -> RunResult:
        """Run one command to the end through a new runner (stopped by request_stop when
        ``stoppable``; reconstructPar, which runs after a stop, is not)."""
        runner = self._factory()
        runner.start(command, self.case_dir, self.case_dir / log_name, on_line=on_line,
                     timeout_s=self._timeout, clean_stop=clean_stop, **({"append": True} if append else {}))
        with self._lock:
            self._runner = runner if stoppable else None
            stop = self._stop
        if stoppable and (stop or (clean_stop and (self._met or self._switching))):  # requested while starting
            runner.request_stop()
        runner.wait()
        with self._lock:
            self._runner = None
        return runner.result()

    def _forward_line(self, text: str) -> None:
        if self._on_line is not None:
            self._on_line(text)

    def _decompose(self) -> tuple[str | None, str | None]:
        """(summary, error) of decomposePar."""
        res = self._step(DECOMPOSE_COMMAND, "log.decomposePar", self._forward_line)
        if res.timed_out or res.stop_requested:  # stopped before the solver started
            with self._lock:
                self._stop = True
            return None, None
        if res.exit_code != 0:
            return None, f"decomposePar failed (exit code {res.exit_code}): see log.decomposePar"
        try:
            found = parse_decomposition((self.case_dir / "log.decomposePar").read_text(errors="replace"))
        except OSError:
            found = None
        summary = found.summary() if found is not None else f"Decomposed into {self.cores} subdomains"
        self._forward_line(summary + "\n")
        return summary, None

    def _reconstruct(self) -> bool:
        res = self._step(RECONSTRUCT_COMMAND, "log.reconstructPar", self._forward_line, stoppable=False)
        ok = res.exit_code == 0
        self._forward_line(("Reconstructed the latest time" if ok else
                            f"reconstructPar failed (exit code {res.exit_code}): see log.reconstructPar") + "\n")
        return ok

    def _run(self) -> None:
        try:
            result = self._execute()
        except Exception as exc:  # noqa: BLE001 - the GUI must always hear of the end of a run
            with self._lock:
                self._runner = None
            result = SolverRunResult(CRASHED, None, 0, {}, f"Could not run {SOLVER}: {type(exc).__name__}: {exc}",
                                     self.case_dir / LOG_NAME, cores=self.cores)
        self._result = result
        if self._on_done is not None:
            self._on_done(result)

    def _execute(self) -> SolverRunResult:
        log_file = self.case_dir / LOG_NAME
        res: RunResult | None = None
        error: str | None = None
        decomposition: str | None = None
        reconstructed: bool | None = None
        try:
            if self.cores > 1:
                decomposition, error = self._decompose()
                with self._lock:
                    stopped_early = self._stop
            if error is None and not (self.cores > 1 and stopped_early):
                command = solver_command(SOLVER, self.cores, self.binding)
                res = self._step(command, LOG_NAME, self._line, clean_stop=True)
                if self._switch_ready(res):
                    self._stage1_duration = res.duration_s
                    res = self._second_stage(command)
                if self.cores > 1 and res.exit_code == 0:
                    reconstructed = self._reconstruct()
        except Exception as exc:  # noqa: BLE001 - classified as crashed below
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
        stages, switch_iteration = self._stages_summary()
        if res is None:
            state = STOPPED if stop and error is None else CRASHED
            result = SolverRunResult(state, None, _iterations(self.parser), final_residuals(self.parser),
                                     error, log_file, cores=self.cores, decomposition=decomposition,
                                     stages=stages, switch_iteration=switch_iteration)
        else:
            criteria_stop = bool(self._met) and not stop and not res.timed_out
            stopped = stop or res.stop_requested or res.timed_out
            if self._switching and self._stage == 1 and not stop and not res.timed_out:
                stopped = False  # stage 1 ended at the switch but stage 2 could not start: see the exit code
            state = classify(res.exit_code, stopped, self.parser, criteria_stop)
            if state != CRITERIA_MET:
                met, met_iteration = (), None
            result = SolverRunResult(
                state, res.exit_code, _iterations(self.parser), final_residuals(self.parser),
                self.parser.crash or self.parser.fatal_error, res.log_file, self._stage1_duration + res.duration_s,
                met, met_iteration, self.cores, decomposition, reconstructed, stages, switch_iteration,
            )
        return result

    def _switch_ready(self, res: RunResult) -> bool:
        """Stage 1 ended at the switch (the app's clean stop, exit code 0, no user stop or timeout)."""
        with self._lock:
            stop = self._stop
        return (self._stage2 is not None and self._stage == 1 and self._switching and not stop
                and res.exit_code == 0 and not res.timed_out
                and self.parser.crash is None and self.parser.fatal_error is None)

    def _second_stage(self, command: list[str]) -> RunResult:
        """The switch (D-126): stage-2 schemes into the case, then the solver again from the latest time."""
        switch = _iterations(self.parser)
        self._stage1_end = switch
        apply_stage2(self.case_dir, self._stage2)
        with self._lock:
            self._stage = 2
            if self._run_stopping is not None:
                self._stopping = stage2_criteria(self._run_stopping, switch)
            self._switching = False
        self._forward_line(f"Turbulence stage 2 from iteration {switch} ({self._switch_reason} at "
                           f"{self._switch_met_at}): k and omega {STAGE2_SCHEME}\n")
        if self._on_stage is not None:
            self._on_stage(2, switch, self._switch_reason or "")
        return self._step(command, LOG_NAME, self._line, clean_stop=True, append=True)

    def _stages_summary(self) -> tuple[tuple[dict, ...], int | None]:
        if self._stage2 is None:
            return (), None
        last = _iterations(self.parser)
        if self._stage == 1:
            return ({"stage": 1, "k_omega": STAGE1_SCHEME, "first": 1, "last": last, "switch": None,
                     "condition_met_at": None},), None
        switch = self._stage1_end
        return ({"stage": 1, "k_omega": STAGE1_SCHEME, "first": 1, "last": switch, "switch": self._switch_reason,
                 "condition_met_at": self._switch_met_at},
                {"stage": 2, "k_omega": STAGE2_SCHEME, "first": switch + 1, "last": last}), switch
