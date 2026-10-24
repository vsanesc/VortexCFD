"""Surface regions and patch assignment: edits, persistence, meshing dictionaries, a real two-patch
mesh (Task 3.5, D-071)."""

from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

from tests.geometry_corpus import box_faces, write_multi_solid
from tests.test_import import _fresh_cache, make_window  # noqa: F401 (fixtures)
from vortexcfd.core.model import Mesh, Part, SurfaceRegion
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_case import (
    MeshCaseInput,
    part_patch_names,
    snappy_hex_mesh_dict,
    wall_patch_names,
)
from vortexcfd.foam.physics_case import initial_fields
from vortexcfd.geometry import regions
from vortexcfd.geometry.loader import load_surface, stl_solid_names
from vortexcfd.workflow import part_ops
from vortexcfd.workflow.meshing import inputs_hash, prepare_job
from vortexcfd.workflow.solving import solver_input


def _project(tmp_path: Path) -> Project:
    p = Project.new("Patches")
    (tmp_path / "proj" / "geometry").mkdir(parents=True)
    p.save(tmp_path / "proj" / "p.json")
    return p


def _box_part(project: Project, size: float = 1.0, name: str = "Box") -> None:
    cube = pv.Box(bounds=(-size / 2, size / 2) * 3, level=2).triangulate().clean()
    cube.save(str(project.path.parent / "geometry" / f"{name}.stl"))
    project.add_part(Part(name=name, source_file=f"geometry/{name}.stl"))


