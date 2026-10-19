"""Lost parts in meshing (D-052, docs/QUESTIONS.md item 54): post-mesh guard, pre-mesh warning,
per-part refinement levels and seed lines.

The reproduced case: a sphere of radius 0.5 m at the origin and a flattened ellipsoid (semi-axes
0.3 x 0.2 x 0.2 m) at x = 1.5 m with the default sizing (background cell 0.596 m). The ellipsoid lies
between the background cell-centre lines, so without seed lines snappyHexMesh never refines it and it
is lost; since the review of 2026-10-17 such parts are seeded automatically (D-052).
"""

import shutil
from pathlib import Path

import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Domain, Mesh, Part
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_case import (
    MeshCaseInput,
    needs_seed,
    part_level_range,
    seed_edge_mesh_text,
    seed_file_name,
    snappy_castellation_dict,
    snappy_hex_mesh_dict,
)
from vortexcfd.foam.mesh_record import MeshRecord, read_mesh_record, write_mesh_record
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.foam.mesh_run import MeshRunResult, lost_parts
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.workflow.meshing import thin_part_warnings

TWO = Path(__file__).parent / "data" / "two_walls"
BALL_BOUNDS = (-0.5, 0.5, -0.5, 0.5, -0.5, 0.5)
POD_BOUNDS = (1.2, 1.8, -0.2, 0.2, -0.2, 0.2)


def ball() -> pv.PolyData:
    return pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24)


def pod() -> pv.PolyData:
    return (pv.ParametricEllipsoid(0.3, 0.2, 0.2, u_res=32, v_res=16, w_res=16).triangulate().clean()
            .translate((1.5, 0, 0)))


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def _report(lost=()) -> MeshReport:
    return MeshReport(points=10, faces=40, cells=1234, max_non_orthogonality=30.0, avg_non_orthogonality=10.0,
                      max_skewness=0.5, failed_checks=0, mesh_ok=True, lost_parts=tuple(lost))


# -- guard ---------------------------------------------------------------------------------------------


def test_report_is_invalid_with_a_lost_part_even_when_checkmesh_is_ok() -> None:
    ok, lost = _report(), _report(["Pod"])
    assert ok.valid and ok.lost_messages() == []
    assert lost.mesh_ok and not lost.valid
    assert lost.lost_messages() == ["Part Pod was lost during meshing"]
    assert lost.summary().endswith("Mesh OK, Part Pod was lost during meshing")


def test_lost_parts_read_from_the_boundary_file(tmp_path: Path) -> None:
    case = tmp_path / "case"
    assert lost_parts(case, ("Ball",)) == ("Ball",)  # no mesh at all: every part is lost
    (case / "constant" / "polyMesh").mkdir(parents=True)
    shutil.copy(TWO / "boundary", case / "constant" / "polyMesh" / "boundary")  # real: Ball 2032, Pod 856
    assert lost_parts(case, ("Ball", "Pod")) == ()
    assert lost_parts(case, ("Ball", "Wing")) == ("Wing",)  # missing patch
    text = (TWO / "boundary").read_text().replace("nFaces          856;", "nFaces          0;")
    (case / "constant" / "polyMesh" / "boundary").write_text(text)
    assert lost_parts(case, ("Ball", "Pod")) == ("Pod",)  # zero faces


def test_mesh_record_keeps_lost_parts(tmp_path: Path) -> None:
    write_mesh_record(tmp_path, MeshRecord(_report(["Pod"]), "h", ("Ball", "Pod")))
    assert read_mesh_record(tmp_path).report.lost_parts == ("Pod",)
    import json

    data = json.loads((tmp_path / "vortexcfd_mesh.json").read_text())
    del data["report"]["lost_parts"]  # a record written before D-052
    (tmp_path / "vortexcfd_mesh.json").write_text(json.dumps(data))
    assert read_mesh_record(tmp_path).report.lost_parts == ()


# -- per-part levels and seed lines ---------------------------------------------------------------------


