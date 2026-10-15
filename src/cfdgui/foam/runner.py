"""OpenFOAM process runner module."""

from pathlib import Path
import shlex
import subprocess

OPENFOAM_BASHRC = Path("/usr/lib/openfoam/openfoam2606/etc/bashrc")


def run_foam(command: list[str], case_dir: Path, log_file: Path) -> int:
    """Run an OpenFOAM command with the OpenFOAM environment loaded.

    Sources /usr/lib/openfoam/openfoam2606/etc/bashrc explicitly, runs the
    specified command within the given case directory, writes combined
    stdout and stderr to log_file, and returns the process exit code.

    Args:
        command: Command and arguments to execute (e.g., ["blockMesh"]).
        case_dir: Working directory for the OpenFOAM case.
        log_file: Path where stdout and stderr will be written.

    Returns:
        Process exit code.
    """
    if not command:
        raise ValueError("command must not be empty")

    case_path = Path(case_dir)
    log_path = Path(log_file)

    log_path.parent.mkdir(parents=True, exist_ok=True)

    cmd_str = shlex.join(command)
    shell_cmd = f"source {shlex.quote(str(OPENFOAM_BASHRC))} && exec {cmd_str}"

    with open(log_path, "w", encoding="utf-8") as f:
        result = subprocess.run(
            ["bash", "-c", shell_cmd],
            cwd=case_path,
            stdout=f,
            stderr=subprocess.STDOUT,
            check=False,
        )

    return result.returncode
