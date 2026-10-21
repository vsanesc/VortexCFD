"""Atomic text files (docs/REVIEW.md R-04, R-05).

``write_text_atomic`` writes a temporary file next to the target and replaces the target with it, so a
crash mid-write leaves the old file or the new one, never half a file. The temporary file is created
with mode 0600 (tempfile); it gets the mode a new file would get (0666 minus the process umask) before
the replace, so the result has the same permissions as every other file the app writes.
"""

import os
import tempfile
from pathlib import Path


def process_umask() -> int:
    """The process umask, read without changing it (/proc/self/status on Linux; else set and restored)."""
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("Umask:"):
                return int(line.split()[1], 8)
    except (OSError, ValueError, IndexError):
        pass
    mask = os.umask(0o022)
    os.umask(mask)
    return mask


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` (UTF-8) to ``path`` through a temporary file in the same folder and os.replace.
    The folder must exist."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o666 & ~process_umask())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