def test_part_level_range() -> None:
    assert part_level_range(4, 5, (None, None)) == (4, 5)
    assert part_level_range(4, 5, (None, 7)) == (6, 7)  # only the max: min = max - 1
    assert part_level_range(4, 5, (6, None)) == (6, 6)  # only the min: the max rises to it
    assert part_level_range(4, 5, (2, None)) == (2, 5)
    assert part_level_range(4, 5, (3, 8)) == (3, 8)


def test_seed_criterion_uses_the_cross_section() -> None:
    base = 0.596  # the reproduced case's background cell
    assert needs_seed(POD_BOUNDS, base)  # 0.4 m across < sqrt(2) x 0.596 = 0.843 m
    assert not needs_seed(BALL_BOUNDS, base)  # 1.0 m across
    plate = (0.0, 2.0, -3.0, 3.0, 0.0, 0.01)  # thin but wide: lines through its thin axis pierce it
    assert not needs_seed(plate, base)


def _inp(levels) -> MeshCaseInput:
    from vortexcfd.geometry.domain import compute_domain

    box = compute_domain([BALL_BOUNDS, POD_BOUNDS], Domain())
    union = (-0.5, 1.8, -0.5, 0.5, -0.5, 0.5)
    return MeshCaseInput(box.bounds, False, ("Ball", "Pod"), union, box.reference_length, Mesh(layer_sizing="relative"),
                         part_bounds=(BALL_BOUNDS, POD_BOUNDS), part_levels=levels)


def test_snappy_dict_seeds_small_parts_automatically_at_their_levels() -> None:
    """The seed lines refine in the castellation-only run (D-052) and are never snap features (D-084)."""
    inp = _inp(((None, None), (None, None)))
    default = snappy_castellation_dict(inp).content
    assert (default["castellatedMesh"], default["snap"], default["addLayers"]) == (True, False, False)
    controls = default["castellatedMeshControls"]
    assert controls["refinementSurfaces"]["Pod"]["level"] == [4, 5]
    assert controls["features"] == [{"file": '"Ball.eMesh"', "level": 5}, {"file": '"Pod.eMesh"', "level": 5},
                                    {"file": f'"{seed_file_name("Pod")}"', "level": 5}]  # seeded by default
    main = snappy_hex_mesh_dict(inp).content
    assert (main["castellatedMesh"], main["snap"], main["addLayers"]) == (False, True, True)
    assert main["snapControls"]["explicitFeatureSnap"] is True
    assert main["castellatedMeshControls"]["features"] == [{"file": '"Ball.eMesh"', "level": 5},
                                                           {"file": '"Pod.eMesh"', "level": 5}]  # no seed lines
    # apart from the phase switches and the seed lines, both runs read the same settings
    same = {k: v for k, v in main.items() if k not in ("castellatedMesh", "snap", "addLayers")}
    other = {k: v for k, v in default.items() if k not in ("castellatedMesh", "snap", "addLayers")}
    other["castellatedMeshControls"] = {**other["castellatedMeshControls"],
                                        "features": main["castellatedMeshControls"]["features"]}
    assert same == other
    over = snappy_castellation_dict(_inp(((None, None), (5, 6)))).content["castellatedMeshControls"]
    assert over["refinementSurfaces"]["Ball"]["level"] == [4, 5]
    assert over["refinementSurfaces"]["Pod"]["level"] == [5, 6]
    assert over["features"] == [{"file": '"Ball.eMesh"', "level": 5}, {"file": '"Pod.eMesh"', "level": 6},
                                {"file": f'"{seed_file_name("Pod")}"', "level": 6}]
    ball_over = snappy_castellation_dict(_inp(((5, 6), (None, None)))).content["castellatedMeshControls"]
    assert [f["file"] for f in ball_over["features"]] == ['"Ball.eMesh"', '"Pod.eMesh"', '"Pod_seed.eMesh"']
    # the ball is large enough: never seeded, overridden or not


