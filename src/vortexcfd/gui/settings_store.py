"""QSettings access shared by the GUI modules."""

from PySide6.QtCore import QSettings

ORGANIZATION = "VortexCFD"
APPLICATION = "VortexCFD"


def settings() -> QSettings:
    """User settings (created on demand so a redirected QSettings path is honored)."""
    return QSettings(ORGANIZATION, APPLICATION)
