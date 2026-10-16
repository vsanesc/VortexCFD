"""Section plane through the volume mesh in the Mesh Scene."""

from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

from vortexcfd.core.model import Domain, Mesh
from vortexcfd.foam.mesh_case import TRI_SURFACE, MeshCaseInput, build_mesh_files, prepare_case_dir, safe_part_names
from vortexcfd.foam.mesh_run import MeshRun
from vortexcfd.geometry.domain import compute_domain
from vortexcfd.gui.scene import MeshView
from vortexcfd.gui.theme import DARK, SECTION_EPS_FRACTION

SPHERE = pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24)


@pytest.fixture(scope="module")
def case_dir(tmp_path_factory) -> Path:
    """A real coarse mesh of a sphere with prism layers (meshed once for the whole module)."""
    case = tmp_path_factory.mktemp("section") / "case"
    box = compute_domain([tuple(SPHERE.bounds)], Domain(upstream=2, downstream=3, lateral=2, vertical=2))
    inp = MeshCaseInput(box.bounds, False, tuple(safe_part_names(["Sphere"])), tuple(SPHERE.bounds),
                        box.reference_length, Mesh(base_size=0.25, surface_level_min=1, surface_level_max=2, layers=2))
    prepare_case_dir(case, build_mesh_files(inp))
    SPHERE.save(str(case / TRI_SURFACE / "Sphere.stl"))
    run = MeshRun(case, step_timeout_s=100)
    run.start()
    result = run.wait(115)
    assert result is not None and result.success
    return case


def make_plotter(qtbot):
    """The same plotter class the app uses (a bare off-screen pv.Plotter segfaults next to Qt
    windows on a real display)."""
    from pyvistaqt import QtInteractor

    plotter = QtInteractor(auto_update=False)
    qtbot.addWidget(plotter)
    return plotter


@pytest.fixture
def view(case_dir: Path, qtbot):
    plotter = make_plotter(qtbot)
    v = MeshView(plotter, DARK)
    assert v.load(case_dir, ("Sphere",))
    yield v
    plotter.close()


def _cell_centers(actor) -> np.ndarray:
    return np.asarray(pv.wrap(actor.GetMapper().GetInput()).cell_centers().points)


def _outside_parts_bbox(points: np.ndarray) -> np.ndarray:
    b = SPHERE.bounds
    inside = ((points[:, 0] >= b[0]) & (points[:, 0] <= b[1]) & (points[:, 1] >= b[2])
              & (points[:, 1] <= b[3]) & (points[:, 2] >= b[4]) & (points[:, 2] <= b[5]))
    return ~inside


def test_default_section_is_a_y_normal_plane_through_the_parts_centre(view: MeshView) -> None:
    assert view.section_enabled and view.section_axis == 1 and view.normal() == (0.0, 1.0, 0.0)
    assert view.has_volume and view.section_actor is not None
    assert view.section_position == pytest.approx(0.0, abs=0.05)  # the sphere is centred on y = 0
    ymin, ymax = view.section_actor.GetBounds()[2:4]
    assert ymin == pytest.approx(ymax, abs=1e-6) and ymin == pytest.approx(view.section_position, abs=1e-6)


def test_section_has_cells_and_they_are_fluid_cells_outside_the_parts_box(view: MeshView) -> None:
    mesh = pv.wrap(view.section_actor.GetMapper().GetInput())
    assert mesh.n_cells > 100
    centers = np.asarray(mesh.cell_centers().points)
    outside = _outside_parts_bbox(centers)
    assert outside.sum() > 0.5 * len(centers)  # most of the cut is background fluid
    # ... and the plane crosses the whole domain, not only the part:
    vol = view.volume_bounds()
    sb = view.section_actor.GetBounds()
    assert sb[0] == pytest.approx(vol[0], abs=1e-6) and sb[1] == pytest.approx(vol[1], abs=1e-6)
    assert sb[4] == pytest.approx(vol[4], abs=1e-6) and sb[5] == pytest.approx(vol[5], abs=1e-6)


