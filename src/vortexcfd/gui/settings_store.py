"""QSettings access shared by the GUI modules."""

from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

ORGANIZATION = "VortexCFD"
APPLICATION = "VortexCFD"


def settings() -> QSettings:
    """User settings (created on demand so a redirected QSettings path is honored)."""
    return QSettings(ORGANIZATION, APPLICATION)


def config_dir() -> Path:
    """The user's VortexCFD configuration folder: <generic config location>/VortexCFD (XDG_CONFIG_HOME
    or ~/.config on Linux). Tests point XDG_CONFIG_HOME at a temporary folder (tests/conftest.py)."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)
    return Path(base or Path.home() / ".config") / APPLICATION


def presets_dir() -> Path:
    """Where the user presets live (D-077)."""
    return config_dir() / "presets"
