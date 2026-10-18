"""CAD import (STEP / IGES / BREP) through OCP: names, colours, units, tessellation (Task 3.2).

The CAD files are written by the tests (tests/cad_corpus.py)."""

from pathlib import Path

import numpy as np
import pytest

from tests import cad_corpus
from tests.test_import import _fresh_cache, make_window  # noqa: F401 (fixtures)
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.geometry import regions
from vortexcfd.geometry.cad import FACE_ARRAY, CadImportError, read_cad, tessellate
from vortexcfd.geometry.checks import check_surface, surface_report
from vortexcfd.geometry.loader import load_surface
from vortexcfd.gui import part_ops


@pytest.fixture
def project(tmp_path: Path) -> Project:
    p = Project.new("CAD")
    (tmp_path / "proj" / "geometry").mkdir(parents=True)
    p.save(tmp_path / "proj" / "p.json")
    return p


def test_box_with_named_faces_and_colour(tmp_path: Path) -> None:
    model = read_cad(cad_corpus.named_box_step(tmp_path / "box.step"))
    assert model.units == "mm" and [b.name for b in model.bodies] == ["Body"]
    assert [f.name for f in model.faces] == cad_corpus.BOX_FACE_NAMES
    assert model.faces[0].color == "#ff0000" and model.faces[1].color is None
    groups = model.face_groups()
    assert [(n, len(ids)) for n, ids, _ in groups] == [("inlet", 1), ("outlet", 1), ("wall", 2), ("top", 1), ("bottom", 1)]
    mesh = tessellate(model, model.default_linear_deflection(), 20.0)
    assert mesh.n_cells == 12 and np.bincount(mesh.cell_data[FACE_ARRAY]).tolist() == [2] * 6
    assert mesh.bounds == pytest.approx((0, 10, 0, 20, 0, 30))


def test_tessellated_cad_passes_the_surface_checks(tmp_path: Path) -> None:
    for path in (cad_corpus.named_box_step(tmp_path / "box.step"), cad_corpus.cylinder_step(tmp_path / "rod.step")):
        model = read_cad(path)
        report = check_surface(tessellate(model, model.default_linear_deflection(), 20.0))
        assert report.watertight and report.snappy_ready and report.signed_volume > 0, path.name


def test_cylinder_triangles_grow_as_the_deflection_shrinks(tmp_path: Path) -> None:
    model = read_cad(cad_corpus.cylinder_step(tmp_path / "rod.step"))
    assert [b.name for b in model.bodies] == ["Rod"] and len(model.faces) == 3
    counts = [tessellate(model, d, 45.0).n_cells for d in (1.0, 0.1, 0.01)]
    assert counts[0] < counts[1] < counts[2]
    coarse, fine = tessellate(model, 1.0, 45.0).n_cells, tessellate(model, 1.0, 5.0).n_cells
    assert coarse < fine
    # The chord error stays within the deflection: every point lies within d of the radius 5 surface.
    mesh = tessellate(model, 0.01, 45.0)
    centres = mesh.cell_centers().points
    side = (centres[:, 2] > 1e-6) & (centres[:, 2] < 20 - 1e-6)
    radius = np.hypot(centres[side, 0], centres[side, 1])
    assert (radius <= 5 + 1e-9).all() and (radius >= 5 - 0.011).all()


def test_assembly_of_two_solids(tmp_path: Path) -> None:
    model = read_cad(cad_corpus.assembly_step(tmp_path / "pair.step"))
    assert [(b.name, len(b.faces)) for b in model.bodies] == [("Block", 6), ("Pin", 3)]
    pin = tessellate(model, 0.05, 20.0, bodies=[1])
    assert pin.bounds[0] == pytest.approx(45, abs=0.01) and pin.bounds[1] == pytest.approx(55, abs=0.01)
    assert set(pin.cell_data[FACE_ARRAY]) == {6, 7, 8}


def test_units_metre_step_file_is_read_in_millimetres(tmp_path: Path, project: Project) -> None:
    path = cad_corpus.named_box_step(tmp_path / "proj" / "geometry" / "box_m.step", unit="M")
    assert "1.E-02" in path.read_text() or "0.01" in path.read_text()  # written in metres
    (part,) = part_ops.cad_parts(project.path.parent, path, None, "regions", set())
    assert part.units == "mm"
    mesh = load_surface(project.path.parent / part.source_file, part.units)
    assert mesh.bounds == pytest.approx((0, 0.01, 0, 0.02, 0, 0.03))


def test_brep_and_iges(tmp_path: Path) -> None:
    brep = read_cad(cad_corpus.box_brep(tmp_path / "b.brep"))
    assert brep.units is None and len(brep.faces) == 6 and brep.bodies[0].name == "b"
    iges = read_cad(cad_corpus.box_iges(tmp_path / "b.igs"))
    assert iges.units == "mm" and len(iges.faces) == 6
    assert tessellate(iges, 0.1, 20.0).bounds == pytest.approx((0, 10, 0, 20, 0, 30))


def test_bad_cad_files(tmp_path: Path) -> None:
    (tmp_path / "bad.step").write_text("ISO-10303-21; not really")
    with pytest.raises(CadImportError):
        read_cad(tmp_path / "bad.step")
    with pytest.raises(CadImportError, match="Unsupported"):
        read_cad(tmp_path / "x.stl")