def test_section_shows_refinement_and_layers(view: MeshView) -> None:
    """Cells shrink towards the part (background > refined > layer cells)."""
    mesh = pv.wrap(view.section_actor.GetMapper().GetInput())
    sizes = np.sqrt(np.asarray(mesh.compute_cell_sizes(length=False, area=True, volume=False)["Area"]))
    centers = np.asarray(mesh.cell_centers().points)
    distance = np.abs(np.linalg.norm(centers, axis=1) - 0.5)  # distance to the sphere surface
    near, far = sizes[distance < 0.05], sizes[distance > 1.0]
    assert near.size and far.size
    assert far.max() > 2.5 * near.min()  # background cells (0.25) vs refinement/layer cells


def test_section_changes_with_normal_and_offset(view: MeshView) -> None:
    base_bounds = view.section_actor.GetBounds()
    base_cells = pv.wrap(view.section_actor.GetMapper().GetInput()).n_cells
    view.set_section(axis=0)
    assert view.section_axis == 0 and view.normal() == (1.0, 0.0, 0.0)
    xb = view.section_actor.GetBounds()
    assert xb[0] == pytest.approx(xb[1], abs=1e-6)  # a plane normal to x: zero thickness along x
    assert xb != base_bounds
    view.set_section(axis=2)
    zb = view.section_actor.GetBounds()
    assert zb[4] == pytest.approx(zb[5], abs=1e-6)
    view.set_section(axis=1, position=1.0)
    assert view.section_actor.GetBounds()[2] == pytest.approx(1.0, abs=1e-6)
    far_cells = pv.wrap(view.section_actor.GetMapper().GetInput()).n_cells
    assert far_cells != base_cells  # off the part there are no refined cells
    centers = _cell_centers(view.section_actor)
    assert _outside_parts_bbox(centers).all()  # a plane at y = 1 is entirely outside the part


def test_part_walls_are_clipped_behind_the_plane_when_the_section_is_on(view: MeshView) -> None:
    ymin = min(a.GetBounds()[2] for a in view.actors)
    assert ymin >= view.section_position - 1e-6  # only the side behind the plane is kept
    view.set_section(enabled=False)
    assert not view.section_actor.GetVisibility()
    full_ymin = min(a.GetBounds()[2] for a in view.actors)
    assert full_ymin < -0.4  # the whole sphere again
    view.set_section(enabled=True)
    assert view.section_actor.GetVisibility()


def test_walls_use_part_surface_and_the_section_uses_elevated_with_part_edge(view: MeshView) -> None:
    assert pv.Color(view.actors[0].prop.color).hex_rgb.lower() == DARK.part_surface.lower()
    assert pv.Color(view.section_actor.prop.color).hex_rgb.lower() == DARK.elevated.lower()
    assert view.section_actor.prop.show_edges
    assert pv.Color(view.section_actor.prop.edge_color).hex_rgb.lower() == DARK.part_edge.lower()


def test_domain_boundary_patches_are_optional_translucent_faces(view: MeshView) -> None:
    assert len(view.boundary_actors) == 5  # inlet, outlet, sides, top, bottom
    assert all(not a.GetVisibility() for a in view.boundary_actors)  # off by default
    view.set_boundaries(True)
    assert all(a.GetVisibility() and a.prop.opacity < 1.0 for a in view.boundary_actors)
    view.set_visible(False)  # leaving the mesh scene hides everything
    assert not any(a.GetVisibility() for a in (*view.boundary_actors, *view.actors, view.section_actor))


def test_with_symmetry_the_default_plane_is_the_symmetry_plane(case_dir: Path, qtbot) -> None:
    plotter = make_plotter(qtbot)
    try:
        v = MeshView(plotter, DARK)
        v.load(case_dir, ("Sphere",), symmetric=True)
        lo, hi = v.volume_bounds()[2:4]
        assert v.section_position == pytest.approx(lo + SECTION_EPS_FRACTION * (hi - lo))
        assert v.section_actor.GetBounds()[2] > lo  # inside the domain, not on the boundary face
    finally:
        plotter.close()


def test_camera_looks_at_the_plane_from_its_negative_side(view: MeshView) -> None:
    position, focal, up = view.camera_for_section()
    assert position[1] < focal[1] and position[0] == focal[0] and position[2] == focal[2]
    assert up == (0.0, 0.0, 1.0)
    view.set_section(axis=2)
    position, focal, up = view.camera_for_section()
    assert position[2] < focal[2] and up == (0.0, 1.0, 0.0)


def test_clear_removes_every_actor(view: MeshView) -> None:
    view.clear()
    assert view.actors == [] and view.boundary_actors == [] and view.section_actor is None
    assert not view.has_volume and not view.has_mesh
