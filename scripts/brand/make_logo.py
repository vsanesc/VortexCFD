"""The VortexCFD logo from its parameters (D-175): the owner's parametric generator ported to Python.

    .venv/bin/python scripts/brand/make_logo.py            # write every file into assets/branding/
    .venv/bin/python scripts/brand/make_logo.py --check    # only compare the mark with the saved SVG

assets/branding/vortexcfd-logo-params.json holds every parameter of the owner's chosen logo (style "arms"). The mark
(numpy only) is ``arms`` arms around the centre of a 512 x 512 box, each a logarithmic spiral turned by 360 / arms
degrees from the last: its centreline starts at the angle ``rot`` (degrees, SVG y down, ``dir`` its sense) at the
radius ARM_RADIUS and turns through ``sweep`` turns to ``inner`` x ARM_RADIUS; its width goes linearly with the radius
from ``wOut`` to ``wIn``; its outline is the centreline offset by half the width along the normal of the central
differences of the sampled centreline (one-sided at the ends), with round caps (circles) at both ends; with
``colorMode`` "alt" the arms alternate the mark colour and ALT_COLOR. The tile (``tile``) is a rounded square
(``radius``) in the panel colour with a 4-unit border, the arms scaled by ``scale`` about the centre. ARM_RADIUS and
SAMPLES were read off the saved SVG (the generator's own constants); --check proves the port gives the saved paths.

Outputs: the mark as SVG with and without its tile and in one colour; PNGs of the tiled mark at 16 to 1024 px (QtSvg
renders the SVG; offscreen); a multi-size .ico (16 to 256 px, Pillow); the horizontal and vertical lockups with the
word set in Sora Bold (assets/branding/fonts/, OFL-1.1) and converted to paths with matplotlib's TextPath, so the
SVGs need no installed font; the mark is placed with a group, not a nested <svg> (QtSvg, SVG Tiny, skips those).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
BRANDING = REPO / "assets" / "branding"
PARAMS = BRANDING / "vortexcfd-logo-params.json"
SAVED_MARK = BRANDING / "vortexcfd-mark.svg"
FONT = BRANDING / "fonts" / "Sora-Bold.ttf"  # Sora[wght].ttf instantiated at wght 700 (fontTools)

SIZE = 512  # the mark's box
CENTRE = SIZE / 2
ARM_RADIUS = 214.0  # the centreline's outer radius before the tile's scale (read off the saved SVG)
SAMPLES = 89  # points along each side of an arm's outline
COLOURS = {"white": "#fafafa", "panel": "#27272a"}  # the theme's text and panel colours (Zinc & Teal, D-144)
ALT_COLOR = "#f59e0b"  # the second colour of "alt" arms
BORDER = "#3f3f46"  # the tile's border (the theme's border colour)
ACCENT = "#2dd4bf"  # "CFD" in the lockups (the theme's accent)
MONO = "#18181b"  # the one-colour mark (for light backgrounds)
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
WORD = (("Vortex", "#fafafa"), ("CFD", ACCENT))
RIGHT_MARGIN = 18  # after the word's last advance in the horizontal lockup (the saved lockup: 1874 units wide)


# -- the mark (numpy only) ------------------------------------------------------------------------------------------

def arm_outlines(p: dict) -> list[dict]:
    """Every arm: its outline polygon (2 x SAMPLES points: out along one side, back along the other), its two caps
    ((centre, radius) at the outer and the inner end) and its colour."""
    t = np.linspace(0.0, 1.0, SAMPLES)
    turn = p.get("dir", 1) * 360.0 * p["sweep"]
    radius = ARM_RADIUS * p["inner"] ** t
    r_in = ARM_RADIUS * p["inner"]
    width = p["wIn"] + (p["wOut"] - p["wIn"]) * (radius - r_in) / (ARM_RADIUS - r_in)
    arms = []
    for k in range(int(p["arms"])):
        theta = np.radians(p["rot"] + 360.0 * k / p["arms"] + turn * t)
        centre = np.c_[CENTRE + radius * np.cos(theta), CENTRE + radius * np.sin(theta)]
        tangent = np.gradient(centre, axis=0)
        tangent /= np.linalg.norm(tangent, axis=1)[:, None]
        normal = np.c_[-tangent[:, 1], tangent[:, 0]]
        side_a = centre + normal * width[:, None] / 2
        side_b = centre - normal * width[:, None] / 2
        colour = COLOURS.get(p.get("markColor", "white"), p.get("markColor"))
        if p.get("colorMode") == "alt" and k % 2:
            colour = ALT_COLOR
        arms.append({"outline": np.vstack([side_a, side_b[::-1]]),
                     "caps": ((centre[0], width[0] / 2), (centre[-1], width[-1] / 2)), "colour": colour})
    return arms


def _n(value: float) -> str:
    text = f"{value:.2f}"
    return "0.00" if text == "-0.00" else text


def arm_path(arm: dict) -> str:
    """An arm as SVG path data: the outline, then each cap as a circle of two arcs (the generator's form)."""
    pts = arm["outline"]
    d = "M" + " L".join(f"{_n(x)} {_n(y)}" for x, y in pts) + " Z"
    for (cx, cy), r in arm["caps"]:
        d += (f" M{_n(cx - r)} {_n(cy)} a{_n(r)} {_n(r)} 0 1 0 {_n(2 * r)} 0"
              f" a{_n(r)} {_n(r)} 0 1 0 {_n(-2 * r)} 0 Z")
    return d


def tile_svg(p: dict) -> str:
    """The tile and its border (empty without a tile)."""
    if not p.get("tile"):
        return ""
    r = p["radius"]
    out = f'<rect x="0" y="0" width="{SIZE}" height="{SIZE}" rx="{r:g}" fill="{COLOURS[p["tileColor"]]}"/>'
    if p.get("border"):
        out += (f'<rect x="2" y="2" width="{SIZE - 4}" height="{SIZE - 4}" rx="{r - 2:g}" fill="none" '
                f'stroke="{BORDER}" stroke-width="4"/>')
    return out


def mark_body(p: dict, colour: str | None = None) -> str:
    """The tile (when ``p`` has one) and the arms, scaled as the generator scales them; ``colour``: one colour."""
    scale = p.get("scale", 1.0) if p.get("tile") else 1.0
    arms = "".join(f'<path d="{arm_path(a)}" fill="{colour or a["colour"]}" fill-rule="nonzero"/>'
                   for a in arm_outlines(p))
    return (tile_svg(p) + f'<g transform="translate({CENTRE:g} {CENTRE:g}) scale({scale:g}) '
            f'translate({-CENTRE:g} {-CENTRE:g})">' + arms + "</g>")


def mark_svg(p: dict, tile: bool = True, colour: str | None = None) -> str:
    q = dict(p, tile=tile and p.get("tile", False))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" role="img" aria-label="VortexCFD">'
            + mark_body(q, colour) + "</svg>")


