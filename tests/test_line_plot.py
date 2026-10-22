"""Line plots (D-136): the samples along a line on the real fixture case tests/data/results_case, the CSV and PNG
exports, the Results node's line plot with its embedded chart, and the streamlines' own scalar bar (D-136)."""

import csv
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from tests.test_scene_objects import CASE, results_window  # noqa: F401 (fixture)
from vortexcfd.core.model import LinePlotObject, StreamlinesObject
from vortexcfd.workflow import line_plot


@pytest.fixture(scope="module")
def points():
    return line_plot.case_points(CASE)


def test_samples_inside_and_outside_the_fluid(points) -> None:
    obj = LinePlotObject(id="l", name="L", point1=(-0.5, 0.0, 0.5), point2=(2.5, 0.0, 0.5), n_samples=31,
                         fields=["U_mag", "p", "yPlus"])
    samples = line_plot.sample_line(points, obj, 20.0)
    assert samples.distance[0] == 0.0 and samples.distance[-1] == pytest.approx(3.0)
    assert samples.positions.shape == (31, 3)
    u = samples.values["U_mag"]
    inside = (samples.positions[:, 0] >= 0.0) & (samples.positions[:, 0] <= 2.0)
    assert np.isfinite(u[inside]).all() and np.isnan(u[~inside]).all() and samples.inside == 21
    assert 0 < np.nanmean(u) < 40  # 20 m/s free stream
    assert "yPlus" in samples.values  # point data from the internal field (the wall-only fields are absent)
    with pytest.raises(ValueError, match="outside the fluid"):
        line_plot.sample_line(points, obj.model_copy(update={"point1": (5, 0, 0), "point2": (6, 0, 0)}), 20.0)
    with pytest.raises(ValueError, match="none of the line's fields"):
        line_plot.sample_line(points, obj.model_copy(update={"fields": ["Cf"]}), 20.0)
    with pytest.raises(ValueError, match="two points"):
        LinePlotObject(id="x", name="X", point1=(1, 1, 1), point2=(1, 1, 1))


def test_csv_and_png_exports(points, tmp_path: Path) -> None:
    obj = LinePlotObject(id="l", name="L", point1=(-0.5, 0.0, 0.5), point2=(2.5, 0.0, 0.5), n_samples=11,
                         fields=["U_x", "Cp"])
    samples = line_plot.sample_line(points, obj, 20.0)
    line_plot.write_csv(samples, tmp_path / "l.csv")
    rows = list(csv.reader((tmp_path / "l.csv").open()))
    assert rows[0] == ["distance_m", "x_m", "y_m", "z_m", "U_x", "Cp"] and len(rows) == 12
    assert rows[1][4] == "" and rows[1][0] == "0.0"  # outside the fluid: empty
    assert float(rows[6][4]) == pytest.approx(samples.values["U_x"][5])
    line_plot.write_png(samples, tmp_path / "out" / "l.png", "L")
    with Image.open(tmp_path / "out" / "l.png") as png:
        assert png.format == "PNG" and png.size[0] == 1200


def test_the_results_node_line_plot_chart_and_exports(results_window, qtbot: QtBot) -> None:
    w = results_window()
    w.results_tab.click()
    qtbot.waitUntil(lambda: w.results_view.has_results, timeout=15000)
    w._select_node("results", None)
    panel = w.properties
    panel.sc_add_buttons["line_plot"].click()
    (obj,) = w.project.sim.results.objects
    assert obj.kind == "line_plot" and obj.fields == ["U_mag", "p"]
    assert obj.point1 == pytest.approx((0.0, 0.0, 0.5)) and obj.point2 == pytest.approx((2.0, 0.0, 0.5))
    view = w.results_view
    assert len(view.object_actors) == 1 and view.object_errors == {}  # the line drawn in the viewer
    samples = view.line_samples[obj.id]
    assert panel._rows["sc_chart"].isVisibleTo(panel) and panel.sc_chart.samples is samples
    assert len(panel.sc_chart.figure_.axes) == 2  # one axes per field
    # one field less from the check boxes: one undo step, the chart follows
    fields = panel.sc_fields[("line_plot", "fields")]
    fields.boxes["p"].setChecked(False)
    assert w.project.sim.results.objects[0].fields == ["U_mag"]
    assert len(panel.sc_chart.figure_.axes) == 1
    # exports through the dialogs
    w.dialogs.line_export_path = w.project.folder / "exports" / "line.csv"
    panel.sc_line_csv.click()
    assert w.dialogs.line_export_asked[-1][1] == "csv" and (w.project.folder / "exports" / "line.csv").is_file()
    w.dialogs.line_export_path = w.project.folder / "images" / "line.png"
    panel.sc_line_png.click()
    assert (w.project.folder / "images" / "line.png").is_file()
    # outside the fluid: no samples, the reason on the node, the exports disabled
    w.project.update_scene_object(obj.id, point1=(5.0, 0.0, 0.0), point2=(6.0, 0.0, 0.0))
    assert "outside the fluid" in view.object_errors[obj.id] and obj.id not in view.line_samples
    assert not panel.sc_line_png.isEnabled() and panel.sc_chart.samples is None


def test_streamlines_have_their_own_scalar_bar(results_window, qtbot: QtBot) -> None:
    from vortexcfd.gui.image_export import render_image

    w = results_window()
    w.results_tab.click()
    qtbot.waitUntil(lambda: w.results_view.has_results, timeout=15000)
    w._select_node("results", None)
    panel = w.properties
    panel.sc_add_buttons["streamlines"].click()
    (obj,) = w.project.sim.results.objects
    view = w.results_view
    assert len(view.object_bars) == 1 and view.object_bars[0].GetTitle() == "Streamlines 1: |U| [m/s]"
    assert view.scalar_bar is not None  # the scene's bar for the walls stays
    assert render_image(w.viewer, (320, 200)).scalar_bars == 2
    # the same controls as the scene's: colormap, range mode and fixed limits
    rows = panel.sc_fields
    assert not panel._rows["sc_streamlines_range_min"].isVisibleTo(panel)
    rows[("streamlines", "range_mode")].setCurrentIndex(rows[("streamlines", "range_mode")].findData("fixed"))
    assert panel._rows["sc_streamlines_range_min"].isVisibleTo(panel)
    w.project.update_scene_object(obj.id, range_min=5.0, range_max=25.0)
    assert view.object_actors[0].mapper.scalar_range == pytest.approx((5.0, 25.0))
    combo = rows[("streamlines", "colormap")]
    combo.setCurrentIndex(combo.findData("turbo"))
    assert w.project.sim.results.objects[0].colormap == "turbo"
    lut = view.object_actors[0].mapper.lookup_table
    assert lut.cmap.name == "turbo"
    rows[("streamlines", "scalar_bar")].setChecked(False)
    assert view.object_bars == [] and not w.project.sim.results.objects[0].scalar_bar
    assert StreamlinesObject(id="s", name="S").colormap is None  # the scene's colormap by default
