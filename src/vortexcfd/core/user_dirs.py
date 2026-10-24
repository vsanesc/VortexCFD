"""Where the app keeps the user's settings and configuration, and their isolation for tests and scripts.

``VORTEXCFD_SETTINGS_DIR`` set: the QSettings files and the configuration folder (presets, the OpenFOAM path)
live under that folder instead of the user's ~/.config. tests/conftest.py sets it for every test; every script
that drives the app (the benchmark, the validation drivers, scripts/manual_images.py) calls
``isolate_settings()`` first, so nothing a test or a script does reaches the user's Recent list or presets.
"""

import os
import tempfile
from pathlib import Path

SETTINGS_DIR_ENV = "VORTEXCFD_SETTINGS_DIR"


def settings_dir(env=None) -> Path | None:
    """The isolated settings folder, None: the user's own settings."""
    value = (os.environ if env is None else env).get(SETTINGS_DIR_ENV, "")
    return Path(value) if value else None


def isolate_settings(prefix: str = "vortexcfd_settings_") -> Path:
    """Point this process (and its children) at a fresh temporary settings folder, unless one is already set
    (a script started by a test or by another script keeps its parent's). Returns the folder."""
    current = settings_dir()
    if current is not None:
        return current
    folder = Path(tempfile.mkdtemp(prefix=prefix))
    os.environ[SETTINGS_DIR_ENV] = str(folder)
    return folder


def temporary_roots() -> tuple[Path, ...]:
    """The system's temporary folders (the Recent list never records a project inside them)."""
    roots = {Path(tempfile.gettempdir()), Path("/tmp"), Path("/var/tmp")}
    out = []
    for root in roots:
        out.append(root)
        try:
            out.append(root.resolve())
        except OSError:
            pass
    return tuple(dict.fromkeys(out))


def is_temporary(path: Path) -> bool:
    """True when ``path`` lies inside a system temporary folder (tests, agents' scratch projects)."""
    path = Path(path).absolute()
    candidates = [path]
    try:
        candidates.append(path.resolve())
    except OSError:
        pass
    return any(p.is_relative_to(root) for p in candidates for root in temporary_roots())
