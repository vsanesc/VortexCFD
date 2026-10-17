"""Open in ParaView: find the Windows ParaView, convert the case path, launch it detached (D-055)."""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from vortexcfd.gui.settings_store import settings

SETTING = "paraview/executable"
PROGRAM_FILES = Path("/mnt/c/Program Files")
NOT_FOUND_TIP = ("ParaView was not found under C:\\Program Files\\ParaView*. Set the path of paraview.exe in "
                 "Edit > Preferences (for example /mnt/c/Program Files/ParaView 5.13.2/bin/paraview.exe).")


def _version(path: Path) -> tuple[int, ...]:
    """Version numbers in the install folder name ("ParaView 5.13.2" -> (5, 13, 2))."""
    folder = path.parent.parent.name
    return tuple(int(n) for n in re.findall(r"\d+", folder))


def detect(root: Path | None = None) -> Path | None:
    """The newest <root>/ParaView*/bin/paraview.exe (by the version in the folder name), or None.
    ``root`` defaults to PROGRAM_FILES (/mnt/c/Program Files)."""
    root = PROGRAM_FILES if root is None else root
    try:
        found = [p for p in Path(root).glob("ParaView*/bin/paraview.exe") if p.is_file()]
    except OSError:
        return None
    return max(found, key=lambda p: (_version(p), p.name)) if found else None


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


def executable(root: Path | None = None) -> Path | None:
    """The configured executable if it exists, otherwise the detected one, otherwise None."""
    path = configured()
    if path:
        return Path(path) if Path(path).is_file() else None
    return detect(root)


def windows_path(path: Path, run: Callable = subprocess.run) -> str:
    """The Windows form of a WSL path (``wslpath -w``)."""
    result = run(["wslpath", "-w", str(path)], capture_output=True, text=True, check=True, timeout=10)
    return result.stdout.strip()


def launch(exe: Path, case_dir: Path, run: Callable = subprocess.run, popen: Callable = subprocess.Popen):
    """Write <case_dir>/case.foam and start ParaView on it, detached (returns the Popen at once)."""
    foam = Path(case_dir) / "case.foam"
    foam.touch(exist_ok=True)
    return popen([str(exe), windows_path(foam, run)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
