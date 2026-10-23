"""The recent projects list (QSettings, most recent first, D-077, D-141)."""

from pathlib import Path

from vortexcfd.core import user_dirs
from vortexcfd.gui.settings_store import settings

RECENT_KEY = "recent/projects"
MAX_RECENT = 10


class RecentProjects:
    """The last MAX_RECENT project files opened or created. A project inside a system temporary folder is
    never recorded (D-141); ``prune`` (at start-up) drops entries whose file no longer exists."""

    def paths(self) -> list[Path]:
        value = settings().value(RECENT_KEY, [])
        if isinstance(value, str):  # QSettings returns a lone entry as a string
            value = [value]
        out: list[Path] = []
        for item in value or []:
            path = Path(str(item))
            if str(item) and path not in out:
                out.append(path)
        return out[:MAX_RECENT]

    def entries(self) -> list[tuple[Path, bool]]:
        """(path, exists) for every recent project."""
        return [(p, p.is_file()) for p in self.paths()]

    def existing(self) -> list[Path]:
        """The recent projects whose file exists (what the start screen and File > Open Recent show)."""
        return [p for p, exists in self.entries() if exists]

    def add(self, path: Path) -> bool:
        """Put ``path`` at the front; False (nothing stored) for a project in a temporary folder."""
        path = Path(path).absolute()
        if user_dirs.is_temporary(path):
            return False
        self._store([path] + [p for p in self.paths() if p != path])
        return True

    def remove(self, path: Path) -> None:
        self._store([p for p in self.paths() if p != Path(path)])

    def prune(self) -> list[Path]:
        """Drop the entries whose file is gone or that lie in a temporary folder; returns the dropped ones."""
        keep, dropped = [], []
        for path, exists in self.entries():
            (keep if exists and not user_dirs.is_temporary(path) else dropped).append(path)
        if dropped:
            self._store(keep)
        return dropped

    def clear(self) -> None:
        self._store([])

    @staticmethod
    def _store(paths: list[Path]) -> None:
        s = settings()
        s.setValue(RECENT_KEY, [str(p) for p in paths[:MAX_RECENT]])
        s.sync()
