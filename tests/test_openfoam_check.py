"""The start-up OpenFOAM check (D-137) on fake installations: the configured path, the environment variable and the
standard places, another version, an incomplete install; the command line (no Qt); the window without OpenFOAM
(meshing and solving disabled with the reason, the dialog at start-up, a path set later enables them)."""

import json
import subprocess
import sys
from pathlib import Path

import pyvista as pv
import pytest
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd import __version__, cli
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.foam import installation, runner


def fake_install(root: Path, version: str = "v2606", binaries=installation.REQUIRED_BINARIES) -> Path:
    """An OpenFOAM tree with etc/bashrc declaring ``version`` and empty binaries under platforms/<arch>/bin."""
    (root / "etc").mkdir(parents=True)
    bashrc = root / "etc" / "bashrc"
    bashrc.write_text(f"# fake\nexport WM_PROJECT=OpenFOAM\nexport WM_PROJECT_VERSION={version}\n")
    bins = root / "platforms" / "linux64GccDPInt32Opt" / "bin"
    bins.mkdir(parents=True)
    for name in binaries:
        (bins / name).write_text("")
    return bashrc


def env_for(tmp_path: Path, **extra) -> dict:
    return {"HOME": str(tmp_path / "home"), "XDG_CONFIG_HOME": str(tmp_path / "config"), **extra}


def test_the_standard_place_another_version_and_an_incomplete_install(tmp_path: Path) -> None:
    good = fake_install(tmp_path / "usr" / "openfoam2606")
    old = fake_install(tmp_path / "usr" / "openfoam2312", "v2312")
    broken = fake_install(tmp_path / "opt" / "openfoam2606", binaries=("blockMesh",))
    env = env_for(tmp_path)
    others = ((str(tmp_path / "usr"), "openfoam*/etc/bashrc"),)
    check = installation.check_openfoam(env=env, standard=(broken, good), other_patterns=others)
    assert check.ok and check.bashrc == good
    assert [i.outcome for i in check.looked] == [
        f"incomplete installation: simpleFoam, snappyHexMesh not under {broken.parent.parent / 'platforms'}/*/bin",
        "found"]
    assert check.others == [(old, "v2312")] and check.problem() is None
    # only the other version: not found, and the message says which version is there
    missing = installation.check_openfoam(env=env, standard=(old, tmp_path / "nothing" / "bashrc"),
                                          other_patterns=others)
    assert not missing.ok
    assert [i.outcome for i in missing.looked] == ["OpenFOAM v2312, not v2606", "no such file"]
    assert missing.problem() == "OpenFOAM v2606 was not found (found v2312 instead): Help > OpenFOAM Installation."
    assert "NOT FOUND" in missing.text() and "other version: v2312" in missing.text()


def test_the_configured_path_and_the_environment_come_first(tmp_path: Path) -> None:
    standard = fake_install(tmp_path / "std")
    mine = fake_install(tmp_path / "mine")
    env = env_for(tmp_path)
    assert installation.configured_bashrc(env) is None
    installation.set_configured_bashrc(mine, env)
    stored = json.loads((tmp_path / "config" / "VortexCFD" / "openfoam.json").read_text())
    assert stored == {"bashrc": str(mine)}
    check = installation.check_openfoam(env=env, standard=(standard,), other_patterns=())
    assert check.bashrc == mine and check.looked[0].source == "configured"
    other = fake_install(tmp_path / "env")
    check = installation.check_openfoam(env={**env, installation.BASHRC_ENV: str(other)}, standard=(standard,),
                                        other_patterns=())
    assert check.bashrc == other and check.looked[0].source == "environment"
    # a home-relative standard place
    home = fake_install(tmp_path / "home" / "OpenFOAM" / "OpenFOAM-v2606")
    installation.set_configured_bashrc(None, env)
    check = installation.check_openfoam(env=env, standard=(Path("~/OpenFOAM/OpenFOAM-v2606/etc/bashrc"),),
                                        other_patterns=())
    assert check.bashrc == home


def test_activate_points_the_runner_at_the_bashrc(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "OPENFOAM_BASHRC", runner.OPENFOAM_BASHRC)  # restored after the test
    bashrc = fake_install(tmp_path / "of")
    installation.activate(installation.check_openfoam(env=env_for(tmp_path), standard=(bashrc,), other_patterns=()))
    assert runner.bashrc() == bashrc
    installation.activate(installation.OpenFOAMCheck(None))  # not found: unchanged
    assert runner.bashrc() == bashrc


