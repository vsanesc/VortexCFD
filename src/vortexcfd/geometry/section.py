"""2D sections (D-121; numpy and pyvista, no Qt): airfoil coordinate files, closed section curves in the x-z
plane and the thin slab (the section extruded along y) that the 2D mode meshes.

Airfoil coordinate files (the two formats of the UIUC airfoil database):

- Selig: a name line, then one "x y" pair per line from the trailing edge over the upper surface to the
  leading edge and back along the lower surface to the trailing edge.
- Lednicer: a name line, a line with the point counts of the upper and lower surfaces ("61. 61."), then
  the upper surface from the leading edge to the trailing edge and the lower surface the same way, the
  blocks usually separated by blank lines.

The file's y is the section's z (the 2D mode's plane is x-z; the span is y). ``scale`` multiplies the
coordinates (a file in chord units with scale c gives chord c). The trailing edge closure: "blunt" closes
an open trailing edge with a straight base segment (a sharp one is kept); "sharp" moves the two surfaces
by a thickness that grows linearly from 0 at the leading edge, so they meet at the mid point of the
trailing edge.
"""

import math
import re
from pathlib import Path

import numpy as np
import pyvista as pv

AIRFOIL_FORMATS = ("selig", "lednicer")
TE_CLOSURES = ("blunt", "sharp")
MIN_POINTS = 5  # per surface
_NUM = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eEdD][-+]?\d+)?$")


class AirfoilFormatError(ValueError):
    """The file is not an airfoil coordinate file this module reads; the message says why."""


def _pairs(lines: list[str], start: int, path_name: str) -> list[tuple[int, tuple[float, float] | None]]:
    """(line number, (x, y) or None for a blank line) of the lines from ``start``."""
    out = []
    for n, line in enumerate(lines[start:], start=start + 1):
        text = line.strip()
        if not text:
            out.append((n, None))
            continue
        fields = text.replace(",", " ").split()
        if len(fields) < 2 or not all(_NUM.match(f) for f in fields[:2]):
            raise AirfoilFormatError(f"{path_name}, line {n}: expected two numbers, found {text[:40]!r}")
        out.append((n, (float(fields[0].replace("d", "e").replace("D", "e")),
                        float(fields[1].replace("d", "e").replace("D", "e")))))
    return out


def read_airfoil(path: Path, fmt: str | None = None) -> tuple[str, str, np.ndarray, np.ndarray]:
    """(name, format, upper, lower) of an airfoil coordinate file: ``upper`` and ``lower`` are (n, 2) arrays
    of (x, y) from the leading edge to the trailing edge. ``fmt`` None detects the format (Lednicer when the
    first data line holds two counts above 1).

    Raises:
        AirfoilFormatError: not a readable Selig or Lednicer file (the message names the line).
    """
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise AirfoilFormatError(f"Cannot read {path.name}: {exc}") from exc
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 2:
        raise AirfoilFormatError(f"{path.name}: too few lines for an airfoil file")
    name = lines[0].strip() or path.stem
    first = next((i for i in range(1, len(lines)) if lines[i].strip()), None)
    if first is None:
        raise AirfoilFormatError(f"{path.name}: no coordinates")
    rows = _pairs(lines, first, path.name)
    head = rows[0][1]
    detected = "lednicer" if head is not None and head[0] > 1.0 and head[1] > 1.0 else "selig"
    fmt = fmt or detected
    if fmt not in AIRFOIL_FORMATS:
        raise AirfoilFormatError(f"unknown airfoil format {fmt!r}")
    if fmt == "lednicer":
        if head is None or head[0] != int(head[0]) or head[1] != int(head[1]):
            raise AirfoilFormatError(f"{path.name}, line {first + 1}: a Lednicer file starts with the two point counts")
        n_up, n_lo = int(head[0]), int(head[1])
        points = [p for _n, p in rows[1:] if p is not None]
        if len(points) != n_up + n_lo:
            raise AirfoilFormatError(f"{path.name}: the header announces {n_up} + {n_lo} points, the file has {len(points)}")
        upper, lower = np.array(points[:n_up]), np.array(points[n_up:])
    else:
        pts = np.array([p for _n, p in rows if p is not None])
        if len(pts) < 2 * MIN_POINTS - 1:
            raise AirfoilFormatError(f"{path.name}: {len(pts)} points, too few for an airfoil")
        le = int(np.argmin(pts[:, 0]))
        upper, lower = pts[:le + 1][::-1], pts[le:]
    for label, surf in (("upper", upper), ("lower", lower)):
        if len(surf) < MIN_POINTS:
            raise AirfoilFormatError(f"{path.name}: the {label} surface has {len(surf)} points (at least {MIN_POINTS})")
    if np.linalg.norm(upper[0] - lower[0]) > 1e-6 * max(np.ptp(upper[:, 0]), 1e-12):
        raise AirfoilFormatError(f"{path.name}: the upper and lower surfaces do not start at the same leading-edge point")
    chord = max(upper[:, 0].max(), lower[:, 0].max()) - upper[0, 0]
    if chord <= 0:
        raise AirfoilFormatError(f"{path.name}: the trailing edge is not behind the leading edge")
    if np.any(np.diff(upper[:, 0]) < -1e-9 * chord) or np.any(np.diff(lower[:, 0]) < -1e-9 * chord):
        raise AirfoilFormatError(f"{path.name}: x does not increase from the leading edge to the trailing edge "
                                 f"(read as {fmt}; try the other format)")
    return name, fmt, upper, lower


