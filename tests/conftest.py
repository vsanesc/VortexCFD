"""Shared fixtures: every test gets isolated QSettings so the user's real ones are never touched."""

import pytest
from PySide6.QtCore import QSettings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("qsettings"))
    # QSettings(org, app) uses the native format; redirect both formats and both scopes.
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
            QSettings.setPath(fmt, scope, path)
    return path
