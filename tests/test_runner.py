"""Tests for the FoamRun streaming runner."""

import os
from pathlib import Path
import threading
import time

import pytest

from cfdgui.foam.case_writer import enable_clean_stop, write_case
from cfdgui.foam.reference_cases.cavity import CavityParams, build_cavity_files
from cfdgui.foam.runner import FoamRun, RunResult, run_foam


@pytest.mark.openfoam
def test_live_lines_received_before_process_ends(tmp_path: Path) -> None:
    """Lines arrive via on_line before the process has finished."""
    case_dir = tmp_path / "cavity"
    write_case(case_dir, build_cavity_files(CavityParams()))

    received: list[str] = []
    first_line_event = threading.Event()

    def on_line(line: str) -> None:
        received.append(line)
        first_line_event.set()

    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    runner = FoamRun()
    runner.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log.icoFoam",
        on_line=on_line,
        timeout_s=120,
    )

    got_line = first_line_event.wait(timeout=30)
    runner.wait(timeout=120)
    res = runner.result()

    assert got_line, "No line received within 30 seconds"
    assert len(received) > 0
    assert res.exit_code == 0
    assert res.timed_out is False


@pytest.mark.openfoam
def test_log_file_equals_received_lines(tmp_path: Path) -> None:
    """Log file content must equal the lines received via on_line."""
    case_dir = tmp_path / "cavity"
    write_case(case_dir, build_cavity_files(CavityParams()))
    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    received: list[str] = []
    runner = FoamRun()
    runner.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log.icoFoam",
        on_line=lambda line: received.append(line),
        timeout_s=120,
    )
    runner.wait(timeout=120)
    res = runner.result()
    assert res.exit_code == 0

    log_text = (case_dir / "log.icoFoam").read_text(encoding="utf-8")
    received_text = "".join(received)
    assert log_text == received_text


def test_timeout_works_on_slow_command(tmp_path: Path) -> None:
    """Timeout terminates a deliberately slow command (sleep via bash)."""
    runner = FoamRun()
    log_file = tmp_path / "log.sleep"
    runner.start(
        ["sleep", "3600"],
        case_dir=tmp_path,
        log_file=log_file,
        timeout_s=1.0,
    )
    runner.wait(timeout=15)
    res = runner.result()
    assert res.timed_out is True
    assert res.duration_s < 15


def test_callback_exceptions_do_not_break_run(tmp_path: Path) -> None:
    """An exception in on_line must not prevent the process from completing."""
    call_count = 0

    def bad_callback(line: str) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("deliberate error")

    runner = FoamRun()
    log_file = tmp_path / "log.echo"
    runner.start(
        ["bash", "-c", "echo line1; echo line2; echo line3"],
        case_dir=tmp_path,
        log_file=log_file,
        on_line=bad_callback,
        timeout_s=30,
    )
    runner.wait(timeout=30)
    res = runner.result()

    assert res.exit_code == 0
    assert res.callback_errors >= 3
    assert call_count >= 3


@pytest.mark.openfoam
@pytest.mark.parametrize("delay_s", [1.0, 2.0])
def test_clean_stop_parametrized(tmp_path: Path, delay_s: float) -> None:
    """Parametrized clean stop at 1s and 2s after the first 'Time = ' line."""
    case_dir = tmp_path / f"cavity_{delay_s}"
    params = CavityParams(cells_x=40, cells_y=40, delta_t=0.002, end_time=20.0)
    files = enable_clean_stop(build_cavity_files(params))
    write_case(case_dir, files)
    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    time_stamp: dict[str, float] = {}
    first_time_event = threading.Event()

    def on_line(line: str) -> None:
        if line.startswith("Time = ") and "first" not in time_stamp:
            time_stamp["first"] = time.monotonic()
            first_time_event.set()

    runner = FoamRun()
    runner.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log.icoFoam",
        on_line=on_line,
        clean_stop=True,
        timeout_s=60,
    )

    try:
        assert first_time_event.wait(timeout=30), "First 'Time = ' line did not arrive"
        elapsed = time.monotonic() - time_stamp["first"]
        if delay_s > elapsed:
            time.sleep(delay_s - elapsed)

        t_req_start = time.monotonic()
        stop_registered = runner.request_stop(grace_s=10.0)
        t_req_duration = time.monotonic() - t_req_start

        assert stop_registered is True
        assert t_req_duration < 0.2

        finished = runner.wait(timeout=3.0)
        assert finished is True, "Process did not finish within 3 seconds of stop request"

        res = runner.result()
        assert res.exit_code == 0
        assert res.stop_mode == "clean"
        assert res.stop_requested is True
        assert res.stopped_by_user is True

        time_dirs = sorted(
            [
                d.name
                for d in case_dir.iterdir()
                if d.is_dir()
                and d.name.replace(".", "", 1).isdigit()
                and float(d.name) > 0
            ],
            key=float,
        )
        assert time_dirs, "No time directories written"
        last_time = float(time_dirs[-1])
        assert last_time < params.end_time
        assert (case_dir / time_dirs[-1] / "U").is_file()
        assert (case_dir / time_dirs[-1] / "p").is_file()
    finally:
        if runner.is_running():
            runner.stop(grace_s=2.0)


