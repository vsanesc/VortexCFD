"""Tests for OpenFOAM log parser using fixture data (no OpenFOAM installation needed)."""

import math
from pathlib import Path

from cfdgui.foam.logparse import (
    MAX_BLOCK_LINES,
    FatalError,
    LogParser,
    NormalEnd,
    SolverCrash,
    TimeStep,
    parse_log_text,
)

DATA = Path(__file__).parent / "data"
FIXTURE_PATH = DATA / "cavity_icoFoam.log"
DIVERGED_PATH = DATA / "cavity_diverged_icoFoam.log"
PITZ_PATH = DATA / "pitzDaily_simpleFoam.log"


def test_log_parser_on_real_cavity_fixture() -> None:
    """Verify parser extracts correct steps, times, fields, and residuals from fixture."""
    assert FIXTURE_PATH.is_file(), f"Fixture file not found: {FIXTURE_PATH}"

    log_text = FIXTURE_PATH.read_text(encoding="utf-8")
    parser = parse_log_text(log_text)

    # 1. Expected number of time steps: 100 (= end_time 0.5 / delta_t 0.005)
    expected_steps = 100
    assert len(parser) == expected_steps
    assert len(parser.time_steps) == expected_steps

    # 2. First and last time
    assert math.isclose(parser[0].time, 0.005)
    assert math.isclose(parser[-1].time, 0.5)

    # NormalEnd detected, no fatal error, no conversion errors
    assert parser.has_ended is True
    assert any(isinstance(ev, NormalEnd) for ev in parser.events)
    assert parser.fatal_error is None
    assert parser.crash is None
    assert parser.parse_error_count == 0

    # Times strictly increasing with constant spacing delta_t = 0.005
    times = [step.time for step in parser]
    for earlier, later in zip(times, times[1:]):
        assert later > earlier
        assert math.isclose(later - earlier, 0.005, abs_tol=1e-9)

    # Every step has an ExecutionTime, and it never decreases
    exec_times = [step.execution_time for step in parser]
    assert all(t is not None for t in exec_times)
    assert all(b >= a for a, b in zip(exec_times, exec_times[1:]))  # type: ignore[operator]

    # Total residual entries equals the number of "Solving for" lines counted independently
    solving_lines = sum(1 for line in log_text.splitlines() if "Solving for" in line)
    assert solving_lines == 400
    assert sum(len(step.residuals) for step in parser) == solving_lines

    # 3. Fields present across the run
    all_fields = {f for step in parser for f, _, _, _ in step.residuals}
    assert all_fields == {"Ux", "Uy", "p"}
    assert not any(step.has_nonfinite for step in parser)

    # 4. Spot check 1: Time = 0.005 (lines 48-52 in cavity_icoFoam.log)
    # Line 48: smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 8.90511e-06, No Iterations 19
    # Line 49: smoothSolver:  Solving for Uy, Initial residual = 0, Final residual = 0, No Iterations 0
    # Line 50: DICPCG:  Solving for p, Initial residual = 1, Final residual = 0.0492854, No Iterations 12
    # Line 52: DICPCG:  Solving for p, Initial residual = 0.590864, Final residual = 2.65225e-07, No Iterations 35
    step_0 = parser[0]
    assert math.isclose(step_0.time, 0.005)
    assert step_0.courant_mean == 0.0
    assert step_0.courant_max == 0.0
    assert len(step_0.residuals) == 4
    assert step_0.residuals[0] == ("Ux", 1.0, 8.90511e-06, 19)
    assert step_0.residuals[1] == ("Uy", 0.0, 0.0, 0)
    assert step_0.residuals[2] == ("p", 1.0, 0.0492854, 12)
    assert step_0.residuals[3] == ("p", 0.590864, 2.65225e-07, 35)

    # 4. Spot check 2: Time = 0.01 (lines 58-63 in cavity_icoFoam.log)
    # Line 58: Courant Number mean: 0.0976825 max: 0.585607
    # Line 59: smoothSolver:  Solving for Ux, Initial residual = 0.160686, Final residual = 6.83031e-06, No Iterations 19
    # Line 60: smoothSolver:  Solving for Uy, Initial residual = 0.260828, Final residual = 9.65939e-06, No Iterations 18
    # Line 61: DICPCG:  Solving for p, Initial residual = 0.428925, Final residual = 0.0103739, No Iterations 22
    # Line 63: DICPCG:  Solving for p, Initial residual = 0.30209, Final residual = 5.26569e-07, No Iterations 33
    step_1 = parser[1]
    assert math.isclose(step_1.time, 0.01)
    assert math.isclose(step_1.courant_mean, 0.0976825)
    assert math.isclose(step_1.courant_max, 0.585607)
    assert len(step_1.residuals) == 4
    assert step_1.residuals[0] == ("Ux", 0.160686, 6.83031e-06, 19)
    assert step_1.residuals[1] == ("Uy", 0.260828, 9.65939e-06, 18)
    assert step_1.residuals[2] == ("p", 0.428925, 0.0103739, 22)
    assert step_1.residuals[3] == ("p", 0.30209, 5.26569e-07, 33)

    # 4. Spot check 3: Time = 0.5 (lines 1135-1140 in cavity_icoFoam.log)
    # Line 1135: Courant Number mean: 0.222158 max: 0.852134
    # Line 1136: smoothSolver:  Solving for Ux, Initial residual = 2.3091e-07, Final residual = 2.3091e-07, No Iterations 0
    # Line 1137: smoothSolver:  Solving for Uy, Initial residual = 5.0684e-07, Final residual = 5.0684e-07, No Iterations 0
    # Line 1138: DICPCG:  Solving for p, Initial residual = 8.63844e-07, Final residual = 8.63844e-07, No Iterations 0
    # Line 1140: DICPCG:  Solving for p, Initial residual = 9.59103e-07, Final residual = 9.59103e-07, No Iterations 0
    step_last = parser[-1]
    assert math.isclose(step_last.time, 0.5)
    assert math.isclose(step_last.courant_mean, 0.222158)
    assert math.isclose(step_last.courant_max, 0.852134)
    assert len(step_last.residuals) == 4
    assert step_last.residuals[0] == ("Ux", 2.3091e-07, 2.3091e-07, 0)
    assert step_last.residuals[1] == ("Uy", 5.0684e-07, 5.0684e-07, 0)
    assert step_last.residuals[2] == ("p", 8.63844e-07, 8.63844e-07, 0)
    assert step_last.residuals[3] == ("p", 9.59103e-07, 9.59103e-07, 0)


