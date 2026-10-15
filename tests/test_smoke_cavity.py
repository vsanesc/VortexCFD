"""Smoke test running OpenFOAM cavity tutorial with blockMesh and icoFoam."""

from pathlib import Path
import shutil
import pytest

from vortexcfd.foam.runner import run_foam

CAVITY_TUTORIAL = Path(
    "/usr/lib/openfoam/openfoam2606/tutorials/incompressible/icoFoam/cavity/cavity"
)


@pytest.mark.openfoam
def test_smoke_cavity(tmp_path: Path) -> None:
    assert CAVITY_TUTORIAL.is_dir(), f"Cavity tutorial not found at {CAVITY_TUTORIAL}"

    case_dir = tmp_path / "cavity"
    shutil.copytree(CAVITY_TUTORIAL, case_dir)

    mesh_log = case_dir / "log.blockMesh"
    ret_mesh = run_foam(["blockMesh"], case_dir=case_dir, log_file=mesh_log)
    assert ret_mesh == 0, (
        f"blockMesh failed (exit code {ret_mesh}). Log:\n"
        f"{mesh_log.read_text(errors='replace')}"
    )

    solver_log = case_dir / "log.icoFoam"
    ret_solver = run_foam(["icoFoam"], case_dir=case_dir, log_file=solver_log)
    assert ret_solver == 0, (
        f"icoFoam failed (exit code {ret_solver}). Log:\n"
        f"{solver_log.read_text(errors='replace')}"
    )

    final_time_dir = case_dir / "0.5"
    assert final_time_dir.is_dir(), f"Final time directory {final_time_dir} does not exist"

    solver_log_content = solver_log.read_text(encoding="utf-8", errors="replace")
    assert "End" in solver_log_content, "icoFoam log does not contain 'End'"
