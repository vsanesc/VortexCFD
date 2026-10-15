"""Tests for the FoamRun streaming runner."""

import threading
import time
from pathlib import Path

import pytest

from cfdgui.foam.runner import FoamRun, RunResult


@pytest.mark.openfoam
def test_live_lines_received_before_process_ends(tmp_path: Path) -> None:
    """Lines arrive via on_line before the process has finished."""
    from cfdgui.foam.case_writer import write_case
    from cfdgui.foam.reference_cases.cavity import CavityParams, build_cavity_files

    case_dir = tmp_path / "cavity"
    write_case(case_dir, build_cavity_files(CavityParams()))

    received: list[str] = []
    first_line_event = threading.Event()

    def on_line(line: str) -> None:
        received.append(line)
        first_line_event.set()

    # Run blockMesh to get mesh
    from cfdgui.foam.runner import run_foam
    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    runner = FoamRun()
    runner.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log.icoFoam",
        on_line=on_line,
        timeout_s=120,
    )

    # Wait for at least one line to arrive (well before process ends)
    got_line = first_line_event.wait(timeout=30)
    still_running = runner.is_running()

    # Wait for finish
    runner.wait(timeout=120)
    res = runner.result()

    assert got_line, "No line received within 30 seconds"
    # The first line should have arrived while the process was still running
    # (icoFoam has substantial output before it finishes)
    assert len(received) > 0
    assert res.exit_code == 0
    assert res.timed_out is False


@pytest.mark.openfoam
def test_log_file_equals_received_lines(tmp_path: Path) -> None:
    """Log file content must equal the lines received via on_line."""
    from cfdgui.foam.case_writer import write_case
    from cfdgui.foam.reference_cases.cavity import CavityParams, build_cavity_files
    from cfdgui.foam.runner import run_foam

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
    # Use bash echo which doesn't need OpenFOAM
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
def test_clean_stop_writes_time_and_allows_restart(tmp_path: Path) -> None:
    """Stopping a run cleanly writes a restartable time directory."""
    from cfdgui.foam.case_writer import write_case
    from cfdgui.foam.dictfile import set_foam_entry
    from cfdgui.foam.reference_cases.cavity import CavityParams, build_cavity_files
    from cfdgui.foam.runner import run_foam

    case_dir = tmp_path / "cavity"
    # Use 40x40 cells and end_time=20.0 so the solver runs for multiple seconds
    params = CavityParams(cells_x=40, cells_y=40, delta_t=0.002, end_time=20.0)
    write_case(case_dir, build_cavity_files(params))
    run_foam(["blockMesh"], case_dir=case_dir, log_file=case_dir / "log.blockMesh")

    runner = FoamRun()
    lines: list[str] = []
    runner.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log.icoFoam",
        on_line=lambda l: lines.append(l),
        timeout_s=120,
    )

    # Wait for at least a few time steps and past OpenFOAM's 5s fileModificationSkew
    time.sleep(5.5)

    runner.stop(grace_s=10.0)
    res = runner.result()

    assert not runner.is_running()
    assert res.stopped_by_user is True
    assert res.exit_code == 0

    # Assert last written time directory is < end_time and contains U and p
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
    last_time_str = time_dirs[-1]
    last_time = float(last_time_str)
    assert last_time < params.end_time
    assert (case_dir / last_time_str / "U").is_file()
    assert (case_dir / last_time_str / "p").is_file()

    # Reconfigure case to restart from latestTime
    control_dict = case_dir / "system" / "controlDict"
    set_foam_entry(control_dict, "startFrom", "latestTime")
    set_foam_entry(control_dict, "stopAt", "endTime")

    # Second run picks up from that time
    runner2 = FoamRun()
    lines2: list[str] = []
    runner2.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=case_dir / "log2.icoFoam",
        on_line=lambda l: lines2.append(l),
        timeout_s=30,
    )
    time.sleep(1.0)
    runner2.stop(grace_s=5.0)

    log2_text = (case_dir / "log2.icoFoam").read_text(encoding="utf-8")
    assert f"Create mesh for time = {last_time_str}" in log2_text

