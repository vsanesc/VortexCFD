"""A real benchmark run of the sphere case, mesh only (marker ``bench``: run with `pytest -m bench`;
excluded from scripts/ship.sh and from the fast run, D-082)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.bench, pytest.mark.openfoam]


def test_sphere_case_through_the_cli(tmp_path: Path) -> None:
    run = subprocess.run([sys.executable, "-m", "vortexcfd.bench", "--cases", "sphere", "--no-solve",
                          "--out", str(tmp_path)], capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stdout + run.stderr
    (result_file,) = tmp_path.glob("*.json")
    result = json.loads(result_file.read_text())
    (case,) = result["cases"]
    assert not case["failed"] and case["robustness"]["valid"] and case["cells"] > 50_000
    assert case["layers"]["walls"]["coverage_percent"] is not None
    assert case["layers"]["fidelity"]["rms_rel"] < 1e-3
    assert case["quality"]["faces_non_ortho_gt70"] == 0
    assert "| sphere | ok |" in run.stdout
