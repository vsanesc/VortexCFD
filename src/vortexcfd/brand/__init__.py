"""The VortexCFD logo as package data (D-175), Qt-free: the mark and the lockups written by
scripts/brand/make_logo.py from assets/branding/vortexcfd-logo-params.json. The GUI renders them (the window icon, the
top bar, the start screen, About), the HTML report embeds the mark."""

from pathlib import Path

FOLDER = Path(__file__).resolve().parent
MARK = "mark.svg"  # the mark on its tile (the owner's saved mark)
LOCKUP_H = "lockup-h.svg"  # the mark and the word, side by side (the word as paths)
LOCKUP_V = "lockup-v.svg"  # the mark above the word


def path(name: str) -> Path:
    return FOLDER / name


def svg(name: str = MARK) -> str:
    """The SVG text of a logo file."""
    return path(name).read_text(encoding="utf-8")
