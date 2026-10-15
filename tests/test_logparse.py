"""Tests for OpenFOAM log parser using fixture data (no OpenFOAM installation needed)."""

import math
from pathlib import Path

import pytest

from cfdgui.foam.logparse import FatalError, LogParser, NormalEnd, parse_log_text

FIXTURE_PATH = Path(__file__).parent / "data" / "cavity_icoFoam.log"


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

    # NormalEnd detected, no fatal error
    assert parser.has_ended is True
    assert parser.fatal_error is None

    # 3. Fields present across the run
    all_fields = {f for step in parser for f, _, _, _ in step.residuals}
    assert all_fields == {"Ux", "Uy", "p"}

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


def test_incremental_feed_matches_parse_log_text() -> None:
    """Feeding line-by-line yields identical events and time steps as parse_log_text."""
    log_text = FIXTURE_PATH.read_text(encoding="utf-8")
    batch_parser = parse_log_text(log_text)

    stream_parser = LogParser()
    emitted_events = []
    for line in log_text.splitlines(keepends=True):
        events = stream_parser.feed(line)
        emitted_events.extend(events)
    stream_parser.close()

    assert len(stream_parser) == len(batch_parser)
    assert stream_parser.has_ended == batch_parser.has_ended
    assert stream_parser.fatal_error == batch_parser.fatal_error

    for s_step, b_step in zip(stream_parser.time_steps, batch_parser.time_steps):
        assert s_step.time == b_step.time
        assert s_step.courant_mean == b_step.courant_mean
        assert s_step.courant_max == b_step.courant_max
        assert s_step.residuals == b_step.residuals
        assert s_step.execution_time == b_step.execution_time


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


def test_parser_with_fatal_error() -> None:
    """Parser detects FOAM FATAL ERROR, captures the message, and ignores garbage lines."""
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
    assert any(isinstance(ev, FatalError) for ev in parser.events)


def test_unknown_lines_ignored_never_raise() -> None:
    """Arbitrary non-OpenFOAM lines are ignored and do not crash the parser."""
    gibberish = (
        "Random gibberish line that OpenFOAM never produces\n"
        "*** [Warning] something non-standard\n"
        "null byte or garbage: \x00\x01\x02\n"
        "Time = not_a_number\n"
        "Solving for completely malformed residual\n"
    )
    parser = parse_log_text(gibberish)
    assert len(parser) == 0
    assert parser.fatal_error is None
    assert parser.has_ended is False
