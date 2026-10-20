"""Surface preparation (D-093) on small synthetic multi-component shapes: diagnostics, intersection
curves, the CAD union with per-source regions, the fallback, undo / redo, the meshing case, schema
v11 and the GUI operation. No OpenFOAM run."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Part, Simulation
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import load_simulation, migrate
from vortexcfd.geometry import surface_prep as geo
from vortexcfd.geometry.cad import FACE_ARRAY, read_cad
from vortexcfd.geometry.cad_union import ComponentSource, union_components
from vortexcfd.workflow import meshing, part_ops, surface_prep

DATA = Path(__file__).parent / "data"


# -- synthetic shapes ---------------------------------------------------------------------------


def _step(path: Path, shape) -> Path:
    from vortexcfd.bench.geometries import _write_step

    return _write_step(shape, path)


def _box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def _loose_faces(shape, drop: int | None = None):
    """The faces of ``shape`` as a compound of unsewn faces (``drop``: leave that face out)."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.TopoDS import TopoDS_Compound

    from vortexcfd.geometry.cad import _unique_faces

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for k, face in enumerate(_unique_faces(shape)):
        if k != drop:
            builder.Add(compound, BRepBuilderAPI_Copy(face).Shape())  # its own edges: unsewn
    return compound


@pytest.fixture(scope="module")
def shapes(tmp_path_factory) -> dict[str, Path]:
    """Millimetre STEP files: a body box 2 x 1 x 1 m (a solid), a wing box through it as loose
    unsewn faces (an untrimmed component), and an open box (one face missing: cannot be sewn closed)."""
    folder = tmp_path_factory.mktemp("shapes")
    return {
        "body": _step(folder / "body.step", _box(0, -500, -500, 2000, 500, 500)),
        "wing": _step(folder / "wing.step", _loose_faces(_box(700, -1500, -100, 1300, 1500, 100))),
        "open": _step(folder / "open.step", _loose_faces(_box(1500, -200, 400, 1800, 200, 700), drop=0)),
    }


def _project(tmp_path: Path, shapes: dict[str, Path], names=("body", "wing"), stl: dict | None = None) -> Project:
    project = Project.create(tmp_path, "prep")
    project.update_reports(reference_length=0.6)
    for name in names:
        dest = project.folder / "geometry" / shapes[name].name
        shutil.copy2(shapes[name], dest)
        for part in part_ops.cad_parts(project.folder, dest, None, "regions", {p.name for p in project.sim.geometry.parts}):
            project.add_part(part.model_copy(update={"name": name}))
    for name, mesh in (stl or {}).items():
        path = project.folder / "geometry" / f"{name}.stl"
        mesh.save(str(path))
        project.add_part(Part(name=name, source_file=f"geometry/{name}.stl", units="m"))
    project.save()
    return project


def _mesh(project: Project, name: str) -> pv.PolyData:
    part = next(p for p in project.sim.geometry.parts if p.name == name)
    return part_ops.part_mesh(project, part)


# -- diagnostics and curves ----------------------------------------------------------------------


def test_intersection_curves_of_crossing_boxes_and_the_edge_mesh(tmp_path: Path) -> None:
    body = pv.Box(bounds=(0, 2, 0, 1, 0, 1)).triangulate().clean()
    tube = pv.Cylinder(center=(2.0, 0.5, 0.5), direction=(1, 0, 0), radius=0.2, height=1.0, resolution=90).triangulate().clean()
    curves = geo.intersection_curves([body, tube])
    assert set(curves.pair_lengths()) == {(0, 1)}
    # the cylinder pierces the x = 2 face: a circle of radius 0.2 (the polygon's perimeter)
    assert curves.length() == pytest.approx(2 * 90 * 0.2 * np.sin(np.pi / 90), rel=1e-6)
    path = tmp_path / "j.eMesh"
    edges = geo.write_edge_mesh(path, curves.segments, "test")
    points, read = geo.read_edge_mesh(path)
    assert edges == len(read) == len(points)  # one closed loop: as many points as edges
    assert (np.bincount(read.ravel()) == 2).all()
    assert "featureEdgeMesh" in path.read_text()


