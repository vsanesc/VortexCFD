"""Headless integration test running OpenFOAM pipeline end-to-end with FoamRun and LogParser."""

import math
from pathlib import Path

import pytest

from cfdgui.foam.case_writer import write_case
from cfdgui.foam.logparse import LogParser, parse_log_text
from cfdgui.foam.reference_cases.cavity import CavityParams, build_cavity_files
from cfdgui.foam.runner import FoamRun, run_foam


@pytest.mark.openfoam
def test_pipeline_headless_cavity(tmp_path: Path) -> None:
    """Full headless pipeline: case generation -> meshing -> solving -> live log parsing."""
    case_dir = tmp_path / "cavity"
    params = CavityParams()
    expected_steps = int(round(params.end_time / params.delta_t))

    # 1. Generate and write case files
    files = build_cavity_files(params)
    write_case(case_dir, files)

    # 2. Run blockMesh
    mesh_log = case_dir / "log.blockMesh"
    ret_mesh = run_foam(["blockMesh"], case_dir=case_dir, log_file=mesh_log)
    assert ret_mesh == 0, f"blockMesh failed with exit code {ret_mesh}"

    # 3. Run icoFoam through FoamRun with LogParser attached as on_line callback
    parser = LogParser()
    runner = FoamRun()
    solver_log = case_dir / "log.icoFoam"

    runner.start(
        ["icoFoam"],
        case_dir=case_dir,
        log_file=solver_log,
        on_line=parser.feed,
        timeout_s=120,
    )
    try:
        assert runner.wait(timeout=120) is True, "icoFoam did not finish within 120 s"
    finally:
        if runner.is_running():
            runner.stop(grace_s=2.0)
    result = runner.result()
    parser.close()

    # 4. Assert process exit code 0
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.stopped_by_user is False

    # 5. Assert parsed time step count equals expected count (100)
    assert len(parser) == expected_steps
    assert len(parser.time_steps) == expected_steps

    # 6. Assert last time equals end_time (0.5)
    last_step = parser[-1]
    assert math.isclose(last_step.time, params.end_time)

    # 7. Assert no fatal error and normal completion
    assert parser.fatal_error is None
    assert parser.has_ended is True

    # 8. Assert parsed final-step residuals are finite numbers
    assert len(last_step.residuals) > 0
    for field_name, init_res, final_res, iters in last_step.residuals:
        assert isinstance(field_name, str) and len(field_name) > 0
        assert math.isfinite(init_res), f"Initial residual for {field_name} is not finite: {init_res}"
        assert math.isfinite(final_res), f"Final residual for {field_name} is not finite: {final_res}"
        assert iters >= 0, f"Iteration count for {field_name} is negative: {iters}"

    # 9. Live parsing (callback during the run) equals parsing the log file written to disk
    disk_parser = parse_log_text(solver_log.read_text(encoding="utf-8"))
    assert parser.events == disk_parser.events
    assert len(parser.events) == expected_steps + 1  # steps + NormalEnd
    assert parser.parse_error_count == disk_parser.parse_error_count == 0
