"""Cp on wall sections: cut the part walls with planes and order the cut along the wall (Qt-free;
pyvista, so it cannot live in foam/). (D-062)

A section is the intersection of the wall patches with the plane ``axis = position`` (axis y, the
spanwise default, or z). Each cut segment carries its wall face's cell values; the point used is the
segment midpoint. The chord is taken along x on the section itself: c = x_max - x_min of the cut
points, x/c = (x - x_min) / c. Cp = p / (0.5 U_ref^2) (kinematic p, p_ref = 0, foam/results.py).

Ordering: the cut segments of each patch are chained by their shared end points into polylines
(a closed loop around a body, or an open chain where the body crosses a boundary of the domain);
the points follow the chain, so consecutive points are neighbours on the wall. Each chain is split
at its min-x and max-x points into two branches, both running from the min-x to the max-x point.
The two branches are labelled by the side of the in-plane normal: the in-plane axis normal to x
(z for a y section, y for a z section); the branch whose body outward normal (OpenFOAM's wall face
normals point into the body, so their opposite) has the larger mean component along that axis is
"upper" / "+y side", the other "lower" / "-y side". A second chain in the same section (another part)
gets " 2" appended, and so on.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.foam.results import pressure_coefficient

AXES = {"y": 1, "z": 2}  # section plane normal; x has no chord along x
# In-plane axis normal to x for each section axis, and the names of its two sides (positive first).
SIDES = {"y": (2, ("upper", "lower")), "z": (1, ("+y side", "-y side"))}
# Names drawn dashed (the negative side).
NEGATIVE_SIDES = tuple(names[1] for _axis, names in SIDES.values())


@dataclass
class SectionLine:
    """One ordered branch of a section (SIDES names, or "all" for a chain that cannot be split)."""

    surface: str
    points: np.ndarray  # (n, 3) segment midpoints, in order along the wall
    x_c: np.ndarray
    cp: np.ndarray


@dataclass
class Section:
    axis: str  # "y" or "z"
    position: float  # m
    chord: float  # m, along x on the section
    x_min: float
    lines: list[SectionLine] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.axis} = {self.position:.4g} m"


def stations(lo: float, hi: float, n: int) -> list[float]:
    """``n`` evenly spaced positions strictly inside [lo, hi] (n = 1: the middle): the walls'
    extremes would cut nothing or a point."""
    if n < 1:
        raise ValueError("at least one station")
    step = (hi - lo) / (n + 1)
    return [lo + step * (i + 1) for i in range(n)]


def _outward_normals(surface: pv.PolyData) -> np.ndarray:
    normals = surface.compute_normals(cell_normals=True, point_normals=False, auto_orient_normals=False,
                                      consistent_normals=False, split_vertices=False)
    return -np.asarray(normals.cell_data["Normals"])  # OpenFOAM wall normals point into the body


def chains(segments: np.ndarray) -> list[tuple[list[int], bool]]:
    """Chain line segments (n, 2) of point ids by their shared points: [(segment indices in order,
    closed)]. Open chains start at an end point (a point used by one segment)."""
    by_point: dict[int, list[int]] = {}
    for i, (a, b) in enumerate(segments):
        by_point.setdefault(int(a), []).append(i)
        by_point.setdefault(int(b), []).append(i)
    used = np.zeros(len(segments), bool)
    ends = [(segs[0], p) for p, segs in by_point.items() if len(segs) == 1]
    candidates = ends + [(i, int(segments[i][0])) for i in range(len(segments))]
    out = []
    for first, start in candidates:
        if used[first]:
            continue
        a, b = (int(x) for x in segments[first])
        point = b if a == start else a  # walk away from the start point
        order, seg = [], first
        while True:
            used[seg] = True
            order.append(seg)
            nxt = [s for s in by_point[point] if not used[s]]
            if not nxt:
                break
            seg = nxt[0]
            a, b = (int(x) for x in segments[seg])
            point = b if a == point else a
        out.append((order, point == start and len(order) > 2))
    return out


def split_branches(points: np.ndarray, closed: bool) -> list[np.ndarray]:
    """Index arrays of the branches of one chain between its min-x and max-x points, each running
    from the min-x to the max-x point (both ends included in both branches)."""
    n = len(points)
    i_min, i_max = int(np.argmin(points[:, 0])), int(np.argmax(points[:, 0]))
    if closed:
        rotated = np.roll(np.arange(n), -i_min)
        j = int(np.where(rotated == i_max)[0][0])
        one = rotated[: j + 1]
        two = np.concatenate([rotated[j:], rotated[:1]])[::-1]
        return [b for b in (one, two) if len(b) >= 2]
    lo, hi = sorted((i_min, i_max))
    pieces = [np.arange(0, lo + 1), np.arange(lo, hi + 1), np.arange(hi, n)]
    out = []
    for piece in pieces:
        if len(piece) < 2:
            continue
        if points[piece[0], 0] > points[piece[-1], 0]:
            piece = piece[::-1]
        out.append(piece)
    return out


def cut_section(patches: dict[str, pv.PolyData], axis: str, position: float, u_ref: float) -> Section | None:
    """The section of the walls at ``axis = position`` (None when the plane misses every wall).
    The patches carry the cell field ``p`` (kinematic)."""
    if axis not in AXES:
        raise ValueError(f"section axis must be one of {sorted(AXES)}")
    normal = [0.0, 0.0, 0.0]
    normal[AXES[axis]] = 1.0
    side_axis, side_names = SIDES[axis]
    found = []  # (midpoints, cp, side normal component) per chain
    for surface in patches.values():
        if "p" not in surface.cell_data:
            continue
        work = surface.copy()
        work.cell_data["_n_side"] = _outward_normals(work)[:, side_axis]
        origin = list(work.center)
        origin[AXES[axis]] = position
        cut = work.slice(normal=normal, origin=origin)
        if cut.n_cells == 0:
            continue
        cut = cut.clean(tolerance=1e-9, absolute=False)  # merge coincident end points
        lines = np.asarray(cut.lines).reshape(-1, 3)
        if lines.size == 0 or np.any(lines[:, 0] != 2):
            continue
        segments = lines[:, 1:]
        pts = np.asarray(cut.points)
        mids = 0.5 * (pts[segments[:, 0]] + pts[segments[:, 1]])
        cp = pressure_coefficient(np.asarray(cut.cell_data["p"]), u_ref)
        side = np.asarray(cut.cell_data["_n_side"])
        for order, closed in chains(segments):
            found.append((mids[order], cp[order], side[order], closed))
    if not found:
        return None
    all_pts = np.concatenate([f[0] for f in found])
    x_min, x_max = float(all_pts[:, 0].min()), float(all_pts[:, 0].max())
    chord = x_max - x_min
    section = Section(axis, float(position), chord, x_min)
    for k, (pts, cp, side, closed) in enumerate(found):
        suffix = "" if k == 0 else f" {k + 1}"
        branches = split_branches(pts, closed) if len(pts) >= 3 else []
        if len(branches) == 2:
            means = [float(np.mean(side[b])) for b in branches]
            first_positive = means[0] >= means[1]
            names = side_names if first_positive else side_names[::-1]
            labelled = sorted(zip(names, branches), key=lambda nb: side_names.index(nb[0]))
        else:
            labelled = [("all", b) for b in branches] or [("all", np.arange(len(pts)))]
        for name, idx in labelled:
            x_c = (pts[idx, 0] - x_min) / chord if chord > 0 else np.zeros(len(idx))
            section.lines.append(SectionLine(name + suffix, pts[idx], x_c, cp[idx]))
    return section


def export_csv(sections: list[Section], path: Path) -> int:
    """Write every section line point as one CSV row; returns the number of rows."""
    rows = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["section", "axis", "position_m", "chord_m", "surface", "x_m", "y_m", "z_m", "x_c", "Cp"])
        for i, s in enumerate(sections, start=1):
            for line in s.lines:
                for (x, y, z), xc, cp in zip(line.points, line.x_c, line.cp):
                    writer.writerow([i, s.axis, f"{s.position:.6g}", f"{s.chord:.6g}", line.surface,
                                     f"{x:.6g}", f"{y:.6g}", f"{z:.6g}", f"{xc:.6g}", f"{cp:.6g}"])
                    rows += 1
    return rows