# -- comparison with the saved mark ---------------------------------------------------------------------------------

def _numbers(text: str) -> np.ndarray:
    return np.array([float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", text)])


def compare(saved: Path, p: dict) -> tuple[float, int]:
    """(the largest difference of any path coordinate, the paths compared) between the saved mark and the port; the
    path commands must be the same."""
    old = re.findall(r'<path d="([^"]*)"', saved.read_text())
    new = re.findall(r'<path d="([^"]*)"', mark_svg(p))
    if len(old) != len(new):
        raise SystemExit(f"{len(old)} paths saved, {len(new)} ported")
    worst = 0.0
    for a, b in zip(old, new):
        if re.findall(r"[A-Za-z]", a) != re.findall(r"[A-Za-z]", b):
            raise SystemExit("the path commands differ")
        na, nb = _numbers(a), _numbers(b)
        if na.shape != nb.shape:
            raise SystemExit("the path lengths differ")
        worst = max(worst, float(np.abs(na - nb).max()))
    return worst, len(old)


# -- the word as paths (matplotlib's TextPath and the font file) ---------------------------------------------------

def word_paths(font: Path, size: float, x0: float, baseline: float, track: float) -> tuple[str, float]:
    """The word "VortexCFD" as SVG paths (each part in its colour) set from ``x0`` on the baseline at ``size`` units
    with the advance and kerning of the font plus ``track`` units after each letter (CSS letter-spacing); returns
    (the paths, the right end of the last letter's advance)."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.ft2font import FT2Font, Kerning
    from matplotlib.path import Path as MPath
    from matplotlib.textpath import TextPath

    prop = FontProperties(fname=str(font))
    face = FT2Font(str(font))
    face.set_size(size, 72)  # size points at 72 dpi: size pixels
    out, x, previous = [], x0, None
    for part, colour in WORD:
        commands = []
        for ch in part:
            index = face.get_char_index(ord(ch))
            if previous is not None:
                x += face.get_kerning(previous, index, Kerning.UNFITTED) / 64.0
            path = TextPath((0, 0), ch, size=size, prop=prop)
            for verts, code in path.iter_segments(curves=True, simplify=False):
                xy = [(x + verts[i], baseline - verts[i + 1]) for i in range(0, len(verts), 2)]
                letter = {MPath.MOVETO: "M", MPath.LINETO: "L", MPath.CURVE3: "Q", MPath.CURVE4: "C"}.get(code)
                if code == MPath.CLOSEPOLY:
                    commands.append("Z")
                elif letter is not None:
                    commands.append(letter + " ".join(f"{_n(px)} {_n(py)}" for px, py in xy))
            glyph = face.load_char(ord(ch))
            x += glyph.linearHoriAdvance / 65536.0 + track
            previous = index
        out.append(f'<path fill="{colour}" d="{" ".join(commands)}"/>')
    return "".join(out), x


def lockup_h(p: dict, font: Path) -> str:
    """The horizontal lockup: the tiled mark, then the word (the saved lockup's size, place and tracking)."""
    words, right = word_paths(font, 230, 576, 338.8, p.get("track", -2))
    width = int(round(right + RIGHT_MARGIN))  # 1874: the saved lockup's width
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {SIZE}" role="img" '
            f'aria-label="VortexCFD"><g>' + mark_body(p) + "</g>" + words + "</svg>")


def lockup_v(p: dict, font: Path) -> str:
    """The vertical lockup: the tiled mark centred above the word."""
    size, track = 200, p.get("track", -2) * 200 / 230
    _probe, right = word_paths(font, size, 0, 0, track)
    width = int(round(max(right, SIZE) + 128))
    words, _r = word_paths(font, size, (width - right) / 2, SIZE + 64 + size * 0.75, track)
    height = int(round(SIZE + 64 + size * 1.0))
    left = (width - SIZE) / 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="VortexCFD"><g transform="translate({left:g} 0)">' + mark_body(p) + "</g>" + words + "</svg>")


# -- PNG and ICO -----------------------------------------------------------------------------------------------------

def render_png(svg: str, size: int, path: Path) -> None:
    """The SVG rendered at ``size`` x ``size`` pixels (QtSvg, antialiased, transparent around the tile)."""
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(svg.encode()))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    image.save(str(path), "PNG")


def write_ico(pngs: dict[int, Path], path: Path) -> None:
    from PIL import Image

    largest = Image.open(pngs[max(ICO_SIZES)])
    largest.save(path, format="ICO", sizes=[(s, s) for s in ICO_SIZES],
                 append_images=[Image.open(pngs[s]) for s in ICO_SIZES if s != max(ICO_SIZES)])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only compare the ported mark with the saved SVG")
    parser.add_argument("--out", type=Path, default=BRANDING)
    args = parser.parse_args()
    params = json.loads(PARAMS.read_text())
    worst, n = compare(SAVED_MARK, params)
    print(f"mark: {n} paths; largest coordinate difference from {SAVED_MARK.name}: {worst:.4f} units")
    if worst > 0.01:
        print("the ported mark does not match the saved one")
        return 1
    if args.check:
        return 0
    sys.path.insert(0, str(REPO / "src"))
    from vortexcfd.core.display_guard import apply_display_guard

    apply_display_guard()  # offscreen: no window opens
    from PySide6.QtGui import QGuiApplication

    _app = QGuiApplication.instance() or QGuiApplication([])
    out = args.out
    (out / "png").mkdir(parents=True, exist_ok=True)
    files = {
        "vortexcfd-mark.svg": mark_svg(params),
        "vortexcfd-mark-notile.svg": mark_svg(params, tile=False),
        "vortexcfd-mark-mono.svg": mark_svg(params, tile=False, colour=MONO),
        "vortexcfd-lockup-h-paths.svg": lockup_h(params, FONT),
        "vortexcfd-lockup-v.svg": lockup_v(params, FONT),
    }
    for name, text in files.items():
        if name == "vortexcfd-mark.svg" and (out / name).is_file() and out == BRANDING:
            continue  # the owner's saved mark stays as saved (the port matches it)
        (out / name).write_text(text + "\n")
        print(out / name)
    pngs = {}
    for size in PNG_SIZES:
        pngs[size] = out / "png" / f"vortexcfd-{size}.png"
        render_png(files["vortexcfd-mark.svg"], size, pngs[size])
    print(f"{out / 'png'}: {', '.join(str(s) for s in PNG_SIZES)} px")
    write_ico(pngs, out / "vortexcfd.ico")
    print(out / "vortexcfd.ico")
    if out == BRANDING:  # the app's package data and the manual's header (D-175)
        package = REPO / "src" / "vortexcfd" / "brand"
        for source, name in ((SAVED_MARK.read_text(), "mark.svg"), (files["vortexcfd-lockup-h-paths.svg"], "lockup-h.svg"),
                             (files["vortexcfd-lockup-v.svg"], "lockup-v.svg")):
            (package / name).write_text(source.rstrip("\n") + "\n")
            print(package / name)
        manual = REPO / "docs" / "manual" / "images" / "vortexcfd-lockup.svg"
        manual.write_text(files["vortexcfd-lockup-h-paths.svg"] + "\n")
        print(manual)
    return 0


if __name__ == "__main__":
    sys.exit(main())
