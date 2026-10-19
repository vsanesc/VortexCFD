"""Tests for the project -> meshing case orchestration."""

from pathlib import Path

import pytest
import pyvista as pv

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.mesh_case import MARKER_NAME, CaseDirectoryNotOursError
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.workflow.meshing import MeshingNotReady, case_dir_for, prepare_job, readiness


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def make_project(tmp_path: Path, units: str = "mm", with_part: bool = True, save: bool = True) -> Project:
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True, exist_ok=True)
    project = Project.new("m")
    if with_part:
        pv.Sphere(radius=500.0, theta_resolution=16, phi_resolution=16).save(str(folder / "geometry" / "ball.stl"))
        project.add_part(Part(name="Ball 1", source_file="geometry/ball.stl", units=units))
    if save:
        project.save(folder / "p.json")
    return project


def test_readiness_reasons(tmp_path: Path) -> None:
    unsaved = make_project(tmp_path, save=False)
    assert "Save the project" in readiness(unsaved) and case_dir_for(unsaved) is None
    assert "Import at least one part" in readiness(make_project(tmp_path / "a", with_part=False))
    p = make_project(tmp_path / "b")
    assert readiness(p) is None
    p.update_domain(enabled=False)
    assert "Enable the fluid domain" in readiness(p)
    p.update_domain(enabled=True)
    p.add_part(Part(name="gone", source_file="geometry/gone.stl", units="m"))
    assert "'gone' is missing" in readiness(p)


def test_prepare_job_writes_case_with_stl_in_metres(tmp_path: Path) -> None:
    project = make_project(tmp_path, units="mm")  # a 1 m sphere stored in mm
    job = prepare_job(project)
    case = tmp_path / "proj" / "case"
    assert job.case_dir == case and (case / MARKER_NAME).is_file()
    stl = pv.read(str(case / "constant" / "triSurface" / "Ball_1.stl"))
    assert stl.bounds[1] - stl.bounds[0] == pytest.approx(1.0, rel=0.02)  # metres
    assert job.inputs.parts == ("Ball_1",) and job.inputs.reference_length == pytest.approx(1.0, rel=0.02)
    d = read_foam_file(case / "system" / "snappyHexMeshDict")
    assert "Ball_1" in d["castellatedMeshControls"]["refinementSurfaces"]
    assert (case / "system" / "blockMeshDict").is_file() and (case / "case.foam").is_file()


def test_prepare_job_refuses_a_foreign_case_dir(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    foreign = tmp_path / "proj" / "case" / "constant"
    foreign.mkdir(parents=True)
    (foreign / "mine.txt").write_text("user file")
    with pytest.raises(CaseDirectoryNotOursError):
        prepare_job(project)
    assert (foreign / "mine.txt").read_text() == "user file"


def test_prepare_job_not_ready(tmp_path: Path) -> None:
    with pytest.raises(MeshingNotReady, match="Import at least one part"):
        prepare_job(make_project(tmp_path, with_part=False))


# -- surface size from l_ref and curvature refinement (D-085) -------------------------------------------


def _slab_project(tmp_path: Path) -> Project:
    """A wing-like slab: chord 1 m along x, span 3 m along y, so L = 3 m and the automatic l_ref = 1 m."""
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True, exist_ok=True)
    pv.Box(bounds=(0.0, 1.0, 0.0, 3.0, -0.06, 0.06)).triangulate().save(str(folder / "geometry" / "slab.stl"))
    project = Project.new("s")
    project.add_part(Part(name="Slab", source_file="geometry/slab.stl", units="m"))
    project.save(folder / "p.json")
    return project


def test_surface_levels_follow_l_ref_and_curvature_entries(tmp_path: Path) -> None:
    import math

    from vortexcfd.workflow.meshing import surface_length

    project = _slab_project(tmp_path)
    job = prepare_job(project)
    est = job.inputs.estimate()
    assert job.inputs.reference_length == pytest.approx(3.0) and job.inputs.surface_length == pytest.approx(1.0)
    assert est.surface_length == pytest.approx(1.0)
    assert est.level_max == math.ceil(math.log2(est.base_size / 0.01))  # 0.01 x l_ref, not 0.01 x L
    surfaces = read_foam_file(job.case_dir / "system" / "snappyHexMeshDict")["castellatedMeshControls"][
        "refinementSurfaces"]
    assert list(surfaces["Slab"]["level"]) == [est.level_max - 1, est.level_max]
    # curvatureLevel (cells per radius, start level, max level, ignore level): 2 levels above the surface
    assert list(surfaces["Slab"]["curvatureLevel"]) == [4, 0, est.level_max + 2, -1]
    assert est.curvature_level == est.level_max + 2 and est.curvature_size == pytest.approx(est.surface_size / 4)
    length = surface_length(project, job.box)
    assert (length.value, length.source) == (pytest.approx(1.0), "l_ref_auto")

    project.update_reports(reference_length=0.5)  # an explicit l_ref
    job = prepare_job(project)
    assert job.inputs.surface_length == 0.5
    assert job.inputs.estimate().level_max == math.ceil(math.log2(est.base_size / 0.005))

    project.update_mesh(surface_size_reference="largest_extent", curvature_levels=0)  # the v9 behaviour
    job = prepare_job(project)
    old = job.inputs.estimate()
    assert job.inputs.surface_length == pytest.approx(3.0)
    assert old.level_max == math.ceil(math.log2(old.base_size / 0.03))
    surfaces = read_foam_file(job.case_dir / "system" / "snappyHexMeshDict")["castellatedMeshControls"][
        "refinementSurfaces"]
    assert "curvatureLevel" not in surfaces["Slab"] and old.curvature_level == old.level_max


def test_part_level_override_moves_its_curvature_level(tmp_path: Path) -> None:
    project = _slab_project(tmp_path)
    project.update_part(0, surface_level_min=3, surface_level_max=4)
    surfaces = read_foam_file(prepare_job(project).case_dir / "system" / "snappyHexMeshDict")[
        "castellatedMeshControls"]["refinementSurfaces"]
    assert list(surfaces["Slab"]["level"]) == [3, 4] and list(surfaces["Slab"]["curvatureLevel"]) == [4, 0, 6, -1]


def test_warning_when_l_ref_is_automatic(tmp_path: Path) -> None:
    from vortexcfd.workflow.meshing import SurfaceLength, surface_length, surface_length_warning

    project = _slab_project(tmp_path)
    box = prepare_job(project).box
    auto = surface_length(project, box)
    assert "l_ref is not set" in surface_length_warning(auto) and "bounding-box length" in surface_length_warning(auto)
    assert auto.describe() == "l_ref = 1 m (auto: bounding-box length, x extent)"
    project.update_reports(reference_length=1.0)
    chosen = surface_length(project, box)
    assert surface_length_warning(chosen) is None and chosen.describe() == "l_ref = 1 m"
    project.update_mesh(surface_size_reference="largest_extent")
    assert surface_length_warning(surface_length(project, box)) is None
    assert SurfaceLength(3.0, "largest_extent").describe() == "L = 3 m (largest extent of the parts)"


def test_l_ref_is_a_meshing_input_only_when_it_sizes_the_surface(tmp_path: Path) -> None:
    from vortexcfd.workflow.meshing import inputs_hash

    project = _slab_project(tmp_path)
    before = inputs_hash(project)
    project.update_reports(reference_length=0.8)
    assert inputs_hash(project) != before
    project.update_mesh(surface_size_reference="largest_extent")
    legacy = inputs_hash(project)
    project.update_reports(reference_length=0.9)
    assert inputs_hash(project) == legacy  # L sizes the surface: l_ref changes forces only
