"""Incremental OpenFOAM log parser module."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
import math
import re
from typing import Any, overload

# Number pattern: OpenFOAM prints diverged values as nan, -nan, inf or -inf.
_NUM = r"[-+]?(?:nan|inf(?:inity)?|(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)"

# Regex patterns matching standard OpenFOAM solver output
_TIME_RE = re.compile(rf"^Time = ({_NUM})(?=\s|$)", re.IGNORECASE)
_COURANT_RE = re.compile(
    rf"Courant Number mean:\s*({_NUM})\s+max:\s*({_NUM})", re.IGNORECASE
)
_RESIDUAL_RE = re.compile(
    rf"Solving for\s+(\w+),\s*Initial residual\s*=\s*({_NUM}),"
    rf"\s*Final residual\s*=\s*({_NUM}),\s*No Iterations\s+(\d+)",
    re.IGNORECASE,
)
# setDeltaT.H (adjustTimeStep, v2606): "deltaT = <value>", printed before the step's "Time = " line.
_DELTA_T_RE = re.compile(rf"^deltaT = ({_NUM})$")
_EXEC_TIME_RE = re.compile(rf"^ExecutionTime\s*=\s*({_NUM})", re.IGNORECASE)
# simpleControl::loop (v2606) when every residualControl target is met:
# "SIMPLE solution converged in <time> iterations".
_CONVERGED_RE = re.compile(rf"^(\w+) solution converged in ({_NUM}) iterations")
# runTimeControl (v2606) when its conditions are met: one "<type>: <name> condition satisfied"
# line per satisfied condition, then "Stopping calculation" (satisfiedAction end).
_CONDITION_RE = re.compile(r"^(\w+): (\S+) condition satisfied$")
_STOPPING = "Stopping calculation"
_FATAL_START_RE = re.compile(r"^-->\s*FOAM\s*FATAL")
_FATAL_END_RE = re.compile(r"^FOAM (?:exiting|aborting)")
_TRACE_START = "[stack trace]"
_TRACE_RULE = "============="

# A fatal-error or stack-trace block is closed after this many lines even without a
# terminator, so that it can never swallow the rest of the log.
MAX_BLOCK_LINES = 60
MAX_PARSE_ERRORS_KEPT = 20


@dataclass
class TimeStep:
    """Parsed time step data from solver logs."""

    time: float
    courant_mean: float | None = None
    courant_max: float | None = None
    residuals: list[tuple[str, float, float, int]] = field(default_factory=list)
    execution_time: float | None = None
    # A transient run's time step (s, D-181): the "deltaT = " line of an adaptive step, else the difference from the
    # previous step's time. None for the first step of a fixed-step log and for steady logs.
    delta_t: float | None = None

    @property
    def has_nonfinite(self) -> bool:
        """True if any residual or Courant value of this step is nan or inf."""
        values = [v for _, init, final, _ in self.residuals for v in (init, final)]
        values += [v for v in (self.courant_mean, self.courant_max) if v is not None]
        return any(not math.isfinite(v) for v in values)


@dataclass
class Converged:
    """Event: the solution control reported convergence (residualControl targets reached)."""

    algorithm: str  # e.g. "SIMPLE"
    iterations: float  # the time name printed with the message


@dataclass
class CriteriaMet:
    """Event: runTimeControl met its conditions and is ending the run (D-058)."""

    conditions: tuple[str, ...]  # the satisfied condition names, in the order printed
    after: float | None = None  # the last completed iteration


@dataclass
class NormalEnd:
    """Event representing normal solver termination."""


@dataclass
class FatalError:
    """Event representing a fatal error in solver execution."""

    message: str


@dataclass
class SolverCrash:
    """Event representing a solver crash with an OpenFOAM stack trace (e.g. sigFpe)."""

    message: str


class LogParser(Sequence[TimeStep]):
    """Incremental parser for OpenFOAM solver log streams.

    Accepts output one complete line at a time via ``feed(line)``, emitting newly
    completed events (TimeStep, Converged, CriteriaMet, NormalEnd, FatalError, SolverCrash). Lines that match no
    pattern are ignored silently. Exceptions raised while converting a line that did
    match a pattern are counted in ``parse_error_count`` (last messages in
    ``parse_errors``) and never propagate.
    """

    def __init__(self) -> None:
        self.time_steps: list[TimeStep] = []
        self.events: list[Any] = []
        self.has_ended: bool = False
        self.fatal_error: str | None = None
        self.crash: str | None = None
        self.converged: Converged | None = None
        self.criteria_met: CriteriaMet | None = None
        self._satisfied: list[str] = []
        self.parse_error_count: int = 0
        self.parse_errors: deque[str] = deque(maxlen=MAX_PARSE_ERRORS_KEPT)

        self._current_step: TimeStep | None = None
        self._in_fatal_error: bool = False
        self._fatal_lines: list[str] = []
        self._in_trace: bool = False
        self._trace_lines: list[str] = []
        # pimpleFoam prints the Courant number and the adjusted deltaT before the step's "Time = " line (D-181): kept
        # here until that line opens the step.
        self._pending_courant: tuple[float, float] | None = None
        self._pending_delta_t: float | None = None

    def _emit(self, event: Any, completed: list[Any]) -> None:
        self.events.append(event)
        completed.append(event)

    def _flush_step(self, completed: list[Any]) -> None:
        if self._current_step is not None:
            step = self._current_step
            self._current_step = None
            self.time_steps.append(step)
            self._emit(step, completed)

    def _finish_fatal(self, completed: list[Any]) -> None:
        self._in_fatal_error = False
        self.fatal_error = "\n".join(self._fatal_lines).strip()
        self._emit(FatalError(message=self.fatal_error), completed)

    def _finish_trace(self, completed: list[Any]) -> None:
        self._in_trace = False
        self.crash = "\n".join(self._trace_lines).strip()
        self._emit(SolverCrash(message=self.crash), completed)

    def _record_error(self, line: str, exc: Exception) -> None:
        self.parse_error_count += 1
        self.parse_errors.append(f"{type(exc).__name__}: {exc} | line: {line.rstrip()[:200]}")

    def feed(self, line: str) -> list[Any]:
        """Feed ONE COMPLETE log line into the parser.

        The runner delivers whole lines, so no buffering is done here: a line split
        across two calls is parsed as two separate (usually unrecognised) lines.

        Args:
            line: A single complete log line (trailing newline optional).

        Returns:
            List of newly completed events triggered by this line.
        """
        completed: list[Any] = []

        if self._in_fatal_error:
            self._fatal_lines.append(line.rstrip())
            if _FATAL_END_RE.search(line) or len(self._fatal_lines) >= MAX_BLOCK_LINES:
                self._finish_fatal(completed)
            return completed

        if self._in_trace:
            self._trace_lines.append(line.rstrip())
            closing = line.strip() == _TRACE_RULE and len(self._trace_lines) > 2
            if closing or len(self._trace_lines) >= MAX_BLOCK_LINES:
                self._finish_trace(completed)
            return completed

        stripped = line.strip()

        if _FATAL_START_RE.search(line):
            self._flush_step(completed)
            self._in_fatal_error = True
            self._fatal_lines = [line.rstrip()]
            return completed

        if stripped == _TRACE_START:
            self._flush_step(completed)
            self._in_trace = True
            self._trace_lines = [stripped]
            return completed

        if stripped == "End":
            self._flush_step(completed)
            self.has_ended = True
            self._emit(NormalEnd(), completed)
            return completed

        m_conv = _CONVERGED_RE.match(stripped)
        if m_conv:
            try:
                event = Converged(algorithm=m_conv.group(1), iterations=float(m_conv.group(2)))
            except (ValueError, OverflowError) as exc:
                self._record_error(line, exc)
                return completed
            self._flush_step(completed)
            self.converged = event
            self._emit(event, completed)
            return completed

        m_cond = _CONDITION_RE.match(stripped)
        if m_cond:
            self._satisfied.append(m_cond.group(2))
            return completed

        if stripped == _STOPPING and self._satisfied:
            self._flush_step(completed)
            after = self.time_steps[-1].time if self.time_steps else None
            event = CriteriaMet(tuple(self._satisfied), after)
            self._satisfied = []
            if self.criteria_met is None:
                self.criteria_met = event
                self._emit(event, completed)
            return completed

        m_time = _TIME_RE.match(stripped)
        if m_time:
            try:
                new_time = float(m_time.group(1))
            except (ValueError, OverflowError) as exc:
                self._record_error(line, exc)
                return completed
            self._flush_step(completed)
            self._satisfied = []  # condition lines not followed by a stop (e.g. a trigger action)
            step = TimeStep(time=new_time)
            if self._pending_courant is not None:
                step.courant_mean, step.courant_max = self._pending_courant
            if self._pending_delta_t is not None:
                step.delta_t = self._pending_delta_t
            elif self._pending_courant is not None and self.time_steps:
                step.delta_t = new_time - self.time_steps[-1].time
            self._pending_courant = self._pending_delta_t = None
            self._current_step = step
            return completed

        m_courant = _COURANT_RE.search(line)
        if m_courant:
            try:
                mean, peak = float(m_courant.group(1)), float(m_courant.group(2))
            except (ValueError, OverflowError) as exc:
                self._record_error(line, exc)
                return completed
            if self._current_step is None:  # pimpleFoam: before the step's "Time = " line
                self._pending_courant = (mean, peak)
                return completed
            self._current_step.courant_mean = mean
            self._current_step.courant_max = peak
            return completed

        m_delta = _DELTA_T_RE.match(stripped)
        if m_delta and self._current_step is None:
            try:
                self._pending_delta_t = float(m_delta.group(1))
            except (ValueError, OverflowError) as exc:
                self._record_error(line, exc)
            return completed

        if self._current_step is None:
            return completed

        m_res = _RESIDUAL_RE.search(line)
        if m_res:
            try:
                entry = (
                    m_res.group(1),
                    float(m_res.group(2)),
                    float(m_res.group(3)),
                    int(m_res.group(4)),
                )
            except (ValueError, OverflowError) as exc:
                self._record_error(line, exc)
                return completed
            self._current_step.residuals.append(entry)
            return completed

        m_exec = _EXEC_TIME_RE.match(stripped)
        if m_exec:
            try:
                exec_time = float(m_exec.group(1))
            except (ValueError, OverflowError) as exc:
                self._record_error(line, exc)
                return completed
            self._current_step.execution_time = exec_time
            self._flush_step(completed)  # ExecutionTime marks the end of a time step
        return completed

    def __call__(self, line: str) -> list[Any]:
        """Support using LogParser instance directly as a line callback."""
        return self.feed(line)

    def close(self) -> list[Any]:
        """Flush any pending incomplete time step, fatal-error block or stack trace."""
        completed: list[Any] = []
        self._flush_step(completed)
        if self._in_fatal_error:
            self._finish_fatal(completed)
        if self._in_trace:
            self._finish_trace(completed)
        return completed

    @overload
    def __getitem__(self, index: int) -> TimeStep: ...

    @overload
    def __getitem__(self, index: slice) -> list[TimeStep]: ...

    def __getitem__(self, index: int | slice) -> TimeStep | list[TimeStep]:
        return self.time_steps[index]

    def __len__(self) -> int:
        return len(self.time_steps)

    def __iter__(self) -> Iterator[TimeStep]:
        return iter(self.time_steps)


def parse_log_text(text: str) -> LogParser:
    """Parse complete solver log text into a LogParser object.

    Args:
        text: Complete solver log string.

    Returns:
        LogParser populated with all parsed events and time steps.
    """
    parser = LogParser()
    for line in text.splitlines(keepends=True):
        parser.feed(line)
    parser.close()
    return parser
