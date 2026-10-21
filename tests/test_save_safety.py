"""The .vcfd project files and the save target rules (D-076); every project has a folder from its
creation, so there is no untitled workspace any more (D-077).

Every dialog is a fake (tests/fakes.py)."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

from tests import cad_corpus
from tests.geometry_corpus import box_faces, write_multi_solid
from tests.test_import import _fresh_cache, make_window, wait_geometry  # noqa: F401 (fixtures)
from vortexcfd.core import save_rules as ws
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.geometry import regions
from vortexcfd.geometry.loader import load_surface
from vortexcfd.gui import dialogs


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources(tmp_path: Path) -> dict[str, Path]:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    pv.Sphere().save(str(src / "ball.stl"))
    return {"ball": src / "ball.stl", "box": write_multi_solid(src / "box.stl", box_faces()),
            "step": cad_corpus.named_box_step(src / "body.step")}


def _import(w, path: Path) -> None:
    w.dialogs.import_path = path
    w.act_import.trigger()
    wait_geometry(w._qtbot, w)


# -- import into a project, save, reopen ---------------------------------------------------------


def test_import_save_reopen(make_window, tmp_path: Path) -> None:
    files = _sources(tmp_path)
    w = make_window()  # saved as proj/proj.json by the fixture
    for path in files.values():
        _import(w, path)
    assert w.dialogs.save_asked == []
    assert (tmp_path / "proj" / "geometry" / "body.step").is_file()
    assert [p.name for p in w.project.sim.geometry.parts] == ["ball", "box", "body"]
    assert w.save()
    target = tmp_path / "proj" / "proj.vcfd"  # the legacy .json is saved as .vcfd next to it
    assert w.project.path == target and target.is_file()
    reopened = Project.open(target)
    for part in reopened.sim.geometry.parts:
        mesh = load_surface(reopened.resolve_part_path(part), part.units)
        assert mesh.n_cells > 0
        if part.region_ids:
            assert len(regions.read_ids(target.parent / part.region_ids, mesh.n_cells)) == mesh.n_cells
        if part.cad:
            assert (target.parent / part.cad.file).is_file()
    assert reopened.sim.geometry.parts == w.project.sim.geometry.parts


def test_no_untitled_workspace_is_left(tmp_path: Path) -> None:
    """D-077 supersedes the temporary workspace of D-076: nothing of it is left in the API."""
    from vortexcfd.core import project as project_module

    assert not hasattr(Project, "ensure_folder") and not hasattr(Project, "discard_workspace")
    assert not hasattr(ws, "new_workspace") and not hasattr(project_module, "ws")
    assert Project.new("P").folder is None


# -- the save dialog's result (in-memory projects only: a project with a folder is duplicated) ----


@pytest.mark.parametrize("name", ["model.STEP", "model.step", "part.STL", "mesh.obj", "scan.ply", "body.stp",
                                  "a.iges", "a.IGS", "shape.brep"])
def test_a_geometry_file_picked_in_the_save_dialog_is_refused(make_window, tmp_path: Path, name: str) -> None:
    victim = tmp_path / name
    cad_corpus.named_box_step(victim) if victim.suffix.lower() in (".step", ".stp") else victim.write_bytes(b"geometry \x00\x01")
    before = _digest(victim)
    w = make_window(saved=False, save_path=victim)
    assert not w.save_as()
    assert _digest(victim) == before  # byte-identical
    assert not victim.with_name(victim.name + ".vcfd").exists()  # no extension appended either
    assert w.project.path is None
    assert w.dialogs.errors and "is a geometry file" in w.dialogs.errors[-1][1]
    assert w.dialogs.overwrite_asked == []
    assert "Not saved" in w.statusBar().currentMessage()


def test_a_missing_geometry_name_is_refused_too(make_window, tmp_path: Path) -> None:
    w = make_window(saved=False, save_path=tmp_path / "new.stl")
    assert not w.save()
    assert not (tmp_path / "new.stl").exists() and not (tmp_path / "new.stl.vcfd").exists()


def test_an_existing_non_project_file_is_never_overwritten(make_window, tmp_path: Path) -> None:
    for name, content in (("notes.vcfd", b"my notes"), ("list.vcfd", b"[1, 2]"),
                          ("other.vcfd", json.dumps({"name": "no version"}).encode())):
        victim = tmp_path / name
        victim.write_bytes(content)
        w = make_window(saved=False, save_path=victim)
        assert not w.save_as()
        assert victim.read_bytes() == content
        assert "is not a VortexCFD project" in w.dialogs.errors[-1][1] and w.dialogs.overwrite_asked == []


def test_an_existing_project_is_overwritten_only_after_confirmation(make_window, tmp_path: Path) -> None:
    other = Project.new("Other")
    other.save(tmp_path / "other.vcfd")
    before = _digest(tmp_path / "other.vcfd")
    w = make_window(saved=False, save_path=tmp_path / "other.vcfd")
    w.dialogs.overwrite = False
    assert not w.save_as()
    assert w.dialogs.overwrite_asked == [tmp_path / "other.vcfd"] and _digest(tmp_path / "other.vcfd") == before
    w.dialogs.overwrite = True
    assert w.save_as()
    assert Project.open(tmp_path / "other.vcfd").sim.name == "Demo"


def test_saving_to_its_own_file_does_not_ask(make_window, tmp_path: Path) -> None:
    w = make_window(saved=False, save_path=tmp_path / "mine.vcfd")
    assert w.save()
    w.add_placeholder_part()
    assert w.save() and w.dialogs.overwrite_asked == []


def test_extension_rules() -> None:
    assert ws.with_project_extension(Path("/a/wing")) == Path("/a/wing.vcfd")
    assert ws.with_project_extension(Path("/a/wing.VCFD")) == Path("/a/wing.VCFD")
    assert ws.with_project_extension(Path("/a/wing.json")) == Path("/a/wing.vcfd")
    assert ws.with_project_extension(Path("/a/wing.v2")) == Path("/a/wing.v2.vcfd")
    assert dialogs.SAVE_FILTER == "VortexCFD project (*.vcfd)"
    assert "*.vcfd" in dialogs.OPEN_FILTER and "*.json" in dialogs.OPEN_FILTER


def test_a_legacy_json_project_is_saved_as_vcfd(make_window, tmp_path: Path) -> None:
    w = make_window()  # the fixture saved it as proj/proj.json
    legacy = w.project.path
    assert legacy.suffix == ".json"
    before = _digest(legacy)
    w.add_placeholder_part()
    assert w.save()
    assert w.project.path == legacy.with_suffix(".vcfd") and Project.open(legacy.with_suffix(".vcfd"))
    assert _digest(legacy) == before  # the old file is left as it was
    assert w.dialogs.save_asked == []


# -- the hard rule in Project.save -------------------------------------------------------------


@pytest.mark.parametrize("ext", ws.GEOMETRY_EXTENSIONS)
def test_project_save_never_writes_a_geometry_extension(tmp_path: Path, ext: str) -> None:
    for name in (f"x{ext}", f"x{ext.upper()}"):
        with pytest.raises(ws.SaveTargetError, match="is a geometry file"):
            Project.new("P").save(tmp_path / name)
        assert not (tmp_path / name).exists()


def test_project_save_never_writes_over_its_own_geometry_sources(tmp_path: Path) -> None:
    project = Project.new("P")
    folder = tmp_path / "p"
    (folder / "geometry").mkdir(parents=True)
    pv.Sphere().save(str(folder / "geometry" / "ball.stl"))
    project.save(folder / "p.vcfd")
    ids = regions.write_ids(folder / "geometry", "ball", np.zeros(pv.Sphere().n_cells))
    project.add_part(Part(name="ball", source_file="geometry/ball.stl", region_ids=f"geometry/{ids.name}"))
    before = _digest(ids)
    with pytest.raises(ws.SaveTargetError, match="geometry file of this project"):
        project.save(ids)  # a .npy, not a geometry extension, but a source of this project
    assert _digest(ids) == before


def test_is_project_file(tmp_path: Path) -> None:
    good = tmp_path / "g.vcfd"
    Project.new("G").save(good)
    assert ws.is_project_file(good)
    for content in (b"", b"text", b"[1]", b'{"name": "x"}', b"\xff\xfe"):
        (tmp_path / "b").write_bytes(content)
        assert not ws.is_project_file(tmp_path / "b")
    with pytest.raises(ws.SaveTargetError, match="not a VortexCFD project"):
        Project.new("P").save(tmp_path / "b")
    assert (tmp_path / "b").read_bytes() == b"\xff\xfe"


# -- Save As duplicates the project folder (D-079) ------------------------------------------------


def _tree_digest(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)): _digest(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def _project_with_geometry(make_window, tmp_path: Path):
    files = _sources(tmp_path)
    w = make_window()
    for path in files.values():  # a plain STL, a multi-solid STL with region ids, a STEP (CAD source)
        _import(w, path)
    w.project.save(w.project.path.with_suffix(".vcfd"))
    case = w.project.folder / "case"
    case.mkdir(exist_ok=True)
    (case / "vortexcfd_mesh.json").write_text("{}")  # stands for a mesh that must not be copied
    return w


def test_save_as_duplicates_the_folder_with_its_geometry(make_window, tmp_path: Path) -> None:
    w = _project_with_geometry(make_window, tmp_path)
    original = w.project.path
    referenced = w.project.referenced_files()
    assert any(r.endswith(".npy") for r in referenced) and any(r.endswith(".step") for r in referenced)
    before = _tree_digest(original.parent)
    w.dialogs.duplicate_target = ("Wing copy", tmp_path / "copies")
    assert w.save_as()
    target = tmp_path / "copies" / "Wing copy"
    assert w.dialogs.duplicate_asked == [("Demo", original.parent.parent)]
    assert w.dialogs.save_asked == []  # no file dialog
    assert w.project.path == target / "Wing copy.vcfd" and not w.project.dirty
    assert sorted(p.name for p in target.iterdir()) == ["Wing copy.vcfd", "case", "geometry"]
    assert list((target / "case").iterdir()) == []  # mesh and results not copied
    assert w.mesh_report is None and w.run_record is None
    for rel in referenced:
        assert _digest(target / rel) == _digest(original.parent / rel), rel
    assert _tree_digest(original.parent) == before  # the original is byte-identical
    reopened = Project.open(target / "Wing copy.vcfd")
    assert reopened.sim.name == "Wing copy"
    assert reopened.sim.geometry == Project.open(original).sim.geometry
    for part in reopened.sim.geometry.parts:
        path = reopened.resolve_part_path(part)
        assert path.is_relative_to(target)
        mesh = load_surface(path, part.units)
        assert mesh.n_cells > 0
        if part.region_ids:
            assert len(regions.read_ids(target / part.region_ids, mesh.n_cells)) == mesh.n_cells
        if part.cad:
            assert (target / part.cad.file).is_file()


def test_save_as_refuses_a_non_empty_folder(make_window, tmp_path: Path) -> None:
    w = _project_with_geometry(make_window, tmp_path)
    original = w.project.path
    before = _tree_digest(original.parent)
    busy = tmp_path / "busy" / "Taken"
    busy.mkdir(parents=True)
    (busy / "notes.txt").write_text("mine")
    w.dialogs.duplicate_target = ("Taken", tmp_path / "busy")
    assert not w.save_as()
    assert sorted(p.name for p in busy.iterdir()) == ["notes.txt"] and (busy / "notes.txt").read_text() == "mine"
    assert "already exists and is not empty" in w.dialogs.errors[-1][1]
    assert w.project.path == original and _tree_digest(original.parent) == before
    w.dialogs.duplicate_target = ("bad/name", tmp_path)  # the New simulation name rules
    assert not w.save_as() and w.project.path == original
    w.dialogs.duplicate_target = None  # cancelled
    assert not w.save_as() and w.project.path == original


def test_duplicate_keeps_unsaved_edits_and_never_lands_in_its_own_folder(tmp_path: Path) -> None:
    project = Project.create(tmp_path, "Src")
    project.rename("Edited")  # unsaved: the duplicate takes the current state, the original file stays
    before = _digest(project.path)
    copy, missing = project.duplicate(tmp_path, "Dup")
    assert missing == [] and copy.sim.name == "Dup" and _digest(project.path) == before
    from vortexcfd.core.project import ProjectFolderError

    with pytest.raises(ProjectFolderError, match="inside the project"):
        project.duplicate(project.folder, "Nested")
    assert not (project.folder / "Nested").exists()
    project.add_part(Part(name="gone", source_file="geometry/gone.stl"))
    copy2, missing2 = project.duplicate(tmp_path, "Dup2")
    assert missing2 == ["geometry/gone.stl"]  # reported, not copied
    project.add_part(Part(name="out", source_file="../elsewhere.stl"))
    with pytest.raises(ProjectFolderError, match="outside the project folder"):
        project.duplicate(tmp_path, "Dup3")
    assert not (tmp_path / "Dup3").exists()


def test_save_as_warns_in_a_dialog_about_missing_geometry(make_window, tmp_path: Path) -> None:
    w = make_window()
    w.project.add_part(Part(name="gone", source_file="geometry/gone.stl"))
    w.dialogs.duplicate_target = ("Copy", tmp_path / "copies")
    assert w.save_as()
    assert w.project.path == tmp_path / "copies" / "Copy" / "Copy.vcfd"
    assert len(w.dialogs.warnings) == 1
    title, text = w.dialogs.warnings[0]
    assert title == "Save As" and "geometry/gone.stl" in text and "were not copied" in text
    w.project.remove_part(0)  # nothing missing any more: no dialog
    w.dialogs.duplicate_target = ("Copy2", tmp_path / "copies")
    assert w.save_as() and len(w.dialogs.warnings) == 1


def test_a_project_writes_only_inside_its_own_folder(tmp_path: Path, monkeypatch) -> None:
    """Regression (D-095): on 2026-10-18 the save-first import flow put a project file in the home
    folder, so geometry/ and case/ landed there. A project now lives in <parent>/<name>/: importing a
    CAD file, preparing the surfaces and writing the meshing case touch nothing in <parent> or in the
    current working directory besides that folder."""
    import shutil

    from vortexcfd.bench.geometries import ensure_geometry
    from vortexcfd.workflow import meshing, part_ops, surface_prep

    parent, cwd = tmp_path / "parent", tmp_path / "cwd"
    parent.mkdir()
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    source = ensure_geometry("ahmed", tmp_path / "src")
    project = Project.create(parent, "Demo")
    dest = project.folder / "geometry" / source.name
    shutil.copy2(source, dest)
    for part in part_ops.cad_parts(project.folder, dest, None, "regions", set()):
        project.add_part(part)
    project.set_surface_prep(surface_prep.prepare(project, "cad_union"))
    project.save()
    meshing.prepare_job(project)
    assert [p.name for p in parent.iterdir()] == ["Demo"]
    assert list(cwd.iterdir()) == []
    assert (parent / "Demo" / "case" / "system" / "snappyHexMeshDict").is_file()