def section_loop(upper: np.ndarray, lower: np.ndarray, scale: float = 1.0, closure: str = "blunt") -> np.ndarray:
    """The closed section curve (n, 2) in (x, z), without a repeated point, counter-clockwise seen from -y
    (trailing edge, upper surface, leading edge, lower surface), scaled by ``scale``, its trailing edge
    closed as ``closure`` says (module docstring)."""
    if closure not in TE_CLOSURES:
        raise ValueError(f"trailing edge closure must be one of {TE_CLOSURES}")
    if scale <= 0:
        raise ValueError("the scale must be larger than zero")
    up, lo = np.array(upper, dtype=float), np.array(lower, dtype=float)
    if closure == "sharp":
        le = up[0].copy()
        mid = 0.5 * (up[-1, 1] + lo[-1, 1])
        for surf in (up, lo):
            span = surf[-1, 0] - le[0]
            frac = (surf[:, 0] - le[0]) / span if span > 0 else np.zeros(len(surf))
            surf[:, 1] -= frac * (surf[-1, 1] - mid)
        lo[-1] = up[-1]
    upper_te_to_le = up[::-1]
    lower_le_to_te = lo[1:]
    loop = np.vstack([upper_te_to_le, lower_le_to_te])
    if np.linalg.norm(loop[0] - loop[-1]) <= 1e-12 * max(np.ptp(loop[:, 0]), 1e-12):
        loop = loop[:-1]  # a sharp trailing edge: one point
    return loop * scale


def loop_area(loop: np.ndarray) -> float:
    """The signed area of a closed (x, z) curve (shoelace)."""
    x, z = loop[:, 0], loop[:, 1]
    return 0.5 * float((x * np.roll(z, -1) - np.roll(x, -1) * z).sum())


def slab(loops: list[np.ndarray], y0: float, y1: float) -> pv.PolyData:
    """The closed triangulated surface of the sections ``loops`` ((n, 2) arrays in x-z) extruded from y = y0
    to y = y1, its normals outwards."""
    if y1 <= y0:
        raise ValueError("the slab needs y1 > y0")
    parts = []
    for loop in loops:
        loop = np.asarray(loop, dtype=float)
        n = len(loop)
        if n < 3:
            continue
        p0 = np.column_stack([loop[:, 0], np.full(n, y0), loop[:, 1]])
        p1 = np.column_stack([loop[:, 0], np.full(n, y1), loop[:, 1]])
        faces = []
        for i in range(n):
            j = (i + 1) % n
            faces += [3, i, j, n + j, 3, i, n + j, n + i]
        parts.append(pv.PolyData(np.vstack([p0, p1]), np.array(faces)))
        for cap in (p0, p1):
            parts.append(pv.PolyData(cap, np.hstack([[n], np.arange(n)])).triangulate())
    if not parts:
        raise ValueError("no section curve")
    merged = parts[0]
    for p in parts[1:]:
        merged = merged + p
    surface = merged.clean(tolerance=0.0).triangulate()
    return surface.compute_normals(auto_orient_normals=True, consistent_normals=True, cell_normals=True,
                                   point_normals=False)


def section_loops(mesh: pv.PolyData, y: float | None = None) -> list[np.ndarray]:
    """The closed section curves ((n, 2) arrays in x-z) of a part extruded along y, cut at ``y`` (None: the
    middle of its y range): the part's 2D section. Open pieces (the cut missed a closed curve) are left out.

    Raises:
        ValueError: the cut gives no closed curve (the part is not a closed body crossing that plane).
    """
    b = mesh.bounds
    y = (b[2] + b[3]) / 2 if y is None else y
    cut = mesh.slice(normal=(0.0, 1.0, 0.0), origin=(0.0, y, 0.0))
    if cut.n_points == 0:
        raise ValueError("the part does not cross the plane y = {:.4g} m".format(y))
    stripped = cut.strip(join=True, max_length=10 ** 7)
    loops = []
    lines = stripped.lines
    i = 0
    pts = np.asarray(stripped.points)
    tol = 1e-9 * max(b[1] - b[0], b[5] - b[4], 1e-12)
    while i < len(lines):
        k = int(lines[i])
        ids = np.asarray(lines[i + 1:i + 1 + k])
        i += k + 1
        if k >= 4 and np.linalg.norm(pts[ids[0]] - pts[ids[-1]]) <= tol:
            loops.append(pts[ids[:-1]][:, [0, 2]])
    if not loops:
        raise ValueError("the cut at y = {:.4g} m gives no closed section curve".format(y))
    return loops


def airfoil_slab(path: Path, scale: float = 1.0, closure: str = "blunt", fmt: str | None = None,
                 span: float | None = None) -> tuple[pv.PolyData, str, str, np.ndarray]:
    """(the slab of an airfoil file's section, its name, the format read, the section curve). The slab spans
    y from -span / 2 to span / 2 (``span`` None: the chord); the 2D mode re-extrudes the section to the mesh's
    own span (D-121)."""
    name, fmt, upper, lower = read_airfoil(path, fmt)
    loop = section_loop(upper, lower, scale, closure)
    chord = float(np.ptp(loop[:, 0]))
    half = (span if span is not None else chord) / 2
    if not math.isfinite(half) or half <= 0:
        raise AirfoilFormatError(f"{Path(path).name}: zero chord")
    return slab([loop], -half, half), name, fmt, loop
