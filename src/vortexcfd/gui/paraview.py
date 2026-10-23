"""Open in ParaView (D-055, D-138): ParaView is optional. Find it (the configured path, ``paraview`` on PATH, or the
Windows ParaView under C:\\Program Files), convert the case path for a Windows one, launch it detached."""

import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from vortexcfd.gui.settings_store import settings

SETTING = "paraview/executable"
PROGRAM_FILES = Path("/mnt/c/Program Files")
COMMAND = "paraview"  # the Linux ParaView (Ubuntu's package puts it in /usr/bin)
which: Callable[[str], str | None] = shutil.which  # replaced in tests


def not_found_tip() -> str:
    """The tooltip of the disabled button: ParaView is optional, and how to get it."""
    missing = configured_missing()
    distro = os.environ.get("WSL_DISTRO_NAME", "<distribution>")
    head = "ParaView is optional and was not found (not on PATH, not under C:\\Program Files\\ParaView*)."
    if missing:
        head = f"{missing_note(missing)}\n{head}"
    return (f"{head}\nTo open results in ParaView, either install it in Ubuntu:\n    sudo apt install paraview\n"
            f"or install ParaView for Windows and open the case through \\\\wsl$\\{distro}\\... (the case folder's "
            "case.foam, an empty file; create it if missing). This button finds C:\\Program Files\\ParaView* itself.\n"
            "Another place: set the executable in Edit > Preferences.")


def _version(path: Path) -> tuple[int, ...]:
    """Version numbers in the install folder name ("ParaView 5.13.2" -> (5, 13, 2))."""
    folder = path.parent.parent.name
    return tuple(int(n) for n in re.findall(r"\d+", folder))


def detect_windows(root: Path | None = None) -> Path | None:
    """The newest <root>/ParaView*/bin/paraview.exe (by the version in the folder name), or None.
    ``root`` defaults to PROGRAM_FILES (/mnt/c/Program Files); only that folder is listed, nothing is run."""
    root = PROGRAM_FILES if root is None else root
    try:
        found = [p for p in Path(root).glob("ParaView*/bin/paraview.exe") if p.is_file()]
    except OSError:
        return None
    return max(found, key=lambda p: (_version(p), p.name)) if found else None


def on_path() -> Path | None:
    """``paraview`` on PATH (the Linux ParaView), or None."""
    found = which(COMMAND)
    return Path(found) if found else None


def detect(root: Path | None = None) -> Path | None:
    """ParaView on PATH first, else the Windows ParaView (``detect_windows``), else None."""
    return on_path() or detect_windows(root)


def configured() -> str:
    """The path set in Preferences ("" when unset)."""
    return str(settings().value(SETTING, "") or "")


def set_configured(path: str) -> None:
    s = settings()
    if path:
        s.setValue(SETTING, path)
    else:
        s.remove(SETTING)
    s.sync()


def configured_missing() -> str:
    """The path set in Preferences when that file does not exist ("" when unset or present)."""
    path = configured()
    return path if path and not Path(path).is_file() else ""


def missing_note(path: str) -> str:
    return f"The ParaView set in Edit > Preferences was not found: {path}."


def executable(root: Path | None = None) -> Path | None:
    """The configured executable if it exists, otherwise the detected one (also when the configured path does not
    exist: QUESTIONS 220), otherwise None."""
    path = configured()
    if path and Path(path).is_file():
        return Path(path)
    return detect(root)


def is_windows(exe: Path) -> bool:
    """A Windows executable (paraview.exe), which needs a Windows path to the case."""
    return Path(exe).suffix.lower() == ".exe"


def windows_path(path: Path, run: Callable = subprocess.run) -> str:
    """The Windows form of a WSL path (``wslpath -w``)."""
    result = run(["wslpath", "-w", str(path)], capture_output=True, text=True, check=True, timeout=10)
    return result.stdout.strip()


def launch(exe: Path, case_dir: Path, run: Callable = subprocess.run, popen: Callable = subprocess.Popen):
    """Write <case_dir>/case.foam and start ParaView on it, detached (returns the Popen at once). A Windows ParaView
    gets the file's Windows path, a Linux one the path itself."""
    foam = Path(case_dir) / "case.foam"
    foam.touch(exist_ok=True)
    target = windows_path(foam, run) if is_windows(exe) else str(foam)
    return popen([str(exe), target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
