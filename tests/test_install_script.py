"""scripts/install.sh (D-137) without installing anything: its syntax, that it never runs sudo, and its system checks
(--check-only) on fake environments: the Ubuntu version, OpenFOAM found or missing (the ESI commands printed)."""

import os
import re
import subprocess
from pathlib import Path

from tests.test_openfoam_check import fake_install

SCRIPT = Path(__file__).parent.parent / "scripts" / "install.sh"


def _run(tmp_path: Path, *args: str, os_id="ubuntu", os_version="24.04", **env) -> subprocess.CompletedProcess:
    release = tmp_path / "os-release"
    release.write_text(f'NAME="Test"\nID={os_id}\nVERSION_ID="{os_version}"\n')
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    base = {"PATH": os.environ["PATH"], "HOME": str(home), "VORTEXCFD_OS_RELEASE": str(release),
            "VORTEXCFD_PREFIX": str(tmp_path / "prefix")}
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env={**base, **env},
                          timeout=60)


def test_the_script_parses_and_never_runs_sudo() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    for number, line in enumerate(SCRIPT.read_text().splitlines(), 1):
        code = line.split("#", 1)[0] if not line.lstrip().startswith(("printf", "needs_root", "echo")) else ""
        assert not re.search(r"\bsudo\b", code), f"line {number} runs sudo: {line}"
    assert "set -euo pipefail" in SCRIPT.read_text()


def test_check_only_with_openfoam(tmp_path: Path) -> None:
    bashrc = fake_install(tmp_path / "of")
    result = _run(tmp_path, "--check-only", VORTEXCFD_OPENFOAM_SEARCH=str(bashrc))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok: Ubuntu 24.04" in result.stdout and f"ok: found {bashrc}" in result.stdout
    assert "Check only: nothing installed" in result.stdout
    assert not (tmp_path / "prefix").exists() and list((tmp_path / "home").iterdir()) == []


def test_check_only_without_openfoam_prints_the_commands(tmp_path: Path) -> None:
    old = fake_install(tmp_path / "old", "v2312")
    result = _run(tmp_path, "--check-only", VORTEXCFD_OPENFOAM_SEARCH=f"{old}:{tmp_path / 'none'}")
    assert result.returncode == 3
    out = result.stdout
    assert f"looked at {old}: not v2606" in out and f"looked at {tmp_path / 'none'}: no such file" in out
    for command in ("curl https://dl.openfoam.com/add-debian-repo.sh | sudo bash", "sudo apt-get update",
                    "sudo apt-get install openfoam2606-default"):
        assert f"       {command}\n" in out


def test_the_ubuntu_version_is_checked(tmp_path: Path) -> None:
    bashrc = fake_install(tmp_path / "of")
    result = _run(tmp_path, "--check-only", os_version="22.04", VORTEXCFD_OPENFOAM_SEARCH=str(bashrc))
    assert result.returncode == 1 and "supports Ubuntu 24.04 (found: ubuntu 22.04)" in result.stderr
    result = _run(tmp_path, "--check-only", "--ignore-os", os_version="22.04", VORTEXCFD_OPENFOAM_SEARCH=str(bashrc))
    assert result.returncode == 0 and "is not Ubuntu 24.04 (continuing: --ignore-os)" in result.stdout


def test_a_wrong_python_is_refused(tmp_path: Path) -> None:
    fake = tmp_path / "python3"
    fake.write_text("#!/bin/sh\necho 3.10\n")
    fake.chmod(0o755)
    result = _run(tmp_path, "--check-only", PYTHON=str(fake))
    assert result.returncode == 1 and "Python 3.12 is required (found" in result.stderr
    assert "sudo apt-get install python3.12 python3.12-venv" in result.stdout
