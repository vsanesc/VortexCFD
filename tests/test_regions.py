"""Multi-solid STL, surface regions, the angle split and self-intersection checks (Tasks 3.1, 3.5)."""

import json
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

from tests.geometry_corpus import box_faces, two_spheres, write_multi_solid
from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Part, SurfaceRegion
from vortexcfd.core.project_io import load_simulation
from vortexcfd.geometry import checks, regions
from vortexcfd.geometry.checks import check_surface
from vortexcfd.geometry.intersections import intersecting_triangles
from vortexcfd.geometry.loader import SOLID_ARRAY, clear_cache, load_surface, stl_solid_names


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def test_multi_solid_ascii_stl_names_and_labels(tmp_path: Path) -> None:
    faces = box_faces()
    path = write_multi_solid(tmp_path / "box.stl", [(n, m) for n, m in faces[:5]] + [("", faces[5][1])])
    assert stl_solid_names(path) == ["xmin", "xmax", "ymin", "ymax", "zmin", "solid_6"]
    mesh = load_surface(path, "mm")
    labels = np.asarray(mesh.cell_data[SOLID_ARRAY])
    assert np.bincount(labels).tolist() == [m.n_cells for _, m in faces]
    assert check_surface(mesh).watertight  # the solids share their edge points


def test_repeated_solid_names_get_a_suffix(tmp_path: Path) -> None:
    sq = pv.Plane(i_resolution=1, j_resolution=1)
    path = write_multi_solid(tmp_path / "s.stl", [("wall", sq), ("wall", sq.translate((0, 0, 1)))])
    assert stl_solid_names(path) == ["wall", "wall_2"]


def test_binary_and_single_solid_stl(tmp_path: Path) -> None:
    sphere = pv.Sphere()
    sphere.save(str(tmp_path / "b.stl"))  # binary
    assert stl_solid_names(tmp_path / "b.stl") == []
    assert set(np.asarray(load_surface(tmp_path / "b.stl", "m").cell_data[SOLID_ARRAY])) == {0}
    sphere.save(str(tmp_path / "a.stl"), binary=False)
    assert len(stl_solid_names(tmp_path / "a.stl")) == 1


def test_v7_project_migrates_without_regions() -> None:
    path = Path(__file__).parent / "data" / "project_v7.json"
    assert json.loads(path.read_text())["schema_version"] == 7
    sim = load_simulation(path)
    assert sim.schema_version == CURRENT_SCHEMA_VERSION == 8
    ball, fin = sim.geometry.parts
    assert (ball.units, ball.surface_level_max, ball.regions, ball.region_ids, ball.cad) == ("mm", 4, [], None, None)
    assert ball.patch_names() == ["Ball"] and fin.patch_names() == ["Fin"]
    assert sim.studies.mesh.current_as == "medium" and sim.studies.polar.values == [0.0, 4.0]


def test_region_validation() -> None:
    with pytest.raises(ValueError):
        Part(name="P", source_file="p.stl", regions=[SurfaceRegion(name="a"), SurfaceRegion(name="a")])
    with pytest.raises(ValueError):
        Part(name="P", source_file="p.stl", regions=[SurfaceRegion(name="a", members=[0]),
                                                     SurfaceRegion(name="b", members=[0])])
    with pytest.raises(ValueError):
        SurfaceRegion(name="a", patch="1bad name")


def test_patch_names_and_labels() -> None:
    part = Part(name="Body", source_file="b.stl", regions=[
        SurfaceRegion(name="nose", members=[0], patch="nose"), SurfaceRegion(name="rest", members=[1, 2]),
        SurfaceRegion(name="tail", members=[3], patch="nose")])
    assert part.patch_names() == ["nose", "Body"]
    ids = np.array([0, 1, 2, 3, 4])
    assert regions.region_labels(part, ids).tolist() == [0, 1, 1, 2, -1]
    assert regions.patch_labels(part, ids, part.patch_names()).tolist() == [0, 1, 1, 0, 1]


def test_region_ids_file_is_versioned(tmp_path: Path) -> None:
    a = regions.write_ids(tmp_path, "Box", np.array([0, 1, 1]))
    b = regions.write_ids(tmp_path, "Box", np.array([0, 1, 2]))
    assert a != b and a.exists() and b.exists()
    assert regions.write_ids(tmp_path, "Box", np.array([0, 1, 1])) == a
    assert regions.read_ids(a, 3).tolist() == [0, 1, 1]
    with pytest.raises(regions.RegionError, match="3 entries for a surface of 4"):
        regions.read_ids(a, 4)


