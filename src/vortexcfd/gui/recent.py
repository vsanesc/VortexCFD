"""The recent projects list (QSettings, most recent first, D-077)."""

from pathlib import Path

from vortexcfd.gui.settings_store import settings

RECENT_KEY = "recent/projects"
MAX_RECENT = 10


class RecentProjects:
    """The last MAX_RECENT project files opened or created. Missing files stay listed (shown as
    "not found") until the user removes them."""

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

    def add(self, path: Path) -> None:
        path = Path(path).absolute()
        self._store([path] + [p for p in self.paths() if p != path])

    def remove(self, path: Path) -> None:
        self._store([p for p in self.paths() if p != Path(path)])

    def clear(self) -> None:
        self._store([])

    @staticmethod
    def _store(paths: list[Path]) -> None:
        s = settings()
        s.setValue(RECENT_KEY, [str(p) for p in paths[:MAX_RECENT]])
        s.sync()
