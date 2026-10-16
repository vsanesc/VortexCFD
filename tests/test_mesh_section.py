"""Section plane through the volume mesh in the Mesh Scene."""

from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

from vortexcfd.gui.scene import MeshView
from vortexcfd.gui.theme import DARK, SECTION_EPS_FRACTION

SPHERE = pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24)


pytestmark = pytest.mark.slow  # the shared session mesh takes ~25 s to build


@pytest.fixture
def case_dir(sphere_mesh) -> Path:
    """The shared session mesh (read only: these tests only slice it in memory)."""
    return sphere_mesh.case_dir


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


def test_walls_use_part_surface_and_the_section_uses_the_mesh_tokens(view: MeshView) -> None:
    assert pv.Color(view.actors[0].prop.color).hex_rgb.lower() == DARK.part_surface.lower()
    assert pv.Color(view.section_actor.prop.color).hex_rgb.lower() == DARK.mesh_surface.lower()
    assert view.section_actor.prop.show_edges
    assert pv.Color(view.section_actor.prop.edge_color).hex_rgb.lower() == DARK.mesh_edge.lower()


def test_dragging_the_slider_slices_a_handful_of_times_plus_one_final(sphere_mesh, qtbot) -> None:
    from tests.fakes import FakeDialogs
    from vortexcfd.core.project import Project
    from vortexcfd.gui.main_window import MainWindow
    from vortexcfd.gui.theme import SECTION_PREVIEW_MS, SECTION_SLIDER_STEPS

    w = MainWindow(Project.new("slider"), FakeDialogs(), with_viewer=True)
    qtbot.addWidget(w)
    w.show()
    try:
        assert w.mesh_view.load(sphere_mesh.case_dir, ("Sphere",))
        w._set_scene_mode("mesh")
        assert w.section_slider.isVisible()
        calls = []
        original = w.mesh_view.set_section
        w.mesh_view.set_section = lambda **kw: (calls.append(kw), original(**kw))[1]
        slider = w.section_slider
        slider.setSliderDown(True)  # start dragging
        for i in range(50):  # 50 positions in far less than 150 ms
            slider.setValue(100 + 10 * i)
        during = len(calls)
        assert 1 <= during <= 3, during  # the first preview, at most a couple more
        slider.setSliderDown(False)  # release: one final slice at the last position
        assert len(calls) <= during + 1 and len(calls) <= 4
        lo, hi = w.mesh_view.volume_bounds()[2:4]
        expected = lo + (100 + 10 * 49) / SECTION_SLIDER_STEPS * (hi - lo)
        assert w.mesh_view.section_position == pytest.approx(expected)
        qtbot.wait(2 * SECTION_PREVIEW_MS)
        assert len(calls) <= 4  # nothing slices after the release (no stale pending preview)
        assert w.mesh_view.section_position == pytest.approx(expected)
        # Without dragging (keyboard, programmatic) each change slices immediately.
        before = len(calls)
        slider.setValue(300)
        assert len(calls) == before + 1
    finally:
        w.project.save = lambda *a, **k: None
        w.close()


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