def test_curves_inside_a_third_component_are_dropped() -> None:
    hull = pv.Box(bounds=(0, 4, -1, 1, -1, 1)).triangulate().clean()
    a = pv.Box(bounds=(1, 2, -0.5, 0.5, -0.2, 0.2)).triangulate().clean()  # entirely inside the hull
    b = pv.Box(bounds=(1.5, 2.5, -0.1, 0.1, -0.5, 0.5)).triangulate().clean()  # crosses a, inside the hull
    c = pv.Box(bounds=(3.5, 5, -0.3, 0.3, -0.3, 0.3)).triangulate().clean()  # crosses the hull's end
    kept = geo.intersection_curves([hull, a, b, c])
    every = geo.intersection_curves([hull, a, b, c], drop_hidden=False)
    assert set(every.pair_lengths()) == {(1, 2), (0, 3)}
    assert set(kept.pair_lengths()) == {(0, 3)}
    assert kept.length() == pytest.approx(4 * 0.6)


def test_diagnostics_closed_pairs_gaps_and_thin_parts(tmp_path: Path, shapes) -> None:
    gap = pv.Box(bounds=(5, 6, 0, 1, 0, 1)).triangulate().clean()
    tris = geo.triangles(gap)
    centres = gap.points[tris].mean(axis=1)
    keep = ~np.isclose(centres[:, 0], 6.0)  # the x = 6 face replaced by one 2 mm smaller on each side
    lid = pv.Plane(center=(6, 0.5, 0.5), direction=(1, 0, 0), i_size=0.996, j_size=0.996).triangulate()
    cracked = pv.merge([pv.PolyData(gap.points, np.hstack([np.full((keep.sum(), 1), 3), tris[keep]]).ravel()), lid])
    project = _project(tmp_path, shapes, ("body", "wing"), stl={"cracked": cracked})
    meshes = [_mesh(project, n) for n in ("body", "wing", "cracked")]
    d = geo.diagnose(["body", "wing", "cracked"], meshes, cell_size=0.25,
                     sewing={"body": (True, 0), "wing": (True, 0)})
    body, wing, cracked = d.components
    assert body.closed and wing.closed  # the loose faces share their edges' tessellation
    assert not cracked.closed and cracked.open_edges > 0 and cracked.open_loops == 2
    assert cracked.gaps and min(cracked.gaps) == pytest.approx(0.002, rel=1e-3)  # two loops 2 mm apart
    assert max(cracked.gaps) < 0.003  # seen from the hole's four corners: the diagonal
    assert [(a, b) for a, b, _l, _o in d.intersecting] == [("body", "wing")]
    _a, _b, length, outer = d.intersecting[0]
    assert length == pytest.approx(2 * 2 * (0.6 + 0.2), rel=1e-6) and outer == pytest.approx(length)
    # the wing is 0.2 m thick (< the 0.25 m cell) over its upper and lower faces; the body is not thin
    assert wing.thin_area_fraction > 0.5 and wing.min_thickness == pytest.approx(0.2, rel=1e-3)
    assert body.thin_area_fraction == 0.0
    rows = dict(d.rows())
    assert rows["Surface cell size"] == "250 mm" and "body / wing" in rows["Intersecting pairs"]
    assert "cracked: gaps below the cell size" in rows


# -- the CAD union --------------------------------------------------------------------------------