def test_angle_split_of_a_box_gives_six_regions(tmp_path: Path) -> None:
    cube = pv.Box(level=3, quads=False).triangulate().clean()
    labels = regions.angle_split(cube, 30.0)
    assert labels.max() + 1 == 6
    centres = cube.cell_centers().points
    for label in range(6):  # each region is one flat side
        normals = cube.compute_normals(cell_normals=True).cell_data["Normals"][labels == label]
        assert np.allclose(normals, normals[0], atol=1e-6)
    assert len(centres) == len(labels)


def test_angle_split_keeps_a_sphere_whole_and_respects_selection_and_groups() -> None:
    sphere = pv.Sphere(theta_resolution=24, phi_resolution=24)
    assert regions.angle_split(sphere, 30.0).max() == 0
    cube = pv.Box(level=1).triangulate().clean()
    up = cube.cell_centers().points[:, 2] > 0.99
    labels = regions.angle_split(cube, 30.0, selected=up)
    assert set(labels[~up]) == {-1} and set(labels[up]) == {0}
    # Groups (CAD faces) are never split: one group spanning two sides keeps them together.
    groups = np.where(cube.cell_centers().points[:, 0] > 0.99, 0, np.arange(1, cube.n_cells + 1))
    groups[up] = 0
    labels = regions.angle_split(cube, 30.0, groups=groups)
    assert labels.max() + 1 == 5


def test_transfer_ids_to_a_changed_surface() -> None:
    cube = pv.Box(level=1).triangulate().clean()
    ids = (cube.cell_centers().points[:, 2] > 0.99).astype(int)
    finer = pv.Box(level=3).triangulate().clean()
    moved = regions.transfer_ids(cube, ids, finer)
    assert moved.tolist() == (finer.cell_centers().points[:, 2] > 0.99).astype(int).tolist()


# -- self-intersections --------------------------------------------------------------------


def test_two_overlapping_spheres_self_intersect() -> None:
    mesh = two_spheres()
    report = check_surface(mesh)
    assert report.self_intersections == 172 and len(report.intersecting) == 172
    assert not report.snappy_ready and "172 self-intersecting triangles" in report.summary()
    centres = mesh.cell_centers().points[list(report.intersecting)]
    assert (np.abs(centres[:, 0] - 0.15) < 0.2).all()  # around the circle where the spheres cross


def test_clean_surfaces_do_not_self_intersect() -> None:
    for mesh in (pv.Sphere(theta_resolution=40, phi_resolution=40), pv.Box(level=2).triangulate().clean()):
        report = check_surface(mesh)
        assert report.self_intersections == 0 and report.intersecting == ()
        assert report.snappy_ready


def test_a_crossing_flap_is_found() -> None:
    sphere = pv.Sphere(theta_resolution=16, phi_resolution=16)
    flap = pv.Plane(center=(0.45, 0, 0), direction=(1, 0, 0), i_size=0.6, j_size=0.6).triangulate()
    mesh = (sphere + flap).clean()
    found = intersecting_triangles(mesh.points, regions.triangles(mesh))
    assert len(found) >= 2 and set(found) & set(range(sphere.n_cells, mesh.n_cells))


def test_large_surfaces_skip_the_check_with_a_note(monkeypatch) -> None:
    monkeypatch.setattr(checks, "MAX_INTERSECTION_TRIANGLES", 100)
    report = check_surface(pv.Sphere())
    assert report.self_intersections is None and report.intersections_note == "not checked: more than 100 triangles"
    assert "self-intersections not checked: more than 100 triangles" in report.summary()
    assert not report.snappy_ready


@pytest.mark.slow
def test_self_intersection_timing_one_million_triangles() -> None:
    """The measured time is recorded in D-069 (a log, not an assertion)."""
    import time

    sphere = pv.Sphere(theta_resolution=710, phi_resolution=710)
    t0 = time.perf_counter()
    found = intersecting_triangles(sphere.points, regions.triangles(sphere))
    print(f"self-intersections: {sphere.n_cells} triangles in {time.perf_counter() - t0:.2f} s")
    assert sphere.n_cells > 1_000_000 and len(found) == 0