def test_the_command_line_needs_no_qt(tmp_path: Path, capsys, monkeypatch) -> None:
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out == f"vortexcfd {__version__}\n" and __version__ == "1.1.0"
    code = ("import sys; from vortexcfd.cli import main; main(['--version']); "
            "print('qt' if any(m.startswith('PySide6') for m in sys.modules) else 'no qt')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out == f"vortexcfd {__version__}\nno qt\n"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv(installation.BASHRC_ENV, raising=False)
    monkeypatch.setattr(installation, "STANDARD_BASHRCS", (tmp_path / "none" / "bashrc",))
    monkeypatch.setattr(installation, "OTHER_PATTERNS", ())
    assert cli.main(["--check-openfoam"]) == 1
    out = capsys.readouterr().out
    assert "OpenFOAM v2606: NOT FOUND" in out and "sudo apt-get install openfoam2606-default" in out
    monkeypatch.setenv(installation.BASHRC_ENV, str(fake_install(tmp_path / "of")))
    assert cli.main(["--check-openfoam"]) == 0
    assert "found at" in capsys.readouterr().out


def _window(qtbot: QtBot, tmp_path: Path, check, dialogs=None):
    from vortexcfd.gui.main_window import MainWindow

    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    pv.Sphere(radius=0.5).save(str(folder / "geometry" / "ball.stl"))
    project = Project.new("p")
    project.add_part(Part(name="Ball", source_file="geometry/ball.stl"))
    project.save(folder / "p.vcfd")
    w = MainWindow(project, dialogs or FakeDialogs(), with_viewer=False, openfoam=check)
    qtbot.addWidget(w)
    return w


def test_the_window_without_openfoam(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "OPENFOAM_BASHRC", runner.OPENFOAM_BASHRC)
    missing = installation.check_openfoam(env=env_for(tmp_path), standard=(tmp_path / "x" / "bashrc",),
                                          other_patterns=())
    w = _window(qtbot, tmp_path, missing)
    button = w.top_bar.mesh_button
    assert not button.isEnabled() and "OpenFOAM v2606 was not found" in button.toolTip()
    assert "OpenFOAM v2606 was not found" in w.solve_readiness()
    assert "OpenFOAM v2606 was not found" in w._busy_for_study("mesh")
    w.generate_mesh()  # refused with the reason, nothing written
    assert not (w.project.folder / "case").exists()
    # the user gives a usable bashrc in the dialog: remembered, meshing enabled
    bashrc = fake_install(tmp_path / "of")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    found = installation.check_openfoam(bashrc, env=env_for(tmp_path), standard=(), other_patterns=())
    w.dialogs.openfoam_answer = (found, bashrc)
    w.act_openfoam.trigger()
    assert w.dialogs.openfoam_shown == [missing] and w.openfoam is found
    assert installation.configured_bashrc() == bashrc and runner.bashrc() == bashrc
    assert w.top_bar.mesh_button.isEnabled()
    assert w.solve_readiness() is None or "OpenFOAM" not in w.solve_readiness()


def test_start_up_shows_the_dialog_only_without_openfoam(qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.main_window import start_window

    missing = installation.OpenFOAMCheck(None, [installation.Looked(tmp_path / "bashrc", "standard", "no such file")])
    dialogs = FakeDialogs()
    w = start_window([], dialogs, openfoam=missing)
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: dialogs.openfoam_shown == [missing] and dialogs.start_asked == 1, timeout=5000)
    found = installation.OpenFOAMCheck(fake_install(tmp_path / "of"))
    dialogs2 = FakeDialogs()
    w2 = start_window([], dialogs2, openfoam=found)
    qtbot.addWidget(w2)
    qtbot.waitUntil(lambda: dialogs2.start_asked == 1, timeout=5000)
    assert dialogs2.openfoam_shown == []


def test_the_dialog_shows_the_commands_and_checks_a_path(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    from vortexcfd.gui.openfoam_dialog import OpenFOAMDialog

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(installation, "STANDARD_BASHRCS", (tmp_path / "none" / "bashrc",))
    missing = installation.check_openfoam(other_patterns=())
    dialog = OpenFOAMDialog(missing)
    qtbot.addWidget(dialog)
    assert dialog.commands.toPlainText() == installation.INSTALL_COMMANDS
    assert str(tmp_path / "none" / "bashrc") in dialog.looked.toPlainText()
    assert not dialog.use_button.isEnabled() and dialog.configured_path() is None
    wrong = fake_install(tmp_path / "old", "v2312")
    dialog.set_path(str(wrong))
    assert not dialog.use_button.isEnabled() and "v2312, not v2606" in dialog.looked.toPlainText()
    good = fake_install(tmp_path / "of")
    check = dialog.set_path(str(good))
    assert check.ok and dialog.use_button.isEnabled() and dialog.configured_path() == good


def test_about_shows_the_version(qtbot: QtBot, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from vortexcfd.gui.dialogs import Dialogs

    shown = []
    monkeypatch.setattr(QMessageBox, "about", lambda parent, title, text: shown.append(text))
    Dialogs(None).show_about()
    assert shown and shown[0].startswith(f"VortexCFD {__version__}")


@pytest.mark.skipif(not installation.STANDARD_BASHRCS[0].is_file(), reason="OpenFOAM v2606 not installed")
def test_this_machine_passes() -> None:
    check = installation.check_openfoam(env={"HOME": "/nonexistent"}, other_patterns=())
    assert check.ok and check.bashrc == installation.STANDARD_BASHRCS[0]


def test_help_opens_the_local_manual(qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.main_window import manual_path

    path = manual_path()
    assert path is not None and path.name == "README.md" and path.parent.name == "manual"
    missing = installation.OpenFOAMCheck(None)
    w = _window(qtbot, tmp_path, missing)
    assert w.act_manual.isEnabled() and w.act_manual in w.menuBar().actions()[-1].menu().actions()
    opened = []
    assert w.open_manual(opener=lambda url: opened.append(url.toLocalFile()) or True) == path
    assert opened == [str(path)]