@pytest.mark.openfoam
def test_clean_stop_immediate_after_start(tmp_path: Path) -> None:
    """Stop requested immediately after start(), before the first time step."""
    case_dir = tmp_path / "cavity_immediate"
    params = CavityParams(cells_x=40, cells_y=40, delta_t=0.002, end_time=20.0)
    files = enable_clean_stop(build_cavity_files(params))
    write_case(case_dir, files)
    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    runner = FoamRun()
    runner.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log.icoFoam",
        clean_stop=True,
        timeout_s=60,
    )
    try:
        t_req_start = time.monotonic()
        registered = runner.request_stop(grace_s=10.0)
        t_req_duration = time.monotonic() - t_req_start

        assert registered is True
        assert t_req_duration < 0.2

        finished = runner.wait(timeout=30.0)
        assert finished is True, "Process did not finish after immediate stop request"

        res = runner.result()
        assert res.exit_code == 0, f"Expected exit code 0, got {res.exit_code}"
        assert res.stop_mode == "clean"
        assert res.stop_requested is True
    finally:
        if runner.is_running():
            runner.stop(grace_s=2.0)


@pytest.mark.openfoam
def test_restart_after_clean_stop(tmp_path: Path) -> None:
    """After a clean stop, reconfigure startFrom latestTime and run again cleanly."""
    from cfdgui.foam.dictfile import set_foam_entry

    case_dir = tmp_path / "cavity_restart"
    params = CavityParams(cells_x=40, cells_y=40, delta_t=0.002, end_time=20.0)
    files = enable_clean_stop(build_cavity_files(params))
    write_case(case_dir, files)
    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    first_time_event = threading.Event()
    runner1 = FoamRun()
    runner1.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log1.icoFoam",
        on_line=lambda l: first_time_event.set() if l.startswith("Time = ") else None,
        clean_stop=True,
        timeout_s=60,
    )
    try:
        assert first_time_event.wait(timeout=30)
        time.sleep(1.0)
        runner1.stop(grace_s=10.0)
        res1 = runner1.result()
        assert res1.exit_code == 0
        assert res1.stop_mode == "clean"

        time_dirs = sorted(
            [
                d.name
                for d in case_dir.iterdir()
                if d.is_dir()
                and d.name.replace(".", "", 1).isdigit()
                and float(d.name) > 0
            ],
            key=float,
        )
        assert time_dirs
        last_time_str = time_dirs[-1]

        # Reconfigure case to restart from latestTime
        control_dict = case_dir / "system" / "controlDict"
        set_foam_entry(control_dict, "startFrom", "latestTime")

        runner2 = FoamRun()
        runner2.start(
            ["icoFoam"],
            case_dir=case_dir,
            log_file=case_dir / "log2.icoFoam",
            clean_stop=True,
            timeout_s=60,
        )
        try:
            time.sleep(1.0)
            runner2.stop(grace_s=10.0)
            res2 = runner2.result()
            assert res2.exit_code == 0
            assert res2.stop_mode == "clean"

            log2_text = (case_dir / "log2.icoFoam").read_text(encoding="utf-8")
            assert f"Create mesh for time = {last_time_str}" in log2_text
        finally:
            if runner2.is_running():
                runner2.stop(grace_s=2.0)
    finally:
        if runner1.is_running():
            runner1.stop(grace_s=2.0)


def test_kill_path_ignores_sigterm(tmp_path: Path) -> None:
    """Kill path with clean_stop=False on a process that traps SIGTERM."""
    runner = FoamRun()
    log_file = tmp_path / "log.kill"
    ready_event = threading.Event()

    def on_line(line: str) -> None:
        if "READY" in line:
            ready_event.set()

    runner.start(
        ["bash", "-c", 'trap "" TERM; echo READY; sleep 60'],
        case_dir=tmp_path,
        log_file=log_file,
        on_line=on_line,
        clean_stop=False,
        timeout_s=60,
    )
    assert ready_event.wait(timeout=10), "Process did not start in time"
    t0 = time.monotonic()
    grace = 1.0
    assert runner.request_stop(grace_s=grace) is True
    assert runner.wait(timeout=grace + 5.0) is True
    t_elapsed = time.monotonic() - t0

    res = runner.result()
    assert res.stop_mode == "killed"
    assert t_elapsed <= grace + 5.0


