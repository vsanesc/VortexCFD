"""The logo (D-175): the ported generator rebuilds the owner's saved mark, the generated files, and the logo in the app
(the window icon, the top bar, the start screen), the installer and the report."""

import json
import re
import sys
from pathlib import Path

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

REPO = Path(__file__).parent.parent
BRANDING = REPO / "assets" / "branding"
sys.path.insert(0, str(REPO / "scripts" / "brand"))

import make_logo  # noqa: E402


def test_the_port_rebuilds_the_saved_mark() -> None:
    params = json.loads(make_logo.PARAMS.read_text())
    worst, paths = make_logo.compare(make_logo.SAVED_MARK, params)
    assert paths == 4 and worst <= 0.01
    assert make_logo.mark_svg(params) == make_logo.SAVED_MARK.read_text().rstrip("\n")  # the very file


def test_the_generated_files() -> None:
    for name in ("vortexcfd-mark-notile.svg", "vortexcfd-mark-mono.svg", "vortexcfd-lockup-h-paths.svg",
                 "vortexcfd-lockup-v.svg"):
        text = (BRANDING / name).read_text()
        assert text.startswith("<svg") and "<text" not in text, name  # the word as paths: no font needed
        assert text.count("<svg") == 1, name  # no nested <svg> (QtSvg skips them)
    mono = (BRANDING / "vortexcfd-mark-mono.svg").read_text()
    assert set(re.findall(r'fill="(#[0-9a-f]{6})"', mono)) == {make_logo.MONO} and "<rect" not in mono
    notile = (BRANDING / "vortexcfd-mark-notile.svg").read_text()
    assert "<rect" not in notile and {"#fafafa", "#f59e0b"} <= set(re.findall(r'fill="(#[0-9a-f]{6})"', notile))
    for size in make_logo.PNG_SIZES:
        with Image.open(BRANDING / "png" / f"vortexcfd-{size}.png") as png:
            assert png.size == (size, size) and png.mode == "RGBA"
    with Image.open(BRANDING / "vortexcfd.ico") as ico:
        assert sorted(ico.info["sizes"]) == [(s, s) for s in make_logo.ICO_SIZES]
    lockup = (BRANDING / "vortexcfd-lockup-h-paths.svg").read_text()
    assert 'viewBox="0 0 1874 512"' in lockup  # the saved lockup's frame
    assert (BRANDING / "fonts" / "OFL.txt").read_text().find("SIL Open Font License") >= 0
    from vortexcfd import brand

    assert brand.svg(brand.MARK).rstrip("\n") == make_logo.SAVED_MARK.read_text().rstrip("\n")
    assert brand.svg(brand.LOCKUP_H).rstrip("\n") == lockup.rstrip("\n")


def _colours(pixmap) -> set[tuple[int, int, int]]:
    image = pixmap.toImage()
    return {(c.red() // 16, c.green() // 16, c.blue() // 16) for c in
            (image.pixelColor(x, y) for x in range(0, image.width(), 2) for y in range(0, image.height(), 2))
            if c.alpha() > 200}


@pytest.mark.parametrize("side", [16, 32, 48])
def test_the_app_draws_the_mark(qtbot: QtBot, side: int) -> None:
    from vortexcfd.gui.icons import logo_icon, logo_pixmap
    from vortexcfd.gui.theme import DARK, WINDOW_ICON_SIZES

    pm = logo_pixmap(DARK, side)
    assert pm.width() == side and pm.height() == side
    colours = _colours(pm)
    assert (0xf5 // 16, 0x9e // 16, 0x0b // 16) in colours or side == 16  # the amber arms
    assert (0x27 // 16, 0x27 // 16, 0x2a // 16) in colours  # the tile
    icon = logo_icon(DARK, WINDOW_ICON_SIZES)
    assert sorted(s.width() for s in icon.availableSizes()) == sorted(WINDOW_ICON_SIZES)


def test_the_top_bar_and_the_start_screen_show_the_logo(qtbot: QtBot) -> None:
    from tests.fakes import FakeDialogs
    from vortexcfd.gui.main_window import MainWindow
    from vortexcfd.gui.recent import RecentProjects
    from vortexcfd.gui.start_dialogs import StartDialog

    w = MainWindow(None, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    logo = w.top_bar._logo.pixmap()
    assert not logo.isNull() and (0x27 // 16, 0x27 // 16, 0x2a // 16) in _colours(logo)
    assert not w.windowIcon().isNull()
    dialog = StartDialog(RecentProjects())
    qtbot.addWidget(dialog)
    title = dialog.findChild(type(w.top_bar._logo), "welcomeTitle")
    assert title.pixmap() is not None and not title.pixmap().isNull() and title.accessibleName() == "VortexCFD"
    w.close()


def test_the_report_carries_the_mark(tmp_path: Path) -> None:
    from tests.test_report import solved_project
    from vortexcfd.workflow import report

    text = report.build_report(solved_project(tmp_path), [])
    header = text[text.index("<header"):text.index("</header>")]
    assert '<svg class="mark" width="48" height="48"' in header and "<h1>demo</h1>" in header
    assert "src=" not in header  # inline: the report stays one file


def test_the_logo_licence() -> None:
    """The logo is CC BY-SA 4.0, apart from the code (D-177): the licence text, THIRD_PARTY_LICENSES.md, the README."""
    text = (BRANDING / "LICENSE").read_text(encoding="utf-8")
    assert "Attribution-ShareAlike 4.0 International" in text and "Section 8 -- Interpretation." in text
    assert "assets/branding/" in text and "src/vortexcfd/brand/" in text and "fonts/OFL.txt" in text
    third = (REPO / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    assert "CC BY-SA 4.0" in third and "to be chosen" not in third
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "CC BY-SA 4.0" in readme and "assets/branding/LICENSE" in readme
    assert "suggests your fork is the official VortexCFD project" in readme.replace("\n", " ")
