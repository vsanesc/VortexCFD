"""Tests for the FoamRun streaming runner."""

from collections.abc import Callable, Iterator
from pathlib import Path
import signal
import threading
import time

import pytest

from cfdgui.foam.case_writer import enable_clean_stop, write_case
from cfdgui.foam.reference_cases.cavity import CavityParams, build_cavity_files
from cfdgui.foam.runner import FoamRun, RunResult, run_foam


def wait_until(condition: Callable[[], bool], timeout_s: float, message: str) -> None:
    """Poll condition every 20 ms until it is true; fail with message after timeout_s."""
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail(f"Timed out after {timeout_s} s waiting for: {message}")
        time.sleep(0.02)


@pytest.fixture
def make_run() -> Iterator[Callable[..., FoamRun]]:
    """Factory for FoamRun instances; any still running at teardown are stopped."""
    runs: list[FoamRun] = []

    def factory(**kwargs: int) -> FoamRun:
        run = FoamRun(**kwargs)
        runs.append(run)
        return run

    yield factory
    for run in runs:
        if run.is_running():
            run.stop(grace_s=2.0)


def time_dirs_of(case_dir: Path) -> list[str]:
    """Names of the written time directories (> 0) of a case, sorted numerically."""
    return sorted(
        (
            d.name
            for d in case_dir.iterdir()
            if d.is_dir() and d.name.replace(".", "", 1).isdigit() and float(d.name) > 0
        ),
        key=float,
    )


@pytest.mark.openfoam
def test_live_lines_received_before_process_ends(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """Lines arrive via on_line before the process has finished."""
    case_dir = tmp_path / "cavity"
    write_case(case_dir, build_cavity_files(CavityParams()))

    received: list[str] = []
    first_line_event = threading.Event()

    def on_line(line: str) -> None:
        received.append(line)
        first_line_event.set()

    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    runner = make_run()
    runner.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log.icoFoam",
        on_line=on_line,
        timeout_s=120,
    )

    got_line = first_line_event.wait(timeout=30)
    assert runner.wait(timeout=120) is True, "icoFoam did not finish within 120 s"
    res = runner.result()

    assert got_line, "No line received within 30 seconds"
    assert res.exit_code == 0
    assert res.timed_out is False


@pytest.mark.openfoam
def test_log_file_equals_received_lines(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """Log file content must equal the lines received via on_line."""
    case_dir = tmp_path / "cavity"
    write_case(case_dir, build_cavity_files(CavityParams()))
    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    received: list[str] = []
    runner = make_run()
    runner.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log.icoFoam",
        on_line=lambda line: received.append(line),
        timeout_s=120,
    )
    assert runner.wait(timeout=120) is True, "icoFoam did not finish within 120 s"
    res = runner.result()
    assert res.exit_code == 0

    log_text = (case_dir / "log.icoFoam").read_text(encoding="utf-8")
    received_text = "".join(received)
    assert log_text == received_text


