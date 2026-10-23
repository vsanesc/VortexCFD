"""The 2D view convention (D-140): a 2D x-z case is shown looking along +y with +z up, so the free stream (+x) runs
left to right, in the geometry, mesh and results scenes, and the exported image keeps it (offscreen)."""

import numpy as np
import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.test_domain_operations import _fresh_cache, make_window  # noqa: F401 (fixtures)
from tests.test_scene_objects import results_window  # noqa: F401 (fixture)
from vortexcfd.core.presets import BUILTIN_PRESETS
from vortexcfd.gui.image_export import render_image

TWO_D = next(p for p in BUILTIN_PRESETS if p.name == "2D airfoil")


def _direction(w) -> tuple[np.ndarray, np.ndarray]:
    cam = w.viewer.camera
    look = np.subtract(cam.focal_point, cam.position)
    return look / np.linalg.norm(look), np.asarray(cam.up)


def _looks_along_plus_y(w) -> bool:
    look, up = _direction(w)
    return np.allclose(look, (0, 1, 0), atol=1e-6) and np.allclose(up, (0, 0, 1), atol=1e-6)


def _marker_x(w, bounds) -> float:
    """Where a red marker at the scene's +x end lands in an exported image, as a fraction of the width."""
    centre = [(bounds[2 * i] + bounds[2 * i + 1]) / 2 for i in range(3)]
    radius = 0.05 * max(bounds[1] - bounds[0], 1e-9)
    w.viewer.add_mesh(pv.Sphere(radius=radius, center=(bounds[1], centre[1], centre[2])), color="red",
                      lighting=False, name="marker", render=False)
    try:
        pixels = render_image(w.viewer, (400, 200)).pixels
    finally:
        w.viewer.remove_actor("marker", render=False)
    red = (pixels[..., 0] > 200) & (pixels[..., 1] < 60) & (pixels[..., 2] < 60)
    assert red.any()
    return float(np.nonzero(red)[1].mean()) / pixels.shape[1]


def test_a_2d_geometry_is_shown_looking_along_plus_y(make_window) -> None:
    w = make_window(TWO_D, with_viewer=True)
    assert w.project.sim.dimension == "2d" and w._scene_mode == "geometry"
    assert _looks_along_plus_y(w) and w.current_view == "XZ"
    assert _marker_x(w, w.scene.visible_bounds()) > 0.5  # +x on the right in the exported image
    w.viewer.view_xz(negative=True, render=False, bounds=w.scene.visible_bounds())  # the mirrored view: told apart
    assert _marker_x(w, w.scene.visible_bounds()) < 0.5


def test_3d_keeps_its_view_and_switching_to_2d_applies_the_2d_view(make_window) -> None:
    w = make_window(BUILTIN_PRESETS[1], with_viewer=True)
    assert w.project.sim.dimension == "3d" and not _looks_along_plus_y(w)
    w.project.set_dimension("2d")
    assert _looks_along_plus_y(w)
    w.viewer.view_isometric(render=False)  # the user's own view is kept on later edits
    w.project.set_dimension("2d")
    assert not _looks_along_plus_y(w)


def test_2d_results_are_shown_and_exported_looking_along_plus_y(results_window, qtbot: QtBot) -> None:
    w = results_window()
    w.project.set_dimension("2d")
    w.results_tab.click()
    qtbot.waitUntil(lambda: w.results_view.has_results, timeout=15000)
    assert w._scene_mode == "results" and _looks_along_plus_y(w)
    assert _marker_x(w, w.results_view.bounds()) > 0.5
    w.scene_tab.click()
    assert _looks_along_plus_y(w)


@pytest.mark.parametrize("dimension", ["3d", "2d"])
def test_the_results_view_of_3d_is_unchanged(results_window, qtbot: QtBot, dimension: str) -> None:
    w = results_window()
    if dimension == "2d":
        w.project.set_dimension("2d")
    w.results_tab.click()
    qtbot.waitUntil(lambda: w.results_view.has_results, timeout=15000)
    look, _ = _direction(w)
    if dimension == "3d":  # the upstream ISO view (docs/QUESTIONS.md item 59)
        assert w.current_view == w.UPSTREAM_VIEW and look[0] > 0 and look[1] > 0 and look[2] < 0
    else:
        assert w.current_view == "XZ"
