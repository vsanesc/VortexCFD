"""Tests for the geometry layer: surface loader and checks (small meshes generated in tmp)."""

import logging
import os
import time
from pathlib import Path

import numpy as np
import pyvista as pv
import pytest

from vortexcfd.geometry.checks import check_surface
from vortexcfd.geometry.loader import SurfaceLoadError, UNIT_TO_METRE, clear_cache, load_surface

log = logging.getLogger(__name__)


def make_sphere(n: int = 24) -> pv.PolyData:
    return pv.Sphere(radius=1.0, theta_resolution=n, phi_resolution=n).clean()


def with_faces(mesh: pv.PolyData, faces: np.ndarray, extra_points: np.ndarray | None = None) -> pv.PolyData:
    points = mesh.points if extra_points is None else np.vstack([mesh.points, extra_points])
    return pv.PolyData(points, faces=faces.ravel())


def tri_array(mesh: pv.PolyData) -> np.ndarray:
    return np.asarray(mesh.faces).reshape(-1, 4)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


# -- loader -----------------------------------------------------------------------


@pytest.mark.parametrize("ext, kwargs", [(".stl", {}), (".stl", {"binary": False}), (".ply", {}), (".obj", {})])
def test_loader_reads_each_format(tmp_path: Path, ext: str, kwargs: dict) -> None:
    sphere = make_sphere()
    path = tmp_path / f"s{ext}"
    sphere.save(str(path), **kwargs)
    mesh = load_surface(path, "m")
    assert mesh.is_all_triangles
    assert mesh.n_cells == sphere.n_cells
    assert mesh.n_points == sphere.n_points  # coincident points merged
    assert np.allclose(mesh.bounds, sphere.bounds, atol=1e-4)


@pytest.mark.parametrize("units", list(UNIT_TO_METRE))
def test_loader_scales_to_metres(tmp_path: Path, units: str) -> None:
    path = tmp_path / "s.stl"
    sphere = make_sphere()
    sphere.save(str(path))
    mesh = load_surface(path, units)
    expected = (sphere.bounds[1] - sphere.bounds[0]) * UNIT_TO_METRE[units]
    assert mesh.bounds[1] - mesh.bounds[0] == pytest.approx(expected, rel=1e-4)


def test_loader_errors(tmp_path: Path) -> None:
    step = tmp_path / "part.step"
    step.write_text("ISO-10303-21;")
    with pytest.raises(SurfaceLoadError, match=r"Unsupported file type '\.step'"):
        load_surface(step, "m")
    with pytest.raises(FileNotFoundError, match="not found"):
        load_surface(tmp_path / "missing.stl", "m")
    bad = tmp_path / "bad.stl"
    bad.write_text("this is not an stl")
    with pytest.warns(UserWarning, match="vtkSTLReader"), pytest.raises(SurfaceLoadError):
        load_surface(bad, "m")  # VTK reports the failed read as a UserWarning
    ok = tmp_path / "ok.stl"
    make_sphere().save(str(ok))
    with pytest.raises(SurfaceLoadError, match="Unknown units"):
        load_surface(ok, "km")


def test_loader_cache_keyed_by_path_mtime_units(tmp_path: Path) -> None:
    path = tmp_path / "s.stl"
    make_sphere().save(str(path))
    a = load_surface(path, "m")
    assert load_surface(path, "m") is a
    assert load_surface(path, "mm") is not a
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    assert load_surface(path, "m") is not a  # mtime changed


def test_load_timing_one_million_triangles(tmp_path: Path) -> None:
    sphere = pv.Sphere(theta_resolution=700, phi_resolution=700)
    path = tmp_path / "big.stl"
    sphere.save(str(path))
    t0 = time.perf_counter()
    mesh = load_surface(path, "m")
    seconds = time.perf_counter() - t0
    msg = f"load_surface: {mesh.n_cells} triangles in {seconds:.2f} s"
    log.info(msg)
    print(msg)  # a log, not an assertion
    assert mesh.n_cells > 900_000


# -- checks ---------------------------------------------------------------------------


def test_closed_sphere_is_watertight() -> None:
    r = check_surface(make_sphere())
    assert r.watertight
    assert (r.open_edges, r.non_manifold_edges, r.degenerate_triangles, r.duplicate_faces) == (0, 0, 0, 0)
    assert r.inconsistent_orientation == 0
    assert r.n_triangles > 0 and r.n_points > 0
    assert r.size == pytest.approx((2.0, 2.0, 2.0), rel=1e-2)
    assert "watertight: yes" in r.summary()


def test_open_box_has_boundary_edges() -> None:
    box = pv.Box(level=0).triangulate().clean()
    assert check_surface(box).watertight
    faces = tri_array(box)[:-1]  # drop one triangle: opens a hole
    r = check_surface(with_faces(box, faces))
    assert not r.watertight and r.open_edges == 3 and r.non_manifold_edges == 0
    assert "3 open edges" in r.summary()


def test_non_manifold_edge() -> None:
    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]], dtype=float)
    faces = np.array([[3, 0, 1, 2], [3, 0, 1, 3], [3, 0, 1, 4]])
    r = check_surface(pv.PolyData(points, faces=faces.ravel()))
    assert r.non_manifold_edges == 1 and not r.watertight


def test_flipped_normals_are_detected() -> None:
    sphere = make_sphere()
    faces = tri_array(sphere).copy()
    flipped = np.arange(0, 40, 4)  # 10 scattered triangles
    faces[flipped, 1], faces[flipped, 2] = faces[flipped, 2].copy(), faces[flipped, 1].copy()
    r = check_surface(with_faces(sphere, faces))
    assert r.inconsistent_orientation == len(flipped)
    assert r.watertight  # topology is still closed


def test_degenerate_triangle() -> None:
    sphere = make_sphere()
    extra = np.array([[0.0, 0, 0], [0.1, 0, 0], [0.2, 0, 0]])  # collinear: zero area
    n = sphere.n_points
    faces = np.vstack([tri_array(sphere), [[3, n, n + 1, n + 2]]])
    r = check_surface(with_faces(sphere, faces, extra))
    assert r.degenerate_triangles == 1


def test_duplicate_faces() -> None:
    sphere = make_sphere()
    faces = np.vstack([tri_array(sphere), tri_array(sphere)[:1]])
    r = check_surface(with_faces(sphere, faces))
    assert r.duplicate_faces == 1