def test_unseeded_case_keeps_the_single_run(tmp_path: Path) -> None:
    from vortexcfd.foam.mesh_case import CASTELLATE_DICT, MESH_COMMANDS, STEP_DICTS, build_mesh_files, prepare_case_dir

    ball_only = MeshCaseInput(_inp(((None, None), (None, None))).domain_bounds, False, ("Ball",), BALL_BOUNDS, 1.0,
                              Mesh(layer_sizing="relative"), part_bounds=(BALL_BOUNDS,), part_levels=((None, None),))
    assert snappy_castellation_dict(ball_only) is None
    main = snappy_hex_mesh_dict(ball_only).content
    assert (main["castellatedMesh"], main["snap"], main["addLayers"]) == (True, True, True)
    # a seeded set-up writes the castellation dictionary; regenerating without seeds removes it
    case = tmp_path / "case"
    prepare_case_dir(case, build_mesh_files(_inp(((None, None), (None, None)))))
    assert (case / CASTELLATE_DICT).is_file()
    prepare_case_dir(case, build_mesh_files(ball_only))
    assert not (case / CASTELLATE_DICT).exists()
    names = [n for n, _ in MESH_COMMANDS]
    assert set(STEP_DICTS) <= set(names)
    assert names.index("snappyHexMesh.castellate") == names.index("snappyHexMesh") - 1
    assert dict(MESH_COMMANDS)["snappyHexMesh.castellate"] == ["snappyHexMesh", "-overwrite", "-dict", CASTELLATE_DICT]


def test_thin_criterion_also_seeds() -> None:
    from vortexcfd.foam.mesh_case import needs_seeding

    plate = (0.0, 2.0, -3.0, 3.0, 0.0, 0.02)  # wide (not small) but 0.02 m thick
    assert needs_seeding(plate, 0.6, 5)  # thin: 0.02 m < 3 surface cells of 0.6 / 32 = 0.056 m
    assert not needs_seeding(plate, 0.6, 7)  # 3 cells of 0.6 / 128 = 0.014 m < 0.02 m
    assert not needs_seeding(BALL_BOUNDS, 0.596, 5)


def test_seed_edge_mesh_lines_cross_the_part() -> None:
    text = seed_edge_mesh_text("Pod", POD_BOUNDS)
    assert "class       featureEdgeMesh;" in text and "object      Pod_seed.eMesh;" in text
    assert "(1.14 0 0)\n(1.86 0 0)" in text  # x line: 0.3 m half extent x 1.2 about the centre 1.5
    assert "(1.5 -0.24 0)" in text and "(1.5 0 0.24)" in text
    assert text.rstrip().endswith("3\n(\n(0 1)\n(2 3)\n(4 5)\n)")


# -- pre-mesh warning ---------------------------------------------------------------------------------------


def _two_part_project(tmp_path: Path) -> Project:
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    ball().save(str(folder / "geometry" / "ball.stl"))
    pod().save(str(folder / "geometry" / "pod.stl"))
    project = Project.new("lost")
    project.add_part(Part(name="Ball", source_file="geometry/ball.stl"))
    project.add_part(Part(name="Pod", source_file="geometry/pod.stl"))
    project.save(folder / "p.json")
    return project


def test_premesh_note_for_the_small_part_only(tmp_path: Path) -> None:
    project = _two_part_project(tmp_path)
    assert thin_part_warnings(project) == [
        "Part Pod is small relative to the background mesh: refinement seeded automatically"]
    project.update_part(1, surface_level_min=4, surface_level_max=5)  # an override does not change it
    assert len(thin_part_warnings(project)) == 1


def test_premesh_warning_for_a_part_thinner_than_three_surface_cells(tmp_path: Path) -> None:
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    pv.Box(bounds=(0, 1, -1, 1, 0, 0.02)).triangulate().save(str(folder / "geometry" / "plate.stl"))
    project = Project.new("plate")
    project.add_part(Part(name="Plate", source_file="geometry/plate.stl"))
    project.save(folder / "p.json")
    (warning,) = thin_part_warnings(project)
    assert warning == "Part Plate is small relative to the background mesh: refinement seeded automatically"
    project.update_part(0, surface_level_max=12)  # cells of base / 4096: thick enough now
    assert thin_part_warnings(project) == []


# -- GUI ------------------------------------------------------------------------------------------------------


