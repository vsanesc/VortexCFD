"""Cp on wall sections: cut the part walls with planes and order the cut by x/c (Qt-free; pyvista,
so it lives in gui/ like gui/meshing.py). (D-062)

A section is the intersection of the wall patches with the plane ``axis = position`` (axis y, the
spanwise default, or z). Each cut segment carries its wall face's cell values; the point used is the
segment midpoint. The chord is taken along x on the section itself: c = x_max - x_min of the cut
points, x/c = (x - x_min) / c. Cp = p / (0.5 U_ref^2) (kinematic p, p_ref = 0, foam/results.py).

Upper and lower surfaces are told apart by the z component of the body's outward normal (OpenFOAM's
wall face normals point out of the fluid, into the body, so the outward normal is their opposite):
upper n_z > 0, lower n_z < 0, each ordered by x. When the normals do not separate them (a horizontal
plane, or a cut where most points have |n_z| < 0.1) the section is one line ordered by x.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.foam.results import pressure_coefficient

AXES = {"y": 1, "z": 2}  # section plane normal; x has no chord along x
# Fewer than this share of points with |n_z| >= NORMAL_SPLIT: no upper/lower split.
NORMAL_SPLIT = 0.1
SPLIT_SHARE = 0.5


@dataclass
class SectionLine:
    """One ordered line of a section: "upper", "lower" or "all"."""

    surface: str
    points: np.ndarray  # (n, 3) segment midpoints, ordered by x
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


def _outward_nz(surface: pv.PolyData) -> np.ndarray:
    normals = surface.compute_normals(cell_normals=True, point_normals=False, auto_orient_normals=False,
                                      consistent_normals=False, split_vertices=False)
    return -np.asarray(normals.cell_data["Normals"])[:, 2]  # OpenFOAM wall normals point into the body


def cut_section(patches: dict[str, pv.PolyData], axis: str, position: float, u_ref: float) -> Section | None:
    """The section of the walls at ``axis = position`` (None when the plane misses every wall).
    The patches carry the cell field ``p`` (kinematic)."""
    if axis not in AXES:
        raise ValueError(f"section axis must be one of {sorted(AXES)}")
    normal = [0.0, 0.0, 0.0]
    normal[AXES[axis]] = 1.0
    mids, cps, nzs = [], [], []
    for surface in patches.values():
        if "p" not in surface.cell_data:
            continue
        work = surface.copy()
        work.cell_data["_nz"] = _outward_nz(work)
        origin = list(work.center)
        origin[AXES[axis]] = position
        cut = work.slice(normal=normal, origin=origin)
        if cut.n_cells == 0:
            continue
        lines = cut.cell_centers().points  # midpoints of the cut segments
        mids.append(np.asarray(lines))
        cps.append(pressure_coefficient(cut.cell_data["p"], u_ref))
        nzs.append(np.asarray(cut.cell_data["_nz"]))
    if not mids:
        return None
    pts, cp, nz = np.concatenate(mids), np.concatenate(cps), np.concatenate(nzs)
    x_min, x_max = float(pts[:, 0].min()), float(pts[:, 0].max())
    chord = x_max - x_min
    section = Section(axis, float(position), chord, x_min)
    x_c = (pts[:, 0] - x_min) / chord if chord > 0 else np.zeros(len(pts))
    separable = np.mean(np.abs(nz) >= NORMAL_SPLIT) >= SPLIT_SHARE and (nz > 0).sum() >= 2 and (nz < 0).sum() >= 2
    groups = [("upper", nz > 0), ("lower", nz <= 0)] if separable else [("all", np.ones(len(pts), bool))]
    for name, mask in groups:
        order = np.argsort(pts[mask, 0], kind="stable")
        section.lines.append(SectionLine(name, pts[mask][order], x_c[mask][order], cp[mask][order]))
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