def test_request_stop_twice_and_after_finished(tmp_path: Path) -> None:
    """Calling request_stop twice or after finish returns False without changing flags."""
    runner = FoamRun()
    log_file = tmp_path / "log.echo"
    runner.start(
        ["bash", "-c", "sleep 0.5"],
        case_dir=tmp_path,
        log_file=log_file,
        clean_stop=False,
    )
    assert runner.request_stop() is True
    # Second call while running
    assert runner.request_stop() is False

    assert runner.wait(timeout=10) is True
    res = runner.result()
    assert res.stop_requested is True

    # Call after process is finished
    assert runner.request_stop() is False
    res2 = runner.result()
    assert res2.stop_requested is True


def test_start_twice_and_wait_timeout(tmp_path: Path) -> None:
    """start() twice raises RuntimeError; wait() returns False on timeout."""
    runner = FoamRun()
    log_file = tmp_path / "log.sleep"
    runner.start(
        ["sleep", "10"],
        case_dir=tmp_path,
        log_file=log_file,
        timeout_s=30,
    )
    try:
        with pytest.raises(RuntimeError, match="already been called"):
            runner.start(
                ["sleep", "5"],
                case_dir=tmp_path,
                log_file=log_file,
            )
        assert runner.wait(timeout=0.1) is False
    finally:
        runner.stop(grace_s=1.0)


def test_live_streaming_without_openfoam(tmp_path: Path) -> None:
    """Live streaming callback receives output before process finishes."""
    runner = FoamRun()
    log_file = tmp_path / "log.stream"
    timestamps: dict[str, float] = {}

    def on_line(line: str) -> None:
        stripped = line.strip()
        if stripped in ("a", "b"):
            timestamps[stripped] = time.monotonic()

    runner.start(
        ["bash", "-c", "echo a; sleep 1; echo b"],
        case_dir=tmp_path,
        log_file=log_file,
        on_line=on_line,
    )
    assert runner.wait(timeout=10) is True
    end_time = time.monotonic()

    assert "a" in timestamps
    assert "b" in timestamps
    assert (end_time - timestamps["a"]) >= 0.8


def test_lines_keeps_at_most_keep_last_lines(tmp_path: Path) -> None:
    """lines retains only the last N lines in memory while log file keeps all."""
    runner = FoamRun(keep_last_lines=3)
    log_file = tmp_path / "log.lines"
    runner.start(
        ["bash", "-c", "for i in $(seq 1 10); do echo line$i; done"],
        case_dir=tmp_path,
        log_file=log_file,
    )
    assert runner.wait(timeout=10) is True

    lines = runner.lines
    assert len(lines) == 3
    assert [l.strip() for l in lines] == ["line8", "line9", "line10"]
    assert len(log_file.read_text(encoding="utf-8").splitlines()) == 10


def test_clean_stop_requires_sigusr1_switch(tmp_path: Path) -> None:
    """start(clean_stop=True) rejects a controlDict without stopAtWriteNowSignal."""
    import signal

    files = build_cavity_files(CavityParams())
    plain_dir = tmp_path / "plain"
    write_case(plain_dir, files)
    runner = FoamRun()
    with pytest.raises(ValueError, match="enable_clean_stop"):
        runner.start(["true"], plain_dir, plain_dir / "log", clean_stop=True)
    assert runner.is_running() is True and runner._process is None  # nothing spawned

    wrong = enable_clean_stop(files)
    spec = wrong["system/controlDict"]
    content = dict(spec.content)
    content["OptimisationSwitches"] = {"stopAtWriteNowSignal": int(signal.SIGUSR2)}
    wrong["system/controlDict"] = type(spec)(content=content, class_name=spec.class_name)
    wrong_dir = tmp_path / "wrong"
    write_case(wrong_dir, wrong)
    with pytest.raises(ValueError, match="enable_clean_stop"):
        FoamRun().start(["true"], wrong_dir, wrong_dir / "log", clean_stop=True)

    ok_dir = tmp_path / "ok"
    write_case(ok_dir, enable_clean_stop(files))
    ok = FoamRun()
    ok.start(["true"], ok_dir, ok_dir / "log", clean_stop=True)
    assert ok.wait(timeout=10) is True


def test_stop_before_start_returns_immediately() -> None:
    """stop() on a never-started run must not block; request_stop returns False."""
    runner = FoamRun()
    result: list[bool] = []
    t = threading.Thread(target=lambda: (runner.stop(), result.append(True)), daemon=True)
    t.start()
    t.join(timeout=2)
    assert result == [True]
    assert runner.request_stop() is False