def test_union_is_closed_and_keeps_every_face_with_its_source(shapes) -> None:
    body, wing = read_cad(shapes["body"]), read_cad(shapes["wing"])
    result = union_components([ComponentSource("body", shapes["body"], None), ComponentSource("wing", shapes["wing"], None)],
                              linear_deflection=0.005, angular_deflection_deg=20)
    assert result.failed == {} and set(result.meshes) == {"body", "wing"}
    assert result.closed_after_sewing == {"body": True, "wing": True}
    assert result.open_edges == 0 and result.non_manifold_edges == 0 and result.watertight
    assert result.volume == pytest.approx(2.0 + 2 * 1.0 * 0.6 * 0.2, rel=1e-9)  # body + the wing outside it
    whole = pv.merge(list(result.meshes.values())).clean(tolerance=0.0)
    assert whole.volume == pytest.approx(result.volume, rel=1e-6)
    for name, model in (("body", body), ("wing", wing)):
        ids = set(np.unique(result.meshes[name].cell_data[FACE_ARRAY]).tolist())
        assert ids <= set(range(len(model.faces)))  # every triangle keeps a face of its own source
    # the wing's root faces (inside the body) are gone; its four long faces and two tips remain
    assert len(np.unique(result.meshes["wing"].cell_data[FACE_ARRAY])) == 6
    assert result.meshes["wing"].area == pytest.approx(2 * (2 * 0.6 * 1.0 + 2 * 0.2 * 1.0) + 2 * 0.6 * 0.2, rel=1e-6)


def test_prepare_cad_union_writes_per_part_surfaces_and_regions(tmp_path: Path, shapes) -> None:
    project = _project(tmp_path, shapes)
    prep = surface_prep.prepare(project, "cad_union", cell_size=0.05)
    assert [(p.part, p.strategy, p.note) for p in prep.parts] == [("body", "cad_union", None), ("wing", "cad_union", None)]
    assert prep.features_file is None
    project.set_surface_prep(prep)
    assert surface_prep.state(project) == "current"
    # D-101 rejected: the union's junctions are only its parts' open edges in their own feature files,
    # at the parts' surface level; no junction-level feature file reaches the meshing case
    job = meshing.prepare_job(project)
    assert job.inputs.extra_features == ()
    assert not (job.case_dir / "constant" / "triSurface" / surface_prep.JUNCTION_FILE).exists()
    assert surface_prep.JUNCTION_FILE not in (job.case_dir / "system" / "snappyHexMeshDict").read_text()
    for entry in prep.parts:
        mesh, ids_file = surface_prep.prepared_surface(project, next(p for p in project.sim.geometry.parts
                                                                       if p.name == entry.part), prep)
        ids = surface_prep.base_ids(project, project.sim.geometry.parts[0 if entry.part == "body" else 1], mesh, prep)
        assert ids_file == entry.region_ids and len(ids) == mesh.n_cells
    rows = dict(prep.report)
    assert rows["Union"].startswith("2 of 2 parts") and "closed" in rows["Union"] and "not closed" not in rows["Union"]
    assert rows["wing: strategy"] == "CAD union"


def test_fallback_for_a_part_that_cannot_be_sewn_or_is_not_cad(tmp_path: Path, shapes) -> None:
    pod = pv.Sphere(radius=0.2, center=(1.9, 0.0, 0.0)).triangulate()  # an STL part crossing the body's end
    project = _project(tmp_path, shapes, ("body", "wing", "open"), stl={"pod": pod})
    prep = surface_prep.prepare(project, "cad_union", cell_size=0.05)
    by = {p.part: p for p in prep.parts}
    assert by["body"].strategy == by["wing"].strategy == "cad_union"
    assert by["open"].strategy == "intersection_features" and "not closed after sewing" in by["open"].note
    assert by["pod"].strategy == "intersection_features" and by["pod"].note.endswith("not a CAD part")
    assert by["open"].surface_file is None and by["pod"].surface_file is None
    # the fallback parts' curves with the union's shares and with each other go to the features
    points, edges = geo.read_edge_mesh(project.folder / prep.features_file)
    assert len(edges) > 0 and np.isclose(points[:, 0].max(), 2.0, atol=0.21)
    report = dict(prep.report)
    assert "Union: open" in report and "Intersection curves (fallback parts)" in report


