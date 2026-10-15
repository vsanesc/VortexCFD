"""Incremental OpenFOAM log parser module."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
import re
from typing import Any, overload

# Regex patterns matching standard OpenFOAM solver output
_TIME_RE = re.compile(r"^Time = ([0-9.eE+-]+)")
_COURANT_RE = re.compile(
    r"Courant Number mean:\s*([0-9.eE+-]+)\s+max:\s*([0-9.eE+-]+)"
)
_RESIDUAL_RE = re.compile(
    r"Solving for\s+(\w+),\s*Initial residual\s*=\s*([0-9.eE+-]+),\s*Final residual\s*=\s*([0-9.eE+-]+),\s*No Iterations\s+(\d+)"
)
_EXEC_TIME_RE = re.compile(r"^ExecutionTime\s*=\s*([0-9.eE+-]+)")
_FATAL_START_RE = re.compile(r"^-->\s*FOAM\s*FATAL")
_FATAL_END_RE = re.compile(r"^FOAM exiting")


@dataclass
class TimeStep:
    """Parsed time step data from solver logs."""

    time: float
    courant_mean: float | None = None
    courant_max: float | None = None
    residuals: list[tuple[str, float, float, int]] = field(default_factory=list)
    execution_time: float | None = None


@dataclass
class NormalEnd:
    """Event representing normal solver termination."""


@dataclass
class FatalError:
    """Event representing a fatal error in solver execution."""

    message: str


class LogParser(Sequence[TimeStep]):
    """Incremental parser for OpenFOAM solver log streams.

    Accepts output line by line via ``feed(line)``, emitting newly completed
    events (TimeStep, NormalEnd, FatalError). Unknown lines are ignored and
    never raise exceptions.
    """

    def __init__(self) -> None:
        self.time_steps: list[TimeStep] = []
        self.events: list[Any] = []
        self.has_ended: bool = False
        self.fatal_error: str | None = None

        self._current_step: TimeStep | None = None
        self._in_fatal_error: bool = False
        self._fatal_lines: list[str] = []

    def feed(self, line: str) -> list[Any]:
        """Feed a single log line into the parser.

        Args:
            line: Log line to parse.

        Returns:
            List of newly completed events triggered by this line.
        """
        completed: list[Any] = []

        try:
            # Check for FATAL ERROR block
            if self._in_fatal_error:
                self._fatal_lines.append(line.rstrip())
                if _FATAL_END_RE.search(line):
                    self._in_fatal_error = False
                    msg = "\n".join(self._fatal_lines).strip()
                    self.fatal_error = msg
                    err_event = FatalError(message=msg)
                    self.events.append(err_event)
                    completed.append(err_event)
                return completed

            if _FATAL_START_RE.search(line):
                # If there was a pending time step, emit it first
                if self._current_step is not None:
                    self.time_steps.append(self._current_step)
                    self.events.append(self._current_step)
                    completed.append(self._current_step)
                    self._current_step = None
                self._in_fatal_error = True
                self._fatal_lines = [line.rstrip()]
                return completed

            # Check for normal End
            stripped = line.strip()
            if stripped == "End":
                if self._current_step is not None:
                    self.time_steps.append(self._current_step)
                    self.events.append(self._current_step)
                    completed.append(self._current_step)
                    self._current_step = None
                self.has_ended = True
                end_event = NormalEnd()
                self.events.append(end_event)
                completed.append(end_event)
                return completed

            # Check for Time = <time>
            m_time = _TIME_RE.match(stripped)
            if m_time:
                # If there was an uncompleted previous step, emit it now
                if self._current_step is not None:
                    self.time_steps.append(self._current_step)
                    self.events.append(self._current_step)
                    completed.append(self._current_step)
                self._current_step = TimeStep(time=float(m_time.group(1)))
                return completed

            # If inside a time step, match courant, residuals, and execution time
            if self._current_step is not None:
                m_courant = _COURANT_RE.search(line)
                if m_courant:
                    self._current_step.courant_mean = float(m_courant.group(1))
                    self._current_step.courant_max = float(m_courant.group(2))
                    return completed

                m_res = _RESIDUAL_RE.search(line)
                if m_res:
                    entry = (
                        m_res.group(1),
                        float(m_res.group(2)),
                        float(m_res.group(3)),
                        int(m_res.group(4)),
                    )
                    self._current_step.residuals.append(entry)
                    return completed

                m_exec = _EXEC_TIME_RE.match(stripped)
                if m_exec:
                    self._current_step.execution_time = float(m_exec.group(1))
                    # ExecutionTime marks the end of a time step
                    step = self._current_step
                    self._current_step = None
                    self.time_steps.append(step)
                    self.events.append(step)
                    completed.append(step)
                    return completed

        except Exception:
            # Unknown or malformed lines are ignored, never raise
            pass

        return completed

    def __call__(self, line: str) -> list[Any]:
        """Support using LogParser instance directly as a line callback."""
        return self.feed(line)

    def close(self) -> list[Any]:
        """Flush any pending incomplete time step or fatal error."""
        completed: list[Any] = []
        if self._current_step is not None:
            self.time_steps.append(self._current_step)
            self.events.append(self._current_step)
            completed.append(self._current_step)
            self._current_step = None
        if self._in_fatal_error:
            self._in_fatal_error = False
            msg = "\n".join(self._fatal_lines).strip()
            self.fatal_error = msg
            err_event = FatalError(message=msg)
            self.events.append(err_event)
            completed.append(err_event)
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