def test_events_are_emitted_while_feeding_not_at_the_end() -> None:
    """Events appear incrementally: the first long before the last line, steadily after."""
    lines = FIXTURE_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    parser = LogParser()
    emitted_at: list[int] = []  # line index at which each event was returned by feed()
    for index, line in enumerate(lines):
        emitted_at.extend([index] * len(parser.feed(line)))

    assert len(emitted_at) == 101  # 100 TimeSteps + NormalEnd, none held back for close()
    assert emitted_at[0] < len(lines) // 10
    midpoint_events = sum(1 for i in emitted_at if i < len(lines) // 2)
    assert 40 <= midpoint_events <= 60
    assert parser.close() == []


def test_parser_with_truncated_log() -> None:
    """Parser handles truncated lines and incomplete time steps gracefully."""
    truncated = (
        "Starting time loop\n"
        "Time = 0.005\n"
        "Courant Number mean: 0.1 max: 0.5\n"
        "smoothSolver:  Solving for Ux, Initial residual = 0.5, Final residual = 0.01, No Iterations 5\n"
        # Truncated in the middle of time step: no ExecutionTime or End
    )
    parser = parse_log_text(truncated)
    assert len(parser) == 1
    assert parser[0].time == 0.005
    assert parser[0].courant_mean == 0.1
    assert len(parser[0].residuals) == 1
    assert parser[0].execution_time is None
    assert parser.has_ended is False


def test_nan_inf_and_exponents_are_parsed() -> None:
    """Diverged values (nan, inf, -inf) and negative exponents are parsed, not dropped."""
    text = (
        "Time = 1e-03\n"
        "Courant Number mean: 1.5e+02 max: inf\n"
        "smoothSolver:  Solving for Ux, Initial residual = nan, Final residual = -nan, No Iterations 1000\n"
        "smoothSolver:  Solving for Uy, Initial residual = 1.25E-10, Final residual = -inf, No Iterations 0\n"
        "DICPCG:  Solving for p, Initial residual = 3e-300, Final residual = 4.5e-07, No Iterations 2\n"
        "ExecutionTime = 1.5e-1 s  ClockTime = 0 s\n"
    )
    parser = parse_log_text(text)
    assert len(parser) == 1
    step = parser[0]
    assert step.time == 1e-3
    assert step.courant_mean == 150.0
    assert math.isinf(step.courant_max)
    assert [r[0] for r in step.residuals] == ["Ux", "Uy", "p"]
    assert math.isnan(step.residuals[0][1]) and math.isnan(step.residuals[0][2])
    assert step.residuals[0][3] == 1000
    assert step.residuals[1][1] == 1.25e-10
    assert step.residuals[1][2] == -math.inf
    assert step.residuals[2][1:] == (3e-300, 4.5e-07, 2)
    assert step.execution_time == 0.15
    assert step.has_nonfinite is True
    assert TimeStep(time=0.0, residuals=[("p", 1.0, 0.1, 1)]).has_nonfinite is False
    assert TimeStep(time=0.0, courant_max=math.nan).has_nonfinite is True
    assert parser.parse_error_count == 0


def test_parser_with_fatal_error() -> None:
    """FATAL block is captured with its message, and the pending step is emitted first."""
    error_log = (
        "Create time\n"
        "Starting time loop\n"
        "Time = 0.005\n"
        "Courant Number mean: 0 max: 0\n"
        "smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 8.9e-06, No Iterations 19\n"
        "\n"
        "--> FOAM FATAL IO ERROR: (openfoam-2606)\n"
        "Entry 'p' not found in dictionary \"system/fvSolution/solvers\"\n"
        "\n"
        "file: system/fvSolution/solvers at line 15 to 32.\n"
        "\n"
        "    From const Foam::dictionary& Foam::dictionary::subDict\n"
        "    in file db/dictionary/dictionary.C at line 457.\n"
        "\n"
        "FOAM exiting\n"
    )
    parser = parse_log_text(error_log)
    assert parser.has_ended is False
    assert parser.fatal_error is not None
    assert "Entry 'p' not found" in parser.fatal_error
    assert "FOAM FATAL IO ERROR" in parser.fatal_error
    kinds = [type(ev) for ev in parser.events]
    assert kinds == [TimeStep, FatalError]  # step first, then the error
    assert parser[0].time == 0.005 and len(parser[0].residuals) == 1


def test_fatal_block_ends_on_foam_aborting() -> None:
    """A block closed by 'FOAM aborting' is complete and later lines are parsed normally."""
    log = (
        "--> FOAM FATAL ERROR: (openfoam-2606)\n"
        "Something went wrong\n"
        "\n"
        "FOAM aborting\n"
        "\n"
        "Time = 7\n"
        "ExecutionTime = 1 s\n"
    )
    parser = LogParser()
    events = []
    for line in log.splitlines(keepends=True):
        events.extend(parser.feed(line))
    assert isinstance(events[0], FatalError)  # emitted right at "FOAM aborting", not at close()
    assert events[0].message.endswith("FOAM aborting")
    assert "Time = 7" not in events[0].message
    assert len(parser) == 1 and parser[0].time == 7.0


def test_unterminated_fatal_block_never_swallows_later_lines() -> None:
    """Without a terminator the block is capped and the rest of the log is still parsed."""
    filler = "".join(f"detail line {i}\n" for i in range(MAX_BLOCK_LINES * 2))
    log = "--> FOAM FATAL ERROR:\n" + filler + "Time = 3\nExecutionTime = 2 s\nEnd\n"
    parser = parse_log_text(log)
    assert parser.fatal_error is not None
    assert len(parser.fatal_error.splitlines()) == MAX_BLOCK_LINES
    assert "Time = 3" not in parser.fatal_error
    assert len(parser) == 1 and parser[0].time == 3.0
    assert parser.has_ended is True


def test_close_flushes_pending_fatal_block() -> None:
    """A fatal block still open at end of input is flushed by close()."""
    parser = LogParser()
    for line in ["--> FOAM FATAL ERROR:\n", "cut off here\n"]:
        assert parser.feed(line) == []
    events = parser.close()
    assert len(events) == 1 and isinstance(events[0], FatalError)
    assert "cut off here" in parser.fatal_error  # type: ignore[operator]
    assert parser.close() == []


def test_unknown_lines_ignored_never_raise() -> None:
    """Arbitrary non-OpenFOAM lines are ignored: no events and no parse errors."""
    gibberish = (
        "Random gibberish line that OpenFOAM never produces\n"
        "*** [Warning] something non-standard\n"
        "null byte or garbage: \x00\x01\x02\n"
        "Time = not_a_number\n"
        "Solving for completely malformed residual\n"
    )
    parser = parse_log_text(gibberish)
    assert len(parser) == 0
    assert parser.events == []
    assert parser.fatal_error is None
    assert parser.has_ended is False
    assert parser.parse_error_count == 0


def test_parse_error_counted_when_matched_line_fails_conversion() -> None:
    """A line matching the pattern but failing conversion is counted, kept, and skipped.

    The number patterns only admit strings float() accepts, so the only failing
    conversion is int() on an absurdly long digit string (Python's 4300-digit limit).
    """
    huge = "9" * 5000
    parser = LogParser()
    parser.feed("Time = 1\n")
    parser.feed(f"smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.1, No Iterations {huge}\n")
    parser.feed("smoothSolver:  Solving for Uy, Initial residual = 1, Final residual = 0.1, No Iterations 3\n")
    parser.feed("ExecutionTime = 1 s\n")

    assert parser.parse_error_count == 1
    assert len(parser.parse_errors) == 1
    assert "Solving for Ux" in parser.parse_errors[0]
    assert len(parser) == 1
    assert parser[0].residuals == [("Uy", 1.0, 0.1, 3)]  # parser kept going

    for _ in range(40):
        parser.feed("Time = 2\n")
        parser.feed(f"smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.1, No Iterations {huge}\n")
    assert parser.parse_error_count == 41
    assert len(parser.parse_errors) == 20  # only the last 20 are kept


def test_diverged_cavity_fixture_has_crash_event() -> None:
    """Real diverged icoFoam run: sigFpe stack trace becomes a SolverCrash event.

    Facts read from tests/data/cavity_diverged_icoFoam.log: step Time = 0.5 completed
    normally; step Time = 1 printed only its Courant number (mean 1869.7, max 6677.83)
    before the sigFpe trace; no 'End' line; no nan/inf residuals (sigFpe traps first).
    """
    parser = parse_log_text(DIVERGED_PATH.read_text(encoding="utf-8"))
    assert [type(ev) for ev in parser.events] == [TimeStep, TimeStep, SolverCrash]
    first, pending = parser[0], parser[1]
    assert first.time == 0.5 and first.execution_time is not None
    assert len(first.residuals) == 4
    assert pending.time == 1.0 and pending.execution_time is None
    assert pending.courant_mean == 1869.7 and pending.courant_max == 6677.83
    assert pending.residuals == []
    assert parser.crash is not None
    assert "sigFpe" in parser.crash and parser.crash.startswith("[stack trace]")
    assert parser.has_ended is False and parser.fatal_error is None
    assert parser.parse_error_count == 0


def test_crash_event_emitted_immediately_after_trace() -> None:
    """The pending step is emitted before the crash event, and both come out of feed()."""
    lines = DIVERGED_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    parser = LogParser()
    emitted = [ev for line in lines for ev in parser.feed(line)]
    assert [type(ev) for ev in emitted] == [TimeStep, TimeStep, SolverCrash]
    assert parser.close() == []


def test_pitzdaily_steady_fixture() -> None:
    """Real simpleFoam run (pitzDaily, 20 iterations): several fields, no Courant, End.

    Facts read from tests/data/pitzDaily_simpleFoam.log: 20 'Time =' blocks, 5 'Solving
    for' lines in each (Ux, Uy, p, epsilon, k), no 'Courant' line, ends with 'End'.
    """
    text = PITZ_PATH.read_text(encoding="utf-8")
    parser = parse_log_text(text)

    assert len(parser) == 20
    assert [step.time for step in parser] == [float(i) for i in range(1, 21)]
    assert parser.has_ended is True and parser.fatal_error is None and parser.crash is None
    assert any(isinstance(ev, NormalEnd) for ev in parser.events)
    assert parser.parse_error_count == 0

    assert sum(len(step.residuals) for step in parser) == sum(
        1 for line in text.splitlines() if "Solving for" in line
    )
    for step in parser:
        assert [r[0] for r in step.residuals] == ["Ux", "Uy", "p", "epsilon", "k"]
        assert step.courant_mean is None and step.courant_max is None
        assert step.execution_time is not None
        assert not step.has_nonfinite
    # Iteration 1: Ux, Uy and k start at residual 1
    assert parser[0].residuals[0] == ("Ux", 1.0, 0.0538101, 1)
    assert parser[0].residuals[2] == ("p", 1.0, 0.068427, 17)


def test_several_entries_per_field_in_one_step_are_kept_in_order() -> None:
    """Steady solvers with non-orthogonal correctors print a field several times per step."""
    text = (
        "Time = 1\n"
        "GAMG:  Solving for p, Initial residual = 1, Final residual = 0.1, No Iterations 4\n"
        "GAMG:  Solving for p, Initial residual = 0.5, Final residual = 0.05, No Iterations 3\n"
        "GAMG:  Solving for p, Initial residual = 0.2, Final residual = 0.01, No Iterations 2\n"
        "ExecutionTime = 1 s\n"
    )
    parser = parse_log_text(text)
    assert [r[1] for r in parser[0].residuals] == [1.0, 0.5, 0.2]
    assert parser[0].courant_mean is None