def test_intersection_features_mesh_case_and_hash(tmp_path: Path, shapes) -> None:
    project = _project(tmp_path, shapes)
    before = meshing.inputs_hash(project)
    prep = surface_prep.prepare(project, "intersection_features")
    project.set_surface_prep(prep)
    assert all(p.strategy == "intersection_features" and p.surface_file is None for p in prep.parts)
    assert meshing.inputs_hash(project) != before
    job = meshing.prepare_job(project)
    level = meshing.junction_level(project, job.box, meshing.surface_length(project, job.box).value)
    assert job.inputs.extra_features == ((surface_prep.JUNCTION_FILE, level),)
    # the finest level the surfaces reach: the maximum surface level plus the curvature levels (D-097)
    est = meshing.project_estimate(project, job.box)
    assert level == est.level_max + project.sim.mesh.curvature_levels == est.curvature_level
    assert f'{{file "{surface_prep.JUNCTION_FILE}"; level {level};}}' in (job.case_dir / "system" / "snappyHexMeshDict").read_text()
    copied = job.case_dir / "constant" / "triSurface" / surface_prep.JUNCTION_FILE
    assert copied.read_bytes() == (project.folder / prep.features_file).read_bytes()
    # OpenFOAM reads the header's object entry as a word: the name the file has in the case
    assert f"    object      {surface_prep.JUNCTION_FILE};\n" in copied.read_text()
    assert f'"{surface_prep.JUNCTION_FILE}"' in (job.case_dir / "system" / "snappyHexMeshDict").read_text()
    # the per-part force groups and patches stay one per component
    assert job.inputs.patches == ("body", "wing")
    project.set_surface_prep(None)
    job = meshing.prepare_job(project)
    assert job.inputs.extra_features == () and not copied.exists()
    assert meshing.inputs_hash(project) == before


def test_undo_redo_and_a_stale_result_blocks_meshing(tmp_path: Path, shapes) -> None:
    project = _project(tmp_path, shapes)
    prep = surface_prep.prepare(project, "cad_union")
    project.set_surface_prep(prep)
    assert project.undo_label == "Surface preparation (cad_union)"
    union_bounds = meshing.parts_layout(project)[2]
    project.undo()
    assert project.sim.surface_prep is None and surface_prep.state(project) == "none"
    project.redo()
    assert project.sim.surface_prep == prep and surface_prep.state(project) == "current"
    assert meshing.parts_layout(project)[2] == pytest.approx(union_bounds)
    # files the result references count as the project's geometry (Save As copies them)
    assert set(f for p in prep.parts for f in (p.surface_file, p.region_ids)) <= set(project.referenced_files())
    project.update_part(1, units="cm")  # the parts changed after the preparation
    assert surface_prep.state(project) == "stale"
    assert meshing.readiness(project) == surface_prep.STALE_MESSAGE
    project.set_surface_prep(None)
    assert project.undo_label == "Remove surface preparation"


@pytest.mark.parametrize("strategy", ["intersection_features", "cad_union"])
def test_a_single_part_is_not_changed_by_either_strategy(tmp_path: Path, shapes, strategy: str) -> None:
    """Surface preparation must not change single-component geometry: the meshing case of a prepared
    one-part project is the unprepared one."""
    project = _project(tmp_path, shapes, ("body",))
    job = meshing.prepare_job(project)
    files = {f: (job.case_dir / f).read_bytes() for f in ("system/snappyHexMeshDict", "constant/triSurface/body.stl")}
    prep = surface_prep.prepare(project, strategy)
    assert prep.features_file is None and all(p.surface_file is None for p in prep.parts)
    project.set_surface_prep(prep)
    job = meshing.prepare_job(project)
    assert {f: (job.case_dir / f).read_bytes() for f in files} == files
    if strategy == "cad_union":
        assert prep.parts[0].note == "crosses no other part: its own surface, unchanged"


# -- schema v11 -----------------------------------------------------------------------------------


def test_v10_project_migrates_without_a_preparation() -> None:
    stored = json.loads((DATA / "project_v10.json").read_text())
    assert stored["schema_version"] == 10 and "surface_prep" not in stored
    sim = load_simulation(DATA / "project_v10.json")
    assert sim.schema_version == CURRENT_SCHEMA_VERSION  # v12 (D-103) added nothing to fill
    assert sim.surface_prep is None and [p.name for p in sim.geometry.parts] == ["Fuselage", "Wing"]
    assert sim.mesh.target_yplus == 50.0 and sim.reports.reference_length == 1.5 and sim.inflow.speed == 30.0
    assert migrate({"schema_version": 10, "x": 1}) == {"schema_version": CURRENT_SCHEMA_VERSION, "x": 1,
                                                       "mesh": {"layer_controls": "legacy",  # v13 (D-106)
                                                                "yplus_at": "cell_height"}}  # v14 (D-107)