def test_angle_split_of_a_box_part_gives_six_regions_and_undoes(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _box_part(project)
    project.update_part(0, **part_ops.split_region(project, 0, None, 30.0))
    part = project.sim.geometry.parts[0]
    assert [r.name for r in part.regions] == [f"Box_{k}" for k in range(1, 7)]
    assert all(r.patch is None for r in part.regions) and part.patch_names() == ["Box"]
    mesh = load_surface(project.path.parent / part.source_file, "m")
    ids = regions.read_ids(project.path.parent / part.region_ids, mesh.n_cells)
    assert sorted(np.bincount(ids)[1:].tolist()) == [18] * 6  # base ids 1..6, 18 triangles per side
    project.undo()
    assert project.sim.geometry.parts[0].regions == []


def test_rename_merge_assign_and_split_a_region(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = write_multi_solid(project.path.parent / "geometry" / "box.stl", box_faces(resolution=3))
    project.add_part(part_ops.part_with_solid_regions(project.path.parent, "Box", path, "m", stl_solid_names(path)))
    project.update_part(0, **part_ops.rename_region(project, 0, "xmin", "front"))
    project.update_part(0, **part_ops.merge_regions(project, 0, ["ymin", "ymax", "zmin", "zmax", "xmax"], "body"))
    project.update_part(0, **part_ops.assign_patch(project, 0, ["front"], "inlet_face"))
    part = project.sim.geometry.parts[0]
    assert [(r.name, r.members, r.patch) for r in part.regions] == [("front", [0], "inlet_face"),
                                                                     ("body", [1, 2, 3, 4, 5], None)]
    assert part.patch_names() == ["inlet_face", "Box"]
    with pytest.raises(regions.RegionError, match="at least two"):
        part_ops.merge_regions(project, 0, ["front"])
    # Splitting "body" back by angle gives its five flat sides.
    project.update_part(0, **part_ops.split_region(project, 0, "body", 30.0))
    names = [r.name for r in project.sim.geometry.parts[0].regions]
    assert names == ["front", "body_1", "body_2", "body_3", "body_4", "body_5"]
    with pytest.raises(regions.RegionError, match="no edges sharper"):
        part_ops.split_region(project, 0, "front", 30.0)
    project.update_part(0, **part_ops.patch_per_region(project, 0))
    assert project.sim.geometry.parts[0].patch_names() == names


def test_assignment_is_persisted(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = write_multi_solid(project.path.parent / "geometry" / "box.stl", box_faces())
    project.add_part(part_ops.part_with_solid_regions(project.path.parent, "Box", path, "m", stl_solid_names(path)))
    project.update_part(0, **part_ops.assign_patch(project, 0, ["xmin"], "nose"))
    project.save()
    reopened = Project.open(project.path)
    part = reopened.sim.geometry.parts[0]
    assert part == project.sim.geometry.parts[0]
    assert part.regions[0] == SurfaceRegion(name="xmin", members=[0], patch="nose")
    assert (reopened.path.parent / part.region_ids).is_file()
    assert '"patch": "nose"' in reopened.path.read_text()


def test_patch_names_are_safe_and_unique_across_parts() -> None:
    a = Part(name="Wing", source_file="a.stl", regions=[SurfaceRegion(name="u", members=[0], patch="wall"),
                                                          SurfaceRegion(name="l", members=[1], patch="flap")])
    b = Part(name="Fin", source_file="b.stl", regions=[SurfaceRegion(name="x", members=[0], patch="wall")])
    c = Part(name="my body", source_file="c.stl")
    assert part_patch_names([a, b, c]) == [("wall", "flap"), ("wall_1",), ("my_body",)]
    assert wall_patch_names([a, b, c]) == ("wall", "flap", "wall_1", "my_body")
    assert part_patch_names([c]) == [("my_body",)]  # no regions: exactly as before


def test_snappy_dict_has_one_region_per_patch() -> None:
    inp = MeshCaseInput((-5, 5, -5, 5, -5, 5), False, ("Body", "Ball"), (-1, 1, -1, 1, -1, 1), 2.0, Mesh(layer_sizing="relative"),
                        part_patches=(("nose", "Body"), ("Ball",)))
    assert inp.patches == ("nose", "Body", "Ball") and inp.has_regions(0) and not inp.has_regions(1)
    content = snappy_hex_mesh_dict(inp).content
    assert content["geometry"]["Body.stl"]["regions"] == {"nose": {"name": "nose"}, "Body": {"name": "Body"}}
    assert "regions" not in content["geometry"]["Ball.stl"]
    body = content["castellatedMeshControls"]["refinementSurfaces"]["Body"]
    assert set(body["regions"]) == {"nose", "Body"}
    assert body["regions"]["nose"]["patchInfo"] == {"type": "wall", "inGroups": ["BodyGroup"]}
    assert "regions" not in content["castellatedMeshControls"]["refinementSurfaces"]["Ball"]
    layers = content["addLayersControls"]["layers"]
    assert set(layers) == {"nose", "Body", '"Ball.*"'}


def test_case_surfaces_bcs_and_hash_follow_the_patches(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _box_part(project)
    before = inputs_hash(project)
    project.update_part(0, **part_ops.split_region(project, 0, None, 30.0))
    assert inputs_hash(project) != before  # regions are meshing inputs
    names = [r.name for r in project.sim.geometry.parts[0].regions]
    project.update_part(0, **part_ops.assign_patch(project, 0, names[:1], "front"))
    job = prepare_job(project)
    assert job.inputs.part_patches == (("front", "Box"),) and job.inputs.patches == ("front", "Box")
    stl = job.case_dir / "constant" / "triSurface" / "Box.stl"
    assert stl_solid_names(stl) == ["front", "Box"]
    labels = np.asarray(load_surface(stl, "m").cell_data["solid"])
    assert np.bincount(labels).tolist() == [18, 90]
    fields = initial_fields(solver_input(project))
    assert fields["0/U"].content["boundaryField"]["front"] == {"type": "noSlip"}
    assert fields["0/U"].content["boundaryField"]["Box"] == {"type": "noSlip"}
    assert fields["0/nut"].content["boundaryField"]["front"]["type"] == "nutUSpaldingWallFunction"


def test_an_unassigned_project_hashes_as_before(tmp_path: Path) -> None:
    """Parts without regions keep the pre-v8 inputs hash, and a project with the v9 mesh behaviour the
    pre-v10 hash, so existing meshes stay up to date."""
    import hashlib
    import json

    from vortexcfd.workflow.meshing import _hash_file

    from vortexcfd.core.project_io import V9_MESH_BEHAVIOUR, V10_MESH_FIELDS, V13_MESH_FIELDS, V14_MESH_FIELDS

    project = _project(tmp_path)
    _box_part(project)
    project.update_mesh(**V9_MESH_BEHAVIOUR)  # a project made before v10 (D-085, D-086)
    part = project.sim.geometry.parts[0]
    mesh = {k: v for k, v in project.sim.mesh.model_dump().items()
            if k not in V10_MESH_FIELDS and k not in V13_MESH_FIELDS and k not in V14_MESH_FIELDS
            and k != "cores"}  # the v9 fields (the v15 meshing cores are never hashed, D-111)
    payload = {
        "parts": [[part.name, part.units, _hash_file(project.resolve_part_path(part)), None, None]],
        "domain": project.sim.domain.model_dump(exclude={"ground", "boundary_types", "units", "wall_layers"}),  # pre-v16
        "mesh": mesh, "yplus_inputs": None,
    }
    assert inputs_hash(project) == hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# -- GUI ------------------------------------------------------------------------------------------


def test_regions_list_selection_highlight_and_picking(make_window, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    path = write_multi_solid(tmp_path / "src" / "box.stl", box_faces())
    w = make_window(import_path=path)
    w.act_import.trigger()
    p = w.properties
    items = [p.region_list.item(i).text() for i in range(p.region_list.count())]
    assert items[0] == "xmin  →  box" and len(items) == 6
    p.select_regions(["xmin", "zmax"])
    assert w.scene.region_actor is not None and w.scene.region_actor.mapper.dataset.n_cells == 16
    # Assign the selection to a patch through the Patch field (one undo step).
    p.region_patch.setText("ends")
    p.region_patch.editingFinished.emit()
    part = w.project.sim.geometry.parts[0]
    assert [r.patch for r in part.regions] == ["ends", None, None, None, None, "ends"]
    assert w.project.undo_label == "Edit part 'box' (regions)"
    assert p.patch_label.text() == "ends, box"
    assert set(p.selected_regions()) == {"xmin", "zmax"}
    # Picking a triangle of the selected part selects its region.
    ids = part_ops.part_base_ids(w.project, part)
    w._on_triangle_pick(0, int(np.flatnonzero(ids == 2)[0]))
    assert p.selected_regions() == ["ymin"]
    # Merge two regions with the button.
    p.select_regions(["ymin", "ymax"])
    p.region_merge.click()
    assert [r.name for r in w.project.sim.geometry.parts[0].regions] == ["xmin", "xmax", "ymin", "zmin", "zmax"]
    # Selecting another node clears the highlight.
    p.select_regions(["xmin"])
    assert w.scene.region_actor is not None
    w.tree.setCurrentItem(w._items[("fluid_domain", None)])
    assert w.scene.region_actor is None


def test_split_button_on_a_plain_part(make_window, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    pv.Box(level=1).triangulate().clean().save(str(tmp_path / "src" / "cube.stl"))
    w = make_window(import_path=tmp_path / "src" / "cube.stl")
    w.act_import.trigger()
    p = w.properties
    assert p.region_list.count() == 1 and p.region_split.isEnabled()
    p.region_angle.setValue(45.0)
    p.region_split.click()
    assert len(w.project.sim.geometry.parts[0].regions) == 6
    assert p.region_list.count() == 6


# -- real snappyHexMesh --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def two_patch_mesh(tmp_path_factory):
    """A real coarse mesh (no layers) of a 1 m cube whose -x side is the patch "front" and the
    other five sides "body", plus a second part "Ball" (sphere r 0.3 m at x = 2 m). Built once."""
    from vortexcfd.foam.mesh_run import MeshRun

    project = _project(tmp_path_factory.mktemp("two_patch"))
    _box_part(project, name="Cube")
    sphere = pv.Sphere(radius=0.3, center=(2.0, 0, 0), theta_resolution=24, phi_resolution=24)
    sphere.save(str(project.path.parent / "geometry" / "Ball.stl"))
    project.add_part(Part(name="Ball", source_file="geometry/Ball.stl"))
    project.update_mesh(background_cells_target=20_000, target_surface_size=0.05, layers=0,
                        layer_sizing="relative")  # no layers (D-086: absolute sizing ignores the count)
    project.update_part(0, **part_ops.split_region(project, 0, None, 30.0))
    part = project.sim.geometry.parts[0]
    mesh = load_surface(project.path.parent / part.source_file, "m")
    ids = regions.base_ids(part, mesh, project.path.parent)
    centres = mesh.cell_centers().points
    front = [r.name for r in part.regions if set(r.members) == set(ids[centres[:, 0] < -0.49])]
    project.update_part(0, **part_ops.assign_patch(project, 0, front, "front"))
    project.update_part(0, **part_ops.assign_patch(
        project, 0, [r.name for r in project.sim.geometry.parts[0].regions if r.name not in front], "body"))
    project.save()
    job = prepare_job(project)
    run = MeshRun(job.case_dir, step_timeout_s=240, parts=job.inputs.patches)
    run.start()
    result = run.wait(280)
    assert result is not None and result.success, result
    return project, job, result


@pytest.mark.slow
def test_real_two_patch_part_meshes_both_patches(two_patch_mesh) -> None:
    """Both patches of the cube exist in constant/polyMesh/boundary with faces."""
    from vortexcfd.foam.postprocessing import patch_face_counts

    _project_, job, result = two_patch_mesh
    assert job.inputs.patches == ("front", "body", "Ball")
    counts = patch_face_counts(job.case_dir)
    boundary = (job.case_dir / "constant" / "polyMesh" / "boundary").read_text()
    print(f"\ntwo-patch mesh: {result.report.summary()}; faces front {counts['front']}, body {counts['body']}, "
          f"Ball {counts['Ball']}")
    for name in ("front", "body"):
        start = boundary.index(f"    {name}\n")
        print(boundary[start:boundary.index("}", start) + 1])
    assert result.report.lost_parts == () and counts["front"] > 0 and counts["body"] > 0
    assert counts["body"] > 3 * counts["front"]
    assert "Cube" not in counts  # every triangle went to an assigned patch


@pytest.mark.slow
def test_real_per_part_forces_cover_all_patches(two_patch_mesh) -> None:
    """[NUMERICS-REVIEW] After a short real run the cube's per-part force is the sum of its patches'
    forces, and the all-walls total is the sum over the parts."""
    from tests.real_cases import run_solver
    from vortexcfd.foam.forces import parse_vector_row
    from vortexcfd.foam.postprocessing import output_file
    from vortexcfd.workflow.solving import prepare_solver_case

    project, job, _result = two_patch_mesh
    project.update_solver(iterations=5)
    case = prepare_solver_case(project)
    control = (case / "system" / "controlDict").read_text()
    for name in ("forces_Cube", "forces_front", "forces_body", "forces_Ball", "forceCoeffs_Cube"):
        assert name in control
    run = run_solver(case, timeout_s=120)
    assert run is not None and run.exit_code == 0 and run.iterations == 5, run

    def last(function: str) -> np.ndarray:
        path = output_file(case, function, "force.dat")
        rows = [r for r in (parse_vector_row(line) for line in path.read_text().splitlines()
                            if not line.startswith("#")) if r is not None]
        return np.array(rows[-1][1])  # (total, pressure, viscous) x (x, y, z)

    cube, front, body, ball, total = (last(f) for f in ("forces_Cube", "forces_front", "forces_body",
                                                         "forces_Ball", "forces1"))
    print(f"\nforces at iteration 5 (N, total x y z): Cube {cube[0]}, front {front[0]}, body {body[0]}, "
          f"front + body {front[0] + body[0]}, Ball {ball[0]}, all walls {total[0]}, Cube + Ball {cube[0] + ball[0]}")
    scale = np.abs(total).max()
    assert np.allclose(cube, front + body, rtol=1e-5, atol=1e-6 * scale)
    assert np.allclose(total, cube + ball, rtol=1e-5, atol=1e-6 * scale)
    assert np.abs(front[0]).max() > 0 and np.abs(body[0]).max() > 0


def test_per_part_force_objects_cover_all_patches() -> None:
    """[NUMERICS-REVIEW] A part with several patches gets forces_<part> / forceCoeffs_<part> over all
    of them, next to the per-patch objects; a one-patch part keeps its single per-patch object."""
    from vortexcfd.core.model import Inflow, Physics, Solvers
    from vortexcfd.foam.mesh_case import force_report_keys, part_force_groups
    from vortexcfd.foam.physics_case import SolverCaseInput, control_dict

    cube = Part(name="Cube", source_file="c.stl", regions=[SurfaceRegion(name="a", members=[0], patch="front"),
                                                            SurfaceRegion(name="b", members=[1], patch="body")])
    ball = Part(name="Ball", source_file="b.stl")
    groups = part_force_groups([cube, ball])
    assert groups == (("Cube", ("front", "body")),)
    assert force_report_keys([cube, ball]) == ("front", "body", "Ball", "Cube")
    inp = SolverCaseInput(Physics(), Inflow(), Solvers(), ("front", "body", "Ball"), (-1, 1, -1, 1, -1, 1),
                          part_groups=groups)
    functions = control_dict(inp).content["functions"]
    assert functions["forces_Cube"]["patches"] == ["front", "body"]
    assert functions["forceCoeffs_Cube"]["patches"] == ["front", "body"]
    assert functions["forces_front"]["patches"] == ["front"] and functions["forces_Ball"]["patches"] == ["Ball"]
    assert functions["forces1"]["patches"] == ["front", "body", "Ball"]
    # A part whose name is also a patch name keeps no separate group (the patch keeps the key).
    clash = Part(name="front", source_file="f.stl", regions=[SurfaceRegion(name="x", members=[0], patch="p"),
                                                             SurfaceRegion(name="y", members=[1], patch="q")])
    assert part_force_groups([cube, clash]) == (("Cube", ("front", "body")),)