def test_timeout_works_on_slow_command(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """Timeout terminates a deliberately slow command (sleep via bash)."""
    runner = make_run()
    log_file = tmp_path / "log.sleep"
    runner.start(
        ["sleep", "3600"],
        case_dir=tmp_path,
        log_file=log_file,
        timeout_s=1.0,
    )
    assert runner.wait(timeout=15) is True, "timeout watcher did not end the process"
    res = runner.result()
    assert res.timed_out is True


def test_callback_exceptions_do_not_break_run(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """An exception in on_line must not prevent the process from completing."""
    call_count = 0

    def bad_callback(line: str) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("deliberate error")

    runner = make_run()
    log_file = tmp_path / "log.echo"
    runner.start(
        ["bash", "-c", "echo line1; echo line2; echo line3"],
        case_dir=tmp_path,
        log_file=log_file,
        on_line=bad_callback,
        timeout_s=30,
    )
    assert runner.wait(timeout=30) is True
    res = runner.result()

    assert res.exit_code == 0
    assert res.callback_errors >= 3
    assert call_count >= 3


@pytest.mark.openfoam
@pytest.mark.parametrize("min_time_lines", [1, 100])
def test_clean_stop_parametrized(
    tmp_path: Path, make_run: Callable[..., FoamRun], min_time_lines: int
) -> None:
    """Clean stop requested after 1 and after 100 time steps have been logged."""
    case_dir = tmp_path / f"cavity_{min_time_lines}"
    params = CavityParams(cells_x=40, cells_y=40, delta_t=0.002, end_time=20.0)
    files = enable_clean_stop(build_cavity_files(params))
    write_case(case_dir, files)
    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    time_lines: list[str] = []

    def on_line(line: str) -> None:
        if line.startswith("Time = "):
            time_lines.append(line)

    runner = make_run()
    runner.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log.icoFoam",
        on_line=on_line,
        clean_stop=True,
        timeout_s=60,
    )

    try:
        wait_until(
            lambda: len(time_lines) >= min_time_lines,
            30,
            f"{min_time_lines} 'Time = ' lines from icoFoam",
        )

        t_req_start = time.monotonic()
        stop_registered = runner.request_stop(grace_s=10.0)
        t_req_duration = time.monotonic() - t_req_start

        assert stop_registered is True
        assert t_req_duration < 1.0

        finished = runner.wait(timeout=10.0)
        assert finished is True, "Process did not finish within 10 seconds of stop request"

        res = runner.result()
        assert res.exit_code == 0
        assert res.stop_mode == "clean"
        assert res.stop_requested is True
        assert res.stopped_by_user is True

        time_dirs = time_dirs_of(case_dir)
        assert time_dirs, "No time directories written"
        last_time = float(time_dirs[-1])
        assert last_time < params.end_time
        assert (case_dir / time_dirs[-1] / "U").is_file()
        assert (case_dir / time_dirs[-1] / "p").is_file()
    finally:
        if runner.is_running():
            runner.stop(grace_s=2.0)


@pytest.mark.openfoam
def test_clean_stop_immediate_after_start(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """Stop requested immediately after start(), before the first time step."""
    case_dir = tmp_path / "cavity_immediate"
    params = CavityParams(cells_x=40, cells_y=40, delta_t=0.002, end_time=20.0)
    files = enable_clean_stop(build_cavity_files(params))
    write_case(case_dir, files)
    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    runner = make_run()
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
        assert t_req_duration < 1.0

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
def test_restart_after_clean_stop(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """After a clean stop, restart from latestTime and check the second run advances."""
    from cfdgui.foam.dictfile import set_foam_entry

    case_dir = tmp_path / "cavity_restart"
    params = CavityParams(cells_x=40, cells_y=40, delta_t=0.002, end_time=20.0)
    files = enable_clean_stop(build_cavity_files(params))
    write_case(case_dir, files)
    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    def run_and_stop(log_name: str, min_steps: int) -> tuple[RunResult, list[float]]:
        """Run icoFoam until min_steps 'Time = ' lines are logged, stop cleanly."""
        time_values: list[float] = []

        def on_line(line: str) -> None:
            if line.startswith("Time = "):
                time_values.append(float(line.split("=")[1]))

        runner = make_run()
        runner.start(
            ["icoFoam"],
            case_dir=case_dir,
            log_file=case_dir / log_name,
            on_line=on_line,
            clean_stop=True,
            timeout_s=60,
        )
        wait_until(lambda: len(time_values) >= min_steps, 30, f"{min_steps} time steps")
        assert runner.request_stop(grace_s=10.0) is True
        assert runner.wait(timeout=10.0) is True, "icoFoam did not stop within 10 s"
        return runner.result(), time_values

    res1, _ = run_and_stop("log1.icoFoam", min_steps=10)
    assert res1.exit_code == 0
    assert res1.stop_mode == "clean"

    time_dirs = time_dirs_of(case_dir)
    assert time_dirs
    restart_time = float(time_dirs[-1])
    assert restart_time < params.end_time

    # Reconfigure case to restart from latestTime
    set_foam_entry(case_dir / "system" / "controlDict", "startFrom", "latestTime")

    res2, second_times = run_and_stop("log2.icoFoam", min_steps=10)
    assert res2.exit_code == 0
    assert res2.stop_mode == "clean"

    log2_text = (case_dir / "log2.icoFoam").read_text(encoding="utf-8")
    assert f"Create mesh for time = {time_dirs[-1]}" in log2_text
    # The second run continued from the restart time instead of starting over
    assert min(second_times) > restart_time
    assert float(time_dirs_of(case_dir)[-1]) > restart_time


def test_kill_path_ignores_sigterm(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """Kill path with clean_stop=False on a process that traps SIGTERM."""
    runner = make_run()
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
    grace = 1.0
    assert runner.request_stop(grace_s=grace) is True
    assert runner.wait(timeout=grace + 5.0) is True

    res = runner.result()
    assert res.stop_mode == "killed"


def test_request_stop_twice_and_after_finished(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """Calling request_stop twice or after finish returns False without changing flags."""
    runner = make_run()
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


def test_start_twice_and_wait_timeout(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """start() twice raises RuntimeError; wait() returns False on timeout."""
    runner = make_run()
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


def test_live_streaming_without_openfoam(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """Live streaming callback receives output before process finishes."""
    runner = make_run()
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


def test_lines_keeps_at_most_keep_last_lines(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """lines retains only the last N lines in memory while log file keeps all."""
    runner = make_run(keep_last_lines=3)
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


def test_clean_stop_requires_sigusr1_switch(tmp_path: Path, make_run: Callable[..., FoamRun]) -> None:
    """start(clean_stop=True) rejects a controlDict without stopAtWriteNowSignal."""
    files = build_cavity_files(CavityParams())
    plain_dir = tmp_path / "plain"
    write_case(plain_dir, files)
    runner = make_run()
    with pytest.raises(ValueError, match="enable_clean_stop"):
        runner.start(["true"], plain_dir, plain_dir / "log", clean_stop=True)
    assert runner.is_running() is False  # failed validation must not start anything

    wrong = enable_clean_stop(files)
    spec = wrong["system/controlDict"]
    content = dict(spec.content)
    content["OptimisationSwitches"] = {"stopAtWriteNowSignal": int(signal.SIGUSR2)}
    wrong["system/controlDict"] = type(spec)(content=content, class_name=spec.class_name)
    wrong_dir = tmp_path / "wrong"
    write_case(wrong_dir, wrong)
    with pytest.raises(ValueError, match="enable_clean_stop"):
        make_run().start(["true"], wrong_dir, wrong_dir / "log", clean_stop=True)

    ok_dir = tmp_path / "ok"
    write_case(ok_dir, enable_clean_stop(files))
    ok = make_run()
    ok.start(["true"], ok_dir, ok_dir / "log", clean_stop=True)
    assert ok.wait(timeout=10) is True


def test_stop_before_start_returns_immediately(make_run: Callable[..., FoamRun]) -> None:
    """stop() on a never-started run must not block; request_stop returns False."""
    runner = make_run()
    result: list[bool] = []
    t = threading.Thread(target=lambda: (runner.stop(), result.append(True)), daemon=True)
    t.start()
    t.join(timeout=2)
    assert result == [True]
    assert runner.request_stop() is False


def test_clean_stop_rejects_unparsable_or_missing_controldict(
    tmp_path: Path, make_run: Callable[..., FoamRun]
) -> None:
    """A garbage or absent controlDict gives ValueError, not a parser exception."""
    garbage_dir = tmp_path / "garbage"
    (garbage_dir / "system").mkdir(parents=True)
    (garbage_dir / "system" / "controlDict").write_text("a { b ( 1 2;\n}\n")
    with pytest.raises(ValueError, match="(?s)cannot be parsed.*enable_clean_stop"):
        make_run().start(["true"], garbage_dir, garbage_dir / "log", clean_stop=True)

    empty_dir = tmp_path / "missing"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="enable_clean_stop"):
        make_run().start(["true"], empty_dir, empty_dir / "log", clean_stop=True)


def test_is_running_false_and_wait_raises_before_start(
    tmp_path: Path, make_run: Callable[..., FoamRun]
) -> None:
    """Before start(): is_running() is False and wait() raises RuntimeError."""
    runner = make_run()
    assert runner.is_running() is False
    with pytest.raises(RuntimeError, match="start\\(\\) has not been called"):
        runner.wait(timeout=0.1)
    runner.start(["true"], tmp_path, tmp_path / "log.true")
    assert runner.wait(timeout=10) is True
    assert runner.is_running() is False
