"""Import of multi-solid STL files and the self-intersection check in the GUI (Task 3.1)."""

from pathlib import Path

import numpy as np

from tests.geometry_corpus import box_faces, two_spheres, write_multi_solid
from tests.test_import import _fresh_cache, make_window, wait_geometry  # noqa: F401 (fixtures)
from vortexcfd.geometry import regions
from vortexcfd.geometry.loader import load_surface


def _box_stl(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir(exist_ok=True)
    return write_multi_solid(tmp_path / "src" / "box.stl", box_faces())


def test_multi_solid_import_defaults_to_regions(make_window, tmp_path: Path) -> None:
    w = make_window(import_path=_box_stl(tmp_path), units="mm")
    w.act_import.trigger()
    assert w.dialogs.solids_asked == [("box.stl", ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"])]
    (part,) = w.project.sim.geometry.parts
    assert [r.name for r in part.regions] == ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"]
    assert [r.members for r in part.regions] == [[i] for i in range(6)] and part.units == "mm"
    project_dir = w.project.path.parent
    mesh = load_surface(project_dir / part.source_file, "mm")
    ids = regions.read_ids(project_dir / part.region_ids, mesh.n_cells)
    assert np.bincount(ids).tolist() == [8] * 6
    assert w.project.undo_label.startswith("Add part 'box'")
    assert "6 regions: xmin, xmax" in w.console.text()


def test_multi_solid_import_as_one_part_per_solid_is_one_undo_step(make_window, tmp_path: Path) -> None:
    w = make_window(import_path=_box_stl(tmp_path))
    w.dialogs.solids_mode = "parts"
    w.act_import.trigger()
    parts = w.project.sim.geometry.parts
    assert [p.name for p in parts] == ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"]
    project_dir = w.project.path.parent
    assert all(load_surface(project_dir / p.source_file, "m").n_cells == 8 for p in parts)
    assert not (project_dir / "geometry" / "box.stl").exists()  # only the per-solid files remain
    assert w.project.undo_label == "Import box.stl (6 parts)"
    w.project.undo()
    assert w.project.sim.geometry.parts == []


def test_cancelling_the_solids_question_imports_nothing(make_window, tmp_path: Path) -> None:
    w = make_window(import_path=_box_stl(tmp_path))
    w.dialogs.solids_mode = None
    w.act_import.trigger()
    assert w.project.sim.geometry.parts == []
    assert list((w.project.path.parent / "geometry").iterdir()) == []


def test_self_intersections_are_reported_and_highlighted(make_window, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    path = tmp_path / "src" / "spheres.stl"
    two_spheres().save(str(path))
    w = make_window(import_path=path)
    w.act_import.trigger()
    assert w.properties.check_values["intersections"].text() == "checking\u2026"
    wait_geometry(w._qtbot, w)
    value = w.properties.check_values["intersections"]
    assert value.text() == "172" and value.property("warn") == "true"
    assert "172 self-intersecting triangles" in w.console.text()
    assert w.scene.defect_actor is not None
    assert w.scene.defect_actor.mapper.dataset.n_cells == 172
    w.scene.set_selected(None)
    assert w.scene.defect_actor is None


def test_clean_part_shows_zero_self_intersections(make_window, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    path = tmp_path / "src" / "box.stl"
    write_multi_solid(path, [("all", box_faces()[0][1])])  # one solid: no question
    w = make_window(import_path=path)
    w.act_import.trigger()
    wait_geometry(w._qtbot, w)
    assert w.dialogs.solids_asked == []
    assert w.properties.check_values["intersections"].text() == "0"
    assert w.scene.defect_actor is None
