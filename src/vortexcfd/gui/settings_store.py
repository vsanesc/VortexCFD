"""QSettings access shared by the GUI modules."""

from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

from vortexcfd.core.user_dirs import settings_dir

ORGANIZATION = "VortexCFD"
APPLICATION = "VortexCFD"

_redirected: str | None = None


def _apply_isolation() -> None:
    """With VORTEXCFD_SETTINGS_DIR set (tests, scripts), every QSettings file lives in that folder."""
    global _redirected
    folder = settings_dir()
    if folder is None or str(folder) == _redirected:
        return
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
            QSettings.setPath(fmt, scope, str(folder))
    _redirected = str(folder)


def settings() -> QSettings:
    """User settings (created on demand so a redirected QSettings path is honored)."""
    _apply_isolation()
    return QSettings(ORGANIZATION, APPLICATION)


def config_dir() -> Path:
    """The user's VortexCFD configuration folder: <generic config location>/VortexCFD (XDG_CONFIG_HOME
    or ~/.config on Linux), or <VORTEXCFD_SETTINGS_DIR>/VortexCFD when isolated (tests, scripts)."""
    folder = settings_dir()
    if folder is not None:
        return folder / APPLICATION
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)
    return Path(base or Path.home() / ".config") / APPLICATION


def presets_dir() -> Path:
    """Where the user presets live (D-077)."""
    return config_dir() / "presets"