def test_gui_lost_part_fails_the_mesh_and_blocks_the_solver(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    from tests.test_mesh_gui import FakeRun
    from vortexcfd.gui import mesh_worker
    from vortexcfd.gui.main_window import MainWindow

    FakeRun.instances = []
    monkeypatch.setattr(mesh_worker, "MeshRun", FakeRun)
    project = _two_part_project(tmp_path)
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    try:
        b = w.top_bar.mesh_button
        assert b.isEnabled() and "Part Pod is small relative to the background mesh" in b.toolTip()
        w.tree.setCurrentItem(w._items[("mesh", None)])
        p = w.properties
        assert p.mesh_thin_warning.isVisible() and "Part Pod" in p.mesh_thin_warning.text()
        b.click()
        assert "refinement seeded automatically" in w.console.text()  # logged before meshing
        run = FakeRun.instances[-1]
        run.finish(MeshRunResult(True, False, exit_codes={}, report=_report(["Pod"])))
        assert "ERROR" in w.console.text() and "Part Pod was lost during meshing" in w.console.text()
        badge = w.top_bar.mesh_badge
        assert not badge.isHidden() and badge.text() == "Mesh invalid: Part Pod lost"
        assert badge.dot_color() == w._theme.error
        assert p._rows["mesh_lost"].isVisible() and p.mesh_values["lost"].text() == "Pod"
        assert p.mesh_values["lost"].property("error") == "true"
        assert "Part Pod was lost" in w.statusBar().currentMessage()
        rb = w.top_bar.run_button
        assert not rb.isEnabled() and rb.toolTip().startswith("Part Pod was lost during meshing")
        # per-part levels in the Part properties
        w.tree.setCurrentItem(w._items[("part", 1)])
        spin = p.part_level_fields["surface_level_max"]
        assert p._rows["part_surface_level_max"].isVisible() and spin.text() == "auto"
        spin.setValue(6)
        spin.editingFinished.emit()
        assert w.project.sim.geometry.parts[1].surface_level_max == 6
        assert w.mesh_stale  # part levels are meshing inputs
        spin.setValue(spin.minimum())
        spin.editingFinished.emit()
        assert w.project.sim.geometry.parts[1].surface_level_max is None
    finally:
        w.project.save = lambda *a, **k: None
        w.close()


# -- real snappyHexMesh ----------------------------------------------------------------------------------------


def _real_mesh(tmp_path: Path, pod_levels) -> MeshRunResult:
    from vortexcfd.workflow.meshing import prepare_job

    project = _two_part_project(tmp_path)
    if pod_levels is not None:
        project.update_part(1, surface_level_min=pod_levels[0], surface_level_max=pod_levels[1])
    job = prepare_job(project)
    from vortexcfd.foam.mesh_run import MeshRun

    run = MeshRun(job.case_dir, step_timeout_s=240, parts=job.inputs.parts)
    run.start()
    result = run.wait(600)
    assert result is not None and result.success, result
    return result


@pytest.mark.slow
def test_real_reproduced_case_meshes_both_parts_with_default_settings(tmp_path: Path) -> None:
    """The item 54 reproduction with DEFAULT settings: the Pod is seeded automatically and kept."""
    from vortexcfd.foam.postprocessing import patch_face_counts

    result = _real_mesh(tmp_path, None)
    report = result.report
    counts = patch_face_counts(result.log_dir.parent)
    print(f"\ndefault settings: {report.summary()}; faces Ball {counts['Ball']}, Pod {counts['Pod']}")
    assert (result.log_dir.parent / "constant" / "triSurface" / "Pod_seed.eMesh").is_file()
    assert report.mesh_ok and report.lost_parts == () and report.valid and counts["Pod"] > 500


@pytest.mark.slow
def test_real_part_level_override_meshes_the_small_part(tmp_path: Path) -> None:
    from vortexcfd.foam.postprocessing import patch_face_counts

    result = _real_mesh(tmp_path, (4, 5))
    report = result.report
    counts = patch_face_counts(result.log_dir.parent)
    print(f"\nwith Pod levels (4 5): {report.summary()}; faces Ball {counts['Ball']}, Pod {counts['Pod']}")
    assert (result.log_dir.parent / "constant" / "triSurface" / "Pod_seed.eMesh").is_file()
    assert report.lost_parts == () and report.valid and counts["Pod"] > 500
