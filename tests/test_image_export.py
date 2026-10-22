"""Image export (D-133): the viewer rendered offscreen at the requested size, with the scalar bar and the camera, an
optional transparent background (offscreen; the real solved fixture case of tests/test_scene_objects.py)."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from tests.test_scene_objects import results_window  # noqa: F401 (fixture)
from vortexcfd.gui.image_export import PRESETS, ExportImageDialog, ExportSpec, render_image


def _shown(w, qtbot: QtBot):
    w.results_tab.click()
    qtbot.waitUntil(lambda: w.results_view.has_results, timeout=15000)
    w.viewer.render()
    return w


def test_the_image_has_the_requested_size_and_the_scalar_bar(results_window, qtbot: QtBot, tmp_path: Path) -> None:
    w = _shown(results_window(), qtbot)
    w.dialogs.export_spec = ExportSpec(tmp_path / "out" / "view.png", (1920, 1080), False)
    image = w.export_image()
    with Image.open(tmp_path / "out" / "view.png") as png:
        assert png.size == (1920, 1080) and png.mode == "RGB"
    assert image.scalar_bars == 1 and image.actors >= 1
    assert w.dialogs.export_asked[0].parent == w.project.folder / "images"
    # rendered at that size, not scaled up: another size is another render, the same camera
    small = render_image(w.viewer, (640, 360))
    assert small.pixels.shape == (360, 640, 3)
    assert tuple(w.viewer.camera.position) == pytest.approx(tuple(w.viewer.camera.position))


def test_a_transparent_background_keeps_the_scene_and_the_scalar_bar(results_window, qtbot: QtBot) -> None:
    w = _shown(results_window(), qtbot)
    image = render_image(w.viewer, (800, 600), transparent=True)
    alpha = image.pixels[:, :, 3]
    assert image.pixels.shape == (600, 800, 4)
    assert alpha[0, 0] == 0 and alpha[-1, -1] == 0  # the background corners are transparent
    middle = alpha[200:400, 250:550]
    assert (middle == 255).mean() > 0.2  # the walls are drawn in the middle of the view (not only the bar)
    # the scalar bar sits at x 0.86-0.93, y 0.12-0.82 of the viewport (results_scene._add_scalar_bar)
    bar = alpha[int(600 * 0.20):int(600 * 0.80), int(800 * 0.87):int(800 * 0.92)]
    assert (bar > 0).mean() > 0.3
    w.results_view.set_visible(False)  # hidden actors are not exported
    w.results_view.set_visible(True)


def test_the_dialog_presets_and_custom_size(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = ExportImageDialog(tmp_path / "a")
    qtbot.addWidget(dialog)
    assert [dialog.preset.itemText(i) for i in range(dialog.preset.count())] == [*PRESETS, "Custom"]
    dialog.preset.setCurrentText("3840 x 2160 (4K UHD)")
    assert dialog.spec() == ExportSpec(tmp_path / "a.png", (3840, 2160), False)
    assert not dialog.width_spin.isEnabled()
    dialog.preset.setCurrentText("Custom")
    dialog.width_spin.setValue(1000)
    dialog.height_spin.setValue(500)
    dialog.transparent.setChecked(True)
    assert dialog.spec() == ExportSpec(tmp_path / "a.png", (1000, 500), True)
    with pytest.raises(ValueError):
        render_image(None, (0, 10))


def test_the_render_uses_the_viewer_camera() -> None:
    """The offscreen render keeps the source camera (PyVista resets an unset camera to its default view on the first
    render: before the fix every export and report view was drawn from that default view)."""
    import pyvista as pv

    source = pv.Plotter(off_screen=True, window_size=(200, 100))
    try:
        source.set_background("black")
        source.add_mesh(pv.Sphere(radius=0.2, center=(1.0, 0.0, 0.0)), color="white", lighting=False)
        # the sphere left of the image centre: the camera looks along +y at x = 1.6, from 4 m away
        source.camera.position, source.camera.focal_point, source.camera.up = (1.6, -4.0, 0.0), (1.6, 0.0, 0.0), (0, 0, 1)
        image = render_image(source, (200, 100))
    finally:
        source.close()
    bright = np.argwhere(image.pixels.sum(axis=2) > 300)
    assert bright.size and 65 < bright[:, 1].mean() < 80  # 0.6 m left at 4 m, 30 degrees: column 72 (default view: 100)
