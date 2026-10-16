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


def focus_widget(qtbot, window, widget) -> None:
    """Activate ``window``, focus ``widget`` and wait until it really has the keyboard focus.

    Needed before sending keys: on a real display (WSLg) the window may not be active yet.
    If focus cannot be guaranteed on a non-offscreen platform, the test is skipped.
    """
    import os

    from PySide6.QtWidgets import QApplication

    window.activateWindow()
    widget.setFocus()
    try:
        qtbot.waitUntil(lambda: QApplication.focusWidget() is widget, timeout=3000)
    except Exception:
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            pytest.skip("keyboard focus cannot be guaranteed on this display (window not activated)")
        raise