def test_prepared_project_round_trip(tmp_path: Path, shapes) -> None:
    project = _project(tmp_path, shapes)
    project.set_surface_prep(surface_prep.prepare(project, "intersection_features"))
    project.save()
    again = Project.open(project.path)
    assert again.sim.surface_prep == project.sim.surface_prep and surface_prep.state(again) == "current"
    with pytest.raises(ValueError):
        Simulation.model_validate({**project.sim.model_dump(), "surface_prep": {"strategy": "magic", "inputs_hash": ""}})


# -- GUI -----------------------------------------------------------------------------------------


def test_gui_prepares_shows_the_report_and_removes(qtbot, tmp_path: Path, shapes) -> None:
    from tests.fakes import FakeDialogs
    from vortexcfd.gui.main_window import MainWindow

    project = _project(tmp_path, shapes)
    dialogs = FakeDialogs()
    window = MainWindow(project, dialogs, with_viewer=False)
    qtbot.addWidget(window)
    window.show()
    try:
        assert window._items[("surface_prep", None)].text(0) == "Surface Preparation (not run)"
        assert ("prepare_surfaces", None) in window._items
        dialogs.surface_prep_strategy = None  # cancelled: nothing runs
        window.act_prepare_surfaces.trigger()
        assert dialogs.surface_prep_asked[-1][1] == surface_prep.DEFAULT_STRATEGY == "cad_union" and not window.geometry_busy
        dialogs.surface_prep_strategy = "cad_union"
        window.act_prepare_surfaces.trigger()
        qtbot.waitUntil(lambda: not window.geometry_busy and not window.geometry_worker.is_running(), timeout=60000)
        assert project.sim.surface_prep is not None and project.sim.surface_prep.strategy == "cad_union"
        assert window._items[("surface_prep", None)].text(0) == "Surface Preparation: CAD union"
        assert window._selection == ("surface_prep", None)
        panel = window.properties
        assert not panel._rows["sp_report"].isHidden() and "Union: 2 of 2 parts" in panel.sp_report.text()
        assert panel.sp_state.text() == "up to date: meshing uses it"
        panel.sp_remove.click()
        assert project.sim.surface_prep is None
        window._undo()
        assert project.sim.surface_prep is not None
    finally:
        window.geometry_worker.wait(60)
        project.save = lambda *a, **k: None
        window.close()


# -- import checks: parts crossing each other (D-099) ---------------------------------------------


def _stl_project(tmp_path: Path) -> Project:
    project = Project.create(tmp_path, "overlap")
    shapes = {"Body": pv.Box(bounds=(0, 2, -0.5, 0.5, -0.5, 0.5)), "Wing": pv.Box(bounds=(0.7, 1.3, -1.5, 1.5, -0.1, 0.1)),
              "Pod": pv.Sphere(radius=0.2, center=(4.0, 0.0, 0.0))}
    for name, mesh in shapes.items():
        mesh.triangulate().clean().save(str(project.folder / "geometry" / f"{name}.stl"))
        project.add_part(Part(name=name, source_file=f"geometry/{name}.stl", units="m"))
    project.save()
    return project


def test_crossing_parts_are_found_and_point_to_surface_preparation(tmp_path: Path) -> None:
    project = _stl_project(tmp_path)
    assert not surface_prep.crossings_known(project) and surface_prep.crossing_parts(project, compute=False) is None
    crossings = surface_prep.crossing_parts(project)
    assert crossings == {"Body": ["Wing"], "Wing": ["Body"], "Pod": []} and surface_prep.crossings_known(project)
    text, warn = surface_prep.crossing_text(project, "Wing", crossings)
    assert warn and text.startswith("Body: the parts overlap") and "Run Surface Preparation" in text
    assert surface_prep.crossing_text(project, "Pod", crossings) == ("none", False)
    project.set_surface_prep(surface_prep.prepare(project, "intersection_features"))
    text, warn = surface_prep.crossing_text(project, "Wing", crossings)
    assert not warn and text == "Body (resolved by the surface preparation, Intersection features)"


