"""Tests for the project -> meshing case orchestration."""

from pathlib import Path

import pytest
import pyvista as pv

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.mesh_case import MARKER_NAME, CaseDirectoryNotOursError
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.meshing import MeshingNotReady, case_dir_for, prepare_job, readiness


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
