"""Import without saving first, the .vcfd project files and the save target rules (D-076).

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
from vortexcfd.core import workspace as ws
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


# -- import into an untitled project, first save, reopen --------------------------------------


def test_import_save_reopen(make_window, tmp_path: Path) -> None:
    files = _sources(tmp_path)
    w = make_window(saved=False, save_path=tmp_path / "work" / "wing")
    for path in files.values():
        _import(w, path)
    assert w.dialogs.save_asked == [] and w.project.path is None
    workspace = w.project.workspace
    assert workspace.parent == ws.cache_root() and (workspace / "geometry" / "body.step").is_file()
    assert [p.name for p in w.project.sim.geometry.parts] == ["ball", "box", "body"]
    assert w.save()
    target = tmp_path / "work" / "wing.vcfd"  # the extension was appended
    assert w.project.path == target and target.is_file() and not workspace.exists()
    reopened = Project.open(target)
    for part in reopened.sim.geometry.parts:
        mesh = load_surface(reopened.resolve_part_path(part), part.units)
        assert mesh.n_cells > 0
        if part.region_ids:
            assert len(regions.read_ids(target.parent / part.region_ids, mesh.n_cells)) == mesh.n_cells
        if part.cad:
            assert (target.parent / part.cad.file).is_file()
    assert reopened.sim.geometry.parts == w.project.sim.geometry.parts


def test_first_save_renames_clashing_files_in_the_whole_history(make_window, tmp_path: Path) -> None:
    files = _sources(tmp_path)
    folder = tmp_path / "busy"
    (folder / "geometry").mkdir(parents=True)
    (folder / "geometry" / "ball.stl").write_text("somebody else's file")
    w = make_window(saved=False, save_path=folder / "p.vcfd")
    _import(w, files["ball"])
    w.act_add_part.trigger()  # an edit after the import, to undo after the save
    assert w.save()
    part = w.project.sim.geometry.parts[0]
    assert part.source_file == "geometry/ball_2.stl"
    assert (folder / "geometry" / "ball.stl").read_text() == "somebody else's file"
    w.project.undo()  # the history before the save points to the renamed file too
    assert w.project.sim.geometry.parts[0].source_file == "geometry/ball_2.stl"
    assert load_surface(w.project.resolve_part_path(w.project.sim.geometry.parts[0]), "m").n_cells > 0


def test_discard_deletes_the_workspace(make_window, tmp_path: Path) -> None:
    w = make_window(saved=False)
    _import(w, _sources(tmp_path)["ball"])
    workspace = w.project.workspace
    assert workspace.is_dir()
    w.dialogs.discard = "discard"
    w.new_project()
    assert not workspace.exists() and w.project.workspace is None


def test_close_without_saving_deletes_the_workspace(make_window, tmp_path: Path) -> None:
    w = make_window(saved=False)
    _import(w, _sources(tmp_path)["ball"])
    workspace = w.project.workspace
    w.dialogs.discard = "discard"
    assert w.close()
    assert not workspace.exists()


def test_close_with_save_moves_the_workspace(make_window, tmp_path: Path) -> None:
    w = make_window(saved=False, save_path=tmp_path / "kept.vcfd")
    _import(w, _sources(tmp_path)["ball"])
    workspace = w.project.workspace
    w.dialogs.discard = "save"
    assert w.close()
    assert not workspace.exists() and (tmp_path / "geometry" / "ball.stl").is_file()
    assert Project.open(tmp_path / "kept.vcfd").sim.geometry.parts[0].source_file == "geometry/ball.stl"


def test_cancelled_close_keeps_the_workspace(make_window, tmp_path: Path) -> None:
    w = make_window(saved=False)
    _import(w, _sources(tmp_path)["ball"])
    w.dialogs.discard = "cancel"
    assert not w.close()
    assert w.project.workspace.is_dir()
    w.dialogs.discard = "discard"


# -- the save dialog's result -------------------------------------------------------------------


@pytest.mark.parametrize("name", ["model.STEP", "model.step", "part.STL", "mesh.obj", "scan.ply", "body.stp",
                                  "a.iges", "a.IGS", "shape.brep"])
def test_a_geometry_file_picked_in_the_save_dialog_is_refused(make_window, tmp_path: Path, name: str) -> None:
    victim = tmp_path / name
    cad_corpus.named_box_step(victim) if victim.suffix.lower() in (".step", ".stp") else victim.write_bytes(b"geometry \x00\x01")
    before = _digest(victim)
    w = make_window(saved=False, save_path=victim)
    _import(w, _sources(tmp_path)["ball"])
    w.act_save_as.trigger()
    assert not w.save()
    assert _digest(victim) == before  # byte-identical
    assert not victim.with_name(victim.name + ".vcfd").exists()  # no extension appended either
    assert w.project.path is None and w.project.workspace.is_dir()
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
        w = make_window(save_path=victim)
        assert not w.save_as()
        assert victim.read_bytes() == content
        assert "is not a VortexCFD project" in w.dialogs.errors[-1][1] and w.dialogs.overwrite_asked == []


def test_an_existing_project_is_overwritten_only_after_confirmation(make_window, tmp_path: Path) -> None:
    other = Project.new("Other")
    other.save(tmp_path / "other.vcfd")
    before = _digest(tmp_path / "other.vcfd")
    w = make_window(save_path=tmp_path / "other.vcfd")
    w.dialogs.overwrite = False
    assert not w.save_as()
    assert w.dialogs.overwrite_asked == [tmp_path / "other.vcfd"] and _digest(tmp_path / "other.vcfd") == before
    w.dialogs.overwrite = True
    assert w.save_as()
    assert Project.open(tmp_path / "other.vcfd").sim.name == "Demo"


def test_saving_to_its_own_file_does_not_ask(make_window, tmp_path: Path) -> None:
    w = make_window(saved=False, save_path=tmp_path / "mine.vcfd")
    assert w.save()
    w.act_add_part.trigger()
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
    w.act_add_part.trigger()
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
