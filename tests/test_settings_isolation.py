"""Tests and scripts never touch the user's settings; the Recent list skips temporary folders and is pruned (D-141)."""

import os
import subprocess
import sys
from pathlib import Path

from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core import user_dirs
from vortexcfd.core.project import Project
from vortexcfd.foam import installation
from vortexcfd.gui.main_window import start_window
from vortexcfd.gui.recent import RecentProjects
from vortexcfd.gui.settings_store import config_dir, presets_dir, settings


def test_every_test_is_isolated(isolated_settings) -> None:
    folder = Path(os.environ[user_dirs.SETTINGS_DIR_ENV])
    assert str(folder) == isolated_settings and user_dirs.settings_dir() == folder
    assert Path(settings().fileName()).is_relative_to(folder)
    assert config_dir().is_relative_to(folder) and presets_dir().is_relative_to(folder)
    assert installation.config_path().is_relative_to(folder)


def test_a_redirected_folder_is_followed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(user_dirs.SETTINGS_DIR_ENV, str(tmp_path / "other"))
    s = settings()
    s.setValue("probe", 1)
    s.sync()
    assert Path(s.fileName()).is_relative_to(tmp_path / "other")
    assert config_dir() == tmp_path / "other" / "VortexCFD"


def test_isolate_settings_for_scripts(monkeypatch) -> None:
    monkeypatch.delenv(user_dirs.SETTINGS_DIR_ENV)
    folder = user_dirs.isolate_settings("vortexcfd_test_")
    try:
        assert folder.is_dir() and os.environ[user_dirs.SETTINGS_DIR_ENV] == str(folder)
        assert user_dirs.isolate_settings() == folder  # a second call (a child script) keeps it
    finally:
        folder.rmdir()


def test_scripts_isolate_before_anything_else() -> None:
    """Every script that drives the app calls isolate_settings (the benchmark, the validation drivers, the
    manual's images, the screenshots)."""
    repo = Path(__file__).resolve().parent.parent
    scripts = [repo / "scripts" / "manual_images.py", repo / "scripts" / "screenshots.py",
               repo / "src" / "vortexcfd" / "bench" / "cli.py",
               *sorted((repo / "scripts" / "validation").glob("*.py"))]
    for script in scripts:
        assert "isolate_settings(" in script.read_text(encoding="utf-8"), script


def test_a_subprocess_inherits_the_isolation(isolated_settings) -> None:
    code = "from vortexcfd.core.user_dirs import settings_dir; print(settings_dir())"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == isolated_settings


def test_temporary_folders_are_detected(tmp_path: Path) -> None:
    import tempfile

    assert user_dirs.is_temporary(tmp_path / "proj" / "p.vcfd")
    assert user_dirs.is_temporary(Path(tempfile.gettempdir()) / "x.vcfd")
    assert user_dirs.is_temporary(Path("/tmp/claude-1000/a/b.vcfd"))
    assert not user_dirs.is_temporary(Path.home() / "projects" / "wing" / "wing.vcfd")


def test_recent_never_records_a_temporary_project(tmp_path: Path) -> None:
    recent = RecentProjects()
    assert recent.add(tmp_path / "p.vcfd") is False and recent.paths() == []


def test_recent_is_pruned_at_start_up(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    good = Project.create(tmp_path / "home", "Good").path
    gone = tmp_path / "home" / "Gone" / "Gone.vcfd"
    scratch = tmp_path / "scratch" / "s.vcfd"
    scratch.parent.mkdir()
    scratch.write_text("{}")
    # tmp_path stands in for the user's folders; only "scratch" counts as a temporary folder here
    monkeypatch.setattr(user_dirs, "is_temporary", lambda p: Path(p).is_relative_to(tmp_path / "scratch"))
    s = settings()
    s.setValue("recent/projects", [str(p) for p in (scratch, gone, good)])
    s.sync()
    dialogs = FakeDialogs()
    w = start_window([], dialogs)
    qtbot.addWidget(w)
    assert RecentProjects().paths() == [good]
    w._fill_recent_menu()
    assert [a.text() for a in w.recent_menu.actions()][0] == str(good)
    qtbot.waitUntil(lambda: dialogs.start_asked == 1)
    w.close()


def test_recent_keeps_ten(tmp_path: Path, allow_temporary_recent) -> None:
    recent = RecentProjects()
    for i in range(14):
        recent.add(tmp_path / f"p{i}.vcfd")
    assert len(recent.paths()) == 10 and recent.paths()[0] == tmp_path / "p13.vcfd"