def test_cad_part_regions_and_retessellation_are_undoable(project: Project, tmp_path: Path) -> None:
    path = cad_corpus.named_box_step(project.path.parent / "geometry" / "box.step")
    (part,) = part_ops.cad_parts(project.path.parent, path, None, "regions", set())
    assert part.cad.file == "geometry/box.step" and part.cad.angular_deflection == 20.0
    assert part.cad.linear_deflection == pytest.approx(37.417e-6, rel=1e-3)  # 1/1000 of the diagonal, m
    assert [r.name for r in part.regions] == ["inlet", "outlet", "wall", "top", "bottom"]
    assert part.regions[0].color == "#ff0000" and part.regions[2].members == [2, 3]
    project.add_part(part)
    first = project.sim.geometry.parts[0]
    fields = part_ops.retessellate(project, 0, angular_deflection=10.0)
    project.update_part(0, **fields)
    second = project.sim.geometry.parts[0]
    assert second.source_file != first.source_file and second.cad.angular_deflection == 10.0
    assert second.regions == first.regions
    project.undo()
    assert project.sim.geometry.parts[0] == first
    # Same deflections again: the cached files are reused.
    assert part_ops.retessellate(project, 0, angular_deflection=20.0)["source_file"] == first.source_file


def test_cylinder_part_triangle_count_follows_the_deflection(project: Project) -> None:
    path = cad_corpus.cylinder_step(project.path.parent / "geometry" / "rod.step")
    (part,) = part_ops.cad_parts(project.path.parent, path, None, "regions", set())
    project.add_part(part)
    before = surface_report(project.path.parent / part.source_file, "mm").n_triangles
    project.update_part(0, **part_ops.retessellate(project, 0, linear_deflection=part.cad.linear_deflection / 10))
    after = project.sim.geometry.parts[0]
    report = surface_report(project.path.parent / after.source_file, "mm")
    assert report.n_triangles > before and report.watertight
    ids = regions.read_ids(project.path.parent / after.region_ids, report.n_triangles)
    assert set(ids) == {0, 1, 2}


def test_assembly_as_parts_or_regions(project: Project) -> None:
    path = cad_corpus.assembly_step(project.path.parent / "geometry" / "pair.step")
    block, pin = part_ops.cad_parts(project.path.parent, path, None, "parts", set())
    assert (block.name, block.cad.bodies, pin.name, pin.cad.bodies) == ("Block", [0], "Pin", [1])
    assert block.regions == [] and pin.regions == []  # unnamed faces: one region per body
    (both,) = part_ops.cad_parts(project.path.parent, path, None, "regions", set())
    assert [(r.name, r.members) for r in both.regions] == [("Block", [0, 1, 2, 3, 4, 5]), ("Pin", [6, 7, 8])]


# -- GUI ---------------------------------------------------------------------------------------


def test_import_step_from_the_file_menu(make_window, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    step = cad_corpus.named_box_step(tmp_path / "src" / "box.step")
    w = make_window(import_path=step, units=None)  # STEP never asks for units
    w.act_import.trigger()
    (part,) = w.project.sim.geometry.parts
    assert part.name == "box" and part.units == "mm" and part.cad.file == "geometry/box.step"
    assert [r.name for r in part.regions] == ["inlet", "outlet", "wall", "top", "bottom"]
    assert (w.project.path.parent / "geometry" / "box.step").is_file()
    p = w.properties
    assert p._rows["cad_linear"].isVisible() and p.cad_file_label.text() == "geometry/box.step"
    assert p.check_values["watertight"].text() == "yes"
    assert "5 regions: inlet, outlet, wall, top, bottom" in w.console.text()
    # Editing the angular deflection re-tessellates as one undo step.
    p.cad_angular.setValue(10.0)
    p.cad_angular.editingFinished.emit()
    assert w.project.sim.geometry.parts[0].cad.angular_deflection == 10.0
    assert w.project.undo_label == "Edit part 'box' (cad, source_file, region_ids)"


def test_import_assembly_asks_for_parts_or_regions(make_window, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    step = cad_corpus.assembly_step(tmp_path / "src" / "pair.step")
    w = make_window(import_path=step)
    w.dialogs.solids_mode = "parts"
    w.act_import.trigger()
    assert w.dialogs.solids_asked == [("pair.step", ["Block", "Pin"])]
    assert [p.name for p in w.project.sim.geometry.parts] == ["Block", "Pin"]
    assert w.project.undo_label == "Import pair.step (2 parts)"


def test_brep_import_asks_for_units(make_window, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    brep = cad_corpus.box_brep(tmp_path / "src" / "b.brep")
    w = make_window(import_path=brep, units="cm")
    w.act_import.trigger()
    (part,) = w.project.sim.geometry.parts
    assert part.units == "cm"
    assert load_surface(w.project.path.parent / part.source_file, "cm").bounds == pytest.approx((0, .1, 0, .2, 0, .3))


def test_unreadable_cad_import_leaves_nothing(make_window, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    bad = tmp_path / "src" / "bad.step"
    bad.write_text("ISO-10303-21;")
    w = make_window(import_path=bad)
    w.act_import.trigger()
    assert w.project.sim.geometry.parts == []
    assert list((w.project.path.parent / "geometry").iterdir()) == []
    assert isinstance(Part, type)
