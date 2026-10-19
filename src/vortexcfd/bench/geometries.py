"""Benchmark geometries built by code (D-081): deterministic, regenerated on demand, never committed.

- sphere: diameter 1 m, binary STL in metres (the control case).
- wing: rectangular wing, NACA 0012, chord 1 m, span 3 m, trailing edge 0.25 % of the chord thick
  (flat), flat closed tips; STEP (millimetres) built with OCP.
- half_wing: the same section, span 1.5 m from the root at y = 0 (on a y_min symmetry plane) to the
  tip at y = 1.5 m (the benchmark's wing case since task 5.1b, D-092).
- ahmed: Ahmed-type body without stilts: length 1.044 m, width 0.389 m, height 0.288 m, the four front
  edges rounded with radius 0.1 m, a 25 degree rear slant 0.222 m long, sharp rear edges; STEP
  (millimetres) built with OCP.

Axes: x along the flow (nose or leading edge at x = 0), y spanwise, z up. The STEP header's time stamp
is replaced by a fixed one and the product is named after the file, so the files are byte-identical
from run to run.
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyvista as pv

# -- sphere ------------------------------------------------------------------------------------------
SPHERE_DIAMETER = 1.0  # m
SPHERE_RESOLUTION = (180, 90)  # theta, phi: chord error 0.5 (1 - cos(1 deg)) = 76 um

# -- wing (millimetres in the STEP file) -------------------------------------------------------------
WING_CHORD = 1000.0
WING_SPAN = 3000.0
HALF_WING_SPAN = 1500.0
WING_THICKNESS = 0.12  # NACA 0012
WING_TE_THICKNESS = 0.0025  # trailing edge thickness / chord
WING_POINTS = 201  # per side, cosine spacing

# -- Ahmed-type body (millimetres) -------------------------------------------------------------------
AHMED_LENGTH = 1044.0
AHMED_WIDTH = 389.0
AHMED_HEIGHT = 288.0
AHMED_FRONT_RADIUS = 100.0
AHMED_SLANT_DEG = 25.0
AHMED_SLANT_LENGTH = 222.0  # along the slant

FIXED_STAMP = "2026-01-01T00:00:00"


def naca_half_thickness(x: np.ndarray, thickness: float = WING_THICKNESS,
                        te_thickness: float = WING_TE_THICKNESS) -> np.ndarray:
    """Half-thickness / chord of the NACA 4-digit symmetric section at x / chord, with the open
    trailing edge of the standard coefficients (-0.1015) corrected linearly in x so that the total
    trailing-edge thickness is exactly ``te_thickness``."""
    x = np.asarray(x, dtype=float)
    yt = 5 * thickness * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1015 * x**4)
    yt_te = 5 * thickness * (0.2969 - 0.1260 - 0.3516 + 0.2843 - 0.1015)
    return yt + x * (te_thickness / 2 - yt_te)


def ahmed_slant_points() -> dict[str, float]:
    """x where the slant starts and z where it meets the rear face (millimetres)."""
    a = math.radians(AHMED_SLANT_DEG)
    return {"x_start": AHMED_LENGTH - AHMED_SLANT_LENGTH * math.cos(a),
            "z_rear": AHMED_HEIGHT - AHMED_SLANT_LENGTH * math.sin(a)}


def write_sphere(path: Path) -> Path:
    sphere = pv.Sphere(radius=SPHERE_DIAMETER / 2, center=(0.0, 0.0, 0.0),
                       theta_resolution=SPHERE_RESOLUTION[0], phi_resolution=SPHERE_RESOLUTION[1])
    sphere = sphere.triangulate().clean()
    sphere.save(str(path), binary=True)
    return path


def _wing_shape(span: float = WING_SPAN):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.collections import HArray1_gp_Pnt

    beta = np.linspace(0.0, math.pi, WING_POINTS)
    x = 0.5 * (1 + np.cos(beta))  # 1 -> 0 (cosine spacing, dense at both edges)
    half = naca_half_thickness(x)
    # Upper surface from the trailing edge to the leading edge, then the lower surface back.
    xs = np.concatenate([x, x[-2::-1]]) * WING_CHORD
    zs = np.concatenate([half, -half[-2::-1]]) * WING_CHORD
    zs[len(x) - 1] = 0.0  # the leading edge point
    pts = HArray1_gp_Pnt(1, len(xs))
    for i, (px, pz) in enumerate(zip(xs, zs), start=1):
        pts.SetValue(i, gp_Pnt(float(px), 0.0, float(pz)))
    interp = GeomAPI_Interpolate(pts, False, 1e-9)
    interp.Perform()
    curve = interp.Curve()
    te_top, te_bottom = gp_Pnt(float(xs[0]), 0.0, float(zs[0])), gp_Pnt(float(xs[-1]), 0.0, float(zs[-1]))
    wire = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(curve).Edge(),
                                   BRepBuilderAPI_MakeEdge(te_bottom, te_top).Edge()).Wire()
    face = BRepBuilderAPI_MakeFace(wire, True).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0.0, span, 0.0)).Shape()


def _ahmed_shape():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt, gp_Vec

    s = ahmed_slant_points()
    y0 = -AHMED_WIDTH / 2
    profile = [(0.0, 0.0), (AHMED_LENGTH, 0.0), (AHMED_LENGTH, s["z_rear"]), (s["x_start"], AHMED_HEIGHT),
               (0.0, AHMED_HEIGHT)]
    poly = BRepBuilderAPI_MakePolygon()
    for px, pz in profile:
        poly.Add(gp_Pnt(px, y0, pz))
    poly.Close()
    face = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
    body = BRepPrimAPI_MakePrism(face, gp_Vec(0.0, AHMED_WIDTH, 0.0)).Shape()
    fillet = BRepFilletAPI_MakeFillet(body)
    explorer = TopExp_Explorer(body, TopAbs_EDGE)
    seen = []
    while explorer.More():
        edge = TopoDS.Edge(explorer.Current())
        xs = []
        vx = TopExp_Explorer(edge, TopAbs_VERTEX)
        while vx.More():
            xs.append(BRep_Tool.Pnt_s(TopoDS.Vertex(vx.Current())).X())
            vx.Next()
        if xs and all(abs(v) < 1e-9 for v in xs) and not any(edge.IsSame(e) for e in seen):
            seen.append(edge)  # the four edges of the front face (x = 0)
            fillet.Add(AHMED_FRONT_RADIUS, edge)
        explorer.Next()
    if len(seen) != 4:
        raise RuntimeError(f"expected 4 front edges, found {len(seen)}")
    fillet.Build()
    if not fillet.IsDone():
        raise RuntimeError("the front fillet failed")
    return fillet.Shape()


def _write_step(shape, path: Path) -> Path:
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise RuntimeError(f"could not write {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"FILE_NAME\('([^']*)','[^']*'", lambda m: f"FILE_NAME('{path.name}','{FIXED_STAMP}'", text, count=1)
    # The writer numbers its products per process ("... translator 8.0 2"): name it after the file.
    text = re.sub(r"Open CASCADE STEP translator [0-9.]+ [0-9]+", path.stem, text)
    path.write_text(text, encoding="utf-8")
    return path


def write_wing(path: Path) -> Path:
    return _write_step(_wing_shape(), path)


def write_half_wing(path: Path) -> Path:
    return _write_step(_wing_shape(HALF_WING_SPAN), path)


def write_ahmed(path: Path) -> Path:
    return _write_step(_ahmed_shape(), path)


@dataclass(frozen=True)
class GeometrySpec:
    file_name: str
    writer: object  # callable(Path) -> Path


GEOMETRIES: dict[str, GeometrySpec] = {
    "sphere": GeometrySpec("sphere.stl", write_sphere),
    "wing": GeometrySpec("wing.step", write_wing),
    "half_wing": GeometrySpec("half_wing.step", write_half_wing),
    "ahmed": GeometrySpec("ahmed.step", write_ahmed),
}


def sphere_reference(name: str) -> tuple[tuple[float, float, float], float] | None:
    """(centre, radius) in metres of a geometry that is an exact sphere, else None."""
    return ((0.0, 0.0, 0.0), SPHERE_DIAMETER / 2) if name == "sphere" else None


def ensure_geometry(name: str, folder: Path, force: bool = False) -> Path:
    """The geometry file of ``name`` in ``folder``, generated when missing (or when ``force``)."""
    spec = GEOMETRIES[name]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / spec.file_name
    if force or not path.is_file():
        spec.writer(path)
    return path
