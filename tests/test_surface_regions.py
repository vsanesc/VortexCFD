"""Refinement regions from imported geometry (D-145): the model, the surface geometry, the estimate, the snappyHexMesh
entries, the case files and the mesh hash. No OpenFOAM run, except the one ``slow`` test at the end."""

from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, RefinementVolume, SurfaceShape
from vortexcfd.core.project_io import migrate
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.mesh_case import (
    INSIDE_DISTANCE,
    TRI_SURFACE,
    SurfaceRegionEntry,
    VolumeEntry,
    volume_geometry,
    volume_region,
)
from vortexcfd.geometry import refinement_volumes as rv
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.workflow import meshing, refinement
from tests.test_refinement_volumes import sphere_project


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def write_box(path: Path, bounds=(0.8, 2.2, -0.5, 0.5, -0.5, 0.5), inward: bool = False) -> Path:
    box = pv.Box(bounds=bounds).triangulate()
    if inward:
        box.flip_faces(inplace=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    box.save(str(path))
    return path


def region_project(tmp_path: Path, mode: str = "inside", distance: float = 0.0, target: float = 0.1):
    project = sphere_project(tmp_path)
    write_box(project.folder / "geometry" / "region.stl")
    shape = SurfaceShape(file="geometry/region.stl", mode=mode, distance=distance)
    vid = project.add_refinement_volume(RefinementVolume(id="x", name="wake_box", shape=shape, target_size=target))
    return project, vid


# -- model ------------------------------------------------------------------------------------------


def test_surface_shape_model_and_migration() -> None:
    shape = SurfaceShape(file="geometry/r.stl")
    assert (shape.kind, shape.units, shape.mode, shape.distance) == ("surface", "m", "inside", 0.0)
    with pytest.raises(ValueError, match="distance"):
        SurfaceShape(file="geometry/r.stl", mode="distance")
    volume = RefinementVolume(id="v1", name="r", shape={"kind": "surface", "file": "g/r.stl", "units": "mm"},
                              target_size=0.01)
    assert isinstance(volume.shape, SurfaceShape) and volume.shape.units == "mm"
    assert CURRENT_SCHEMA_VERSION == 22
    assert migrate({"schema_version": 21, "x": 1}) == {"schema_version": 22, "x": 1}


def test_part_becomes_a_refinement_region_in_one_undo_step(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    write_box(project.folder / "geometry" / "blob part.stl")
    from vortexcfd.core.model import Part

    project.add_part(Part(name="blob part", source_file="geometry/blob part.stl", units="m"))
    vid = project.part_to_refinement_region(1, 0.05)
    sim = project.sim
    assert [p.name for p in sim.geometry.parts] == ["Ball"]
    volume = project.volume(vid)
    assert volume.name == "blob_part" and volume.shape == SurfaceShape(file="geometry/blob part.stl")
    assert volume.target_size == 0.05
    project.undo()
    assert [p.name for p in project.sim.geometry.parts] == ["Ball", "blob part"]
    assert project.sim.refinement_volumes == []


# -- geometry ---------------------------------------------------------------------------------------


def test_region_containment_volume_and_growth(tmp_path: Path) -> None:
    mesh = refinement.load_region(write_box(tmp_path / "b.stl", (-1, 1, -1, 1, -1, 1)), "m")
    region = rv.SurfaceRegion(mesh)
    assert rv.contains(region, [[0, 0, 0], [1.5, 0, 0]]).tolist() == [True, False]
    assert rv.volume(region) == pytest.approx(8.0)
    grown = rv.grow(region, 0.5)
    assert rv.bounds(grown) == pytest.approx((-1.5, 1.5, -1.5, 1.5, -1.5, 1.5))
    exact = 8 + 6 * 4 * 0.5 + 12 * 2 * np.pi * 0.25 / 4 + 4 / 3 * np.pi * 0.125  # the box's Minkowski sum
    assert rv.volume(grown) == pytest.approx(exact, rel=0.04)
    shell = rv.SurfaceRegion(mesh, "distance", 0.25)
    assert rv.contains(shell, [[0, 0, 0], [0.9, 0, 0], [1.2, 0, 0], [1.3, 0, 0]]).tolist() == [False, True, True, False]
    assert rv.outline(region) is mesh


def test_inward_surfaces_are_flipped_and_open_ones_refused(tmp_path: Path) -> None:
    mesh = refinement.load_region(write_box(tmp_path / "in.stl", inward=True), "m")
    assert rv.contains(rv.SurfaceRegion(mesh), [[1.5, 0, 0]]).tolist() == [True]
    pv.Plane().triangulate().save(str(tmp_path / "open.stl"))  # an open sheet
    with pytest.raises(refinement.RegionFileError, match="not a closed surface"):
        refinement.load_region(tmp_path / "open.stl", "m")
    with pytest.raises(refinement.RegionFileError):
        refinement.load_region(tmp_path / "missing.stl", "m")


def test_estimate_counts_the_region(tmp_path: Path) -> None:
    project, _vid = region_project(tmp_path)
    box = meshing.loaded_parts(project)[0]
    est = meshing.project_estimate(project, box)
    infos = refinement.volume_infos(project, box, est)
    assert infos[0].status == "inside" and infos[0].extra_cells > 0
    assert meshing.estimate_with_volumes(project, box).volume_cells == infos[0].extra_cells


# -- dictionaries and case files --------------------------------------------------------------------------


def test_region_entries_in_the_snappy_dictionary() -> None:
    inside = VolumeEntry("r", SurfaceRegionEntry("volume_r.stl"), 3)
    assert volume_geometry(inside) == {"volume_r.stl": {"type": "triSurfaceMesh", "name": "volume_r"}}
    assert volume_region(inside, False) == {"mode": "inside", "levels": [[INSIDE_DISTANCE, 3]]}
    near = VolumeEntry("r", SurfaceRegionEntry("volume_r.stl", "distance", 0.2), 4)
    assert volume_region(near, False) == {"mode": "distance", "levels": [[0.2, 4]]}
    assert volume_region(near, True)["mode"] == "distance"  # 2D: directional, same distance
    assert volume_region(near, True)["levelIncrement"] == [0, 0, [4, 0, 4]]


def test_prepare_job_writes_the_region_and_never_a_wall(tmp_path: Path) -> None:
    project, vid = region_project(tmp_path)
    job = meshing.prepare_job(project)
    entry = job.inputs.volumes[0]
    assert entry.surface_file == "volume_wake_box.stl"
    case = job.case_dir
    stl = case / TRI_SURFACE / "volume_wake_box.stl"
    assert stl.is_file() and pv.read(str(stl)).bounds == pytest.approx((0.8, 2.2, -0.5, 0.5, -0.5, 0.5))
    snappy = read_foam_file(case / "system" / "snappyHexMeshDict")
    geometry = snappy["geometry"]
    assert geometry["volume_wake_box.stl"]["type"] == "triSurfaceMesh"
    assert geometry["volume_wake_box.stl"]["name"] == "volume_wake_box"
    controls = snappy["castellatedMeshControls"]
    region = controls["refinementRegions"]["volume_wake_box"]
    assert region["mode"] == "inside" and list(region["levels"][0])[1] == entry.level
    assert "volume_wake_box" not in controls["refinementSurfaces"]  # not a wall
    assert "volume_wake_box" not in (case / "system" / "surfaceFeatureExtractDict").read_text()
    # distance mode, then the region removed: the file goes too
    project.update_refinement_volume(vid, shape={"mode": "distance", "distance": 0.15})
    job = meshing.prepare_job(project)
    region = read_foam_file(case / "system" / "snappyHexMeshDict")["castellatedMeshControls"]["refinementRegions"]
    assert region["volume_wake_box"]["mode"] == "distance"
    assert list(region["volume_wake_box"]["levels"][0]) == pytest.approx([0.15, entry.level])
    project.remove_refinement_volume(vid)
    meshing.prepare_job(project)
    assert not stl.exists()


def test_region_turns_with_the_parts(tmp_path: Path) -> None:
    project, _vid = region_project(tmp_path)
    project.update_inflow(alpha_deg=30.0)
    job = meshing.prepare_job(project)
    b = pv.read(str(job.case_dir / TRI_SURFACE / "volume_wake_box.stl")).bounds
    assert b[4] < -0.5 - 0.1  # nose up about the sphere's centre: the box behind it goes down (D-120)
    from vortexcfd.geometry.attitude import rotate_surface

    expected = rotate_surface(pv.read(str(project.folder / "geometry" / "region.stl")), 30.0, (0.0, 0.0, 0.0)).bounds
    assert b == pytest.approx(expected, abs=1e-6)


def test_hash_follows_the_region_file_and_readiness_its_presence(tmp_path: Path) -> None:
    project, _vid = region_project(tmp_path)
    before = meshing.inputs_hash(project)
    write_box(project.folder / "geometry" / "region.stl", (0.8, 2.5, -0.5, 0.5, -0.5, 0.5))
    assert meshing.inputs_hash(project) != before
    assert meshing.readiness(project) is None
    (project.folder / "geometry" / "region.stl").unlink()
    assert "Refinement region 'wake_box'" in meshing.readiness(project)


# -- real mesh (not run by agents except once per change; the owner runs it through scripts/ship.sh) --------


@pytest.mark.slow
@pytest.mark.openfoam
def test_an_imported_box_region_behind_a_sphere_is_meshed_at_its_level(tmp_path: Path) -> None:
    """A sphere with an imported box-shaped STL as an inside-mode region, meshed for real: the cells well inside the
    box are at the region's level (their volume is that level's cube), checkMesh passes and the region is no wall."""
    from vortexcfd.core.model import BoxShape
    from vortexcfd.foam.mesh_run import MeshRun

    project = sphere_project(tmp_path)
    project.update_mesh(layer_sizing="relative", layers=0, background_cells_target=20_000)
    bounds = (0.7, 2.3, -0.5, 0.5, -0.5, 0.5)
    write_box(project.folder / "geometry" / "region.stl", bounds)
    shape = SurfaceShape(file="geometry/region.stl")
    project.add_refinement_volume(RefinementVolume(id="x", name="behind", shape=shape, target_size=0.1))
    job = meshing.prepare_job(project)
    level = job.inputs.volumes[0].level
    base = job.inputs.estimate().base_size
    run = MeshRun(job.case_dir, parts=job.inputs.patches, step_timeout_s=120)
    run.start()
    result = run.wait(150)
    assert result is not None and result.success and result.report.valid and result.report.mesh_ok
    boundary = (job.case_dir / "constant" / "polyMesh" / "boundary").read_text()
    assert "volume_behind" not in boundary
    reader = pv.OpenFOAMReader(str(job.case_dir / "case.foam"))
    internal = reader.read()["internalMesh"].compute_cell_sizes(length=False, area=False, volume=True)
    centres = np.asarray(internal.cell_centers().points)
    margin = 2 * base / 2 ** level
    inner = BoxShape(centre=((bounds[0] + bounds[1]) / 2, 0.0, 0.0),
                     size=(bounds[1] - bounds[0] - 2 * margin, 1.0 - 2 * margin, 1.0 - 2 * margin))
    inside = rv.contains(inner, centres)
    assert inside.sum() > 100
    expected = (base / 2 ** level) ** 3
    assert np.asarray(internal.cell_data["Volume"])[inside] == pytest.approx(expected, rel=0.02)