def test_the_import_checks_report_overlapping_parts(qtbot, tmp_path: Path) -> None:
    from tests.fakes import FakeDialogs
    from tests.test_import import wait_geometry
    from vortexcfd.gui.main_window import MainWindow

    project = _stl_project(tmp_path)
    window = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(window)
    window.show()
    try:
        window.tree.setCurrentItem(window._items[("part", 1)])  # Wing
        wait_geometry(qtbot, window)
        window.properties.refresh()
        values = window.properties.check_values
        assert values["intersections"].text() == "0 within the part; it crosses other parts (below)"
        assert values["crossings"].text().startswith("Body: the parts overlap")
        assert "Edit > Prepare Surfaces" in values["crossings"].text()
        assert values["crossings"].property("warn") == "true"
        window._announce_overlaps = True  # as after an import: the console warning
        window._on_overlaps_checked(surface_prep.geometry_hash(project))
        assert "Parts cross each other: Body / Wing" in window.console.text()
    finally:
        window.close()


def test_hidden_segments_skip_the_points_outside_a_component_box_without_changing_the_mask() -> None:
    """The winding sum is O(points x triangles); a point outside a component's bounding box cannot be
    inside it (|winding| <= 0.5 from outside the convex hull), so it is not summed. Same mask as the
    full sum on the four-box case and on three crossing spheres, and the sum itself behaves as stated."""
    hull = pv.Box(bounds=(0, 4, -1, 1, -1, 1)).triangulate().clean()
    a = pv.Box(bounds=(1, 2, -0.5, 0.5, -0.2, 0.2)).triangulate().clean()
    b = pv.Box(bounds=(1.5, 2.5, -0.1, 0.1, -0.5, 0.5)).triangulate().clean()
    c = pv.Box(bounds=(3.5, 5, -0.3, 0.3, -0.3, 0.3)).triangulate().clean()
    sphere = pv.Sphere(radius=0.5, theta_resolution=60, phi_resolution=60).triangulate().clean()
    spheres = [sphere, sphere.translate((0.6, 0.0, 0.0), inplace=False), sphere.translate((0.0, 0.7, 0.0), inplace=False)]
    for meshes in ([hull, a, b, c], spheres):
        pts, tris, comp = geo.combined(meshes)
        segments, pairs = geo.intersection_segments(pts, tris, comp)
        middle = segments.mean(axis=1)
        fast = geo.hidden_segments(middle, pairs, meshes)
        full = geo.hidden_segments(middle, pairs, meshes, use_bounds=False)
        assert np.array_equal(fast, full) and fast.any() and not fast.all()
    # outside the box or the ball of a closed surface the winding number stays at or below 0.5; inside it is 1
    rng = np.random.default_rng(1)
    outside = rng.uniform(-3, 3, (200, 3))
    outside = outside[~geo._within_hull_container(outside, a)]
    assert len(outside) > 100 and (np.abs(geo.winding_numbers(outside, a)) <= 0.5).all()
    on_sphere = rng.normal(size=(50, 3))
    on_sphere = 0.5 * on_sphere / np.linalg.norm(on_sphere, axis=1)[:, None]  # on the sphere's hull
    assert geo._within_hull_container(on_sphere * 1.001, sphere).sum() == 0
    assert geo._within_hull_container(on_sphere * 0.999, sphere).all()
    assert (np.abs(geo.winding_numbers(np.array([[1.5, 0.0, 0.0]]), a)) > geo.INSIDE_WINDING).all()
    assert geo._within_bounds(np.array([[1.0, -0.5, 0.2], [0.999, 0.0, 0.0]]), a.bounds).tolist() == [True, False]
