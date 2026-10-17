"""Cp on wall sections (D-062): extraction, x/c normalization, upper/lower split, CSV export and
the Sections tool, on the real sphere wall of tests/data/breakdown_run (iteration 300)."""

import csv
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from vortexcfd.gui.sections import cut_section, export_csv, stations

WALL = Path(__file__).parent / "data" / "breakdown_run" / "sphere_wall.vtp"
U_REF = 20.0


@pytest.fixture(scope="module")
def wall() -> pv.PolyData:
    return pv.read(str(WALL))


def test_stations_are_inside_the_range() -> None:
    assert stations(-0.5, 0.5, 1) == [0.0]
    assert stations(-0.5, 0.5, 3) == pytest.approx([-0.25, 0.0, 0.25])
    assert stations(0.0, 1.0, 4) == pytest.approx([0.2, 0.4, 0.6, 0.8])
    with pytest.raises(ValueError):
        stations(0, 1, 0)


def test_centre_section_of_the_sphere(wall) -> None:
    """The y = 0 cut: chord = the sphere's x extent, upper (outward n_z > 0) and lower lines, each
    ordered by x from x/c 0 to 1; the stagnation point at x/c = 0 has Cp about 1 (0.991)."""
    s = cut_section({"Sphere": wall}, "y", 0.0, U_REF)
    assert s.label == "y = 0 m" and s.chord == pytest.approx(0.99767, abs=1e-5) and s.x_min == pytest.approx(-0.49883, abs=1e-5)
    assert [line.surface for line in s.lines] == ["upper", "lower"]
    upper, lower = s.lines
    assert (upper.points[:, 2] > 0).mean() > 0.95 and (lower.points[:, 2] < 0).mean() > 0.95
    for line in s.lines:
        assert np.all(np.diff(line.points[:, 0]) >= 0) and np.all(np.diff(line.x_c) >= 0)
        assert line.x_c.min() >= 0 and line.x_c.max() <= 1
        assert np.allclose(line.x_c, (line.points[:, 0] - s.x_min) / s.chord)
        assert np.abs(line.points[:, 1]).max() < 1e-6  # on the plane
    for line in s.lines:  # stagnation point
        assert line.x_c[0] == pytest.approx(0.0, abs=1e-6)
        assert line.cp[0] == pytest.approx(0.9906, abs=1e-3) and line.cp.max() == line.cp[0]
    assert abs(upper.cp[0] - 1.0) < 0.02
    p = wall.cell_data["p"]
    assert upper.cp.min() >= p.min() / (0.5 * U_REF**2) - 1e-9  # values come from the wall faces


def test_horizontal_section_is_one_line_and_misses_give_none(wall) -> None:
    s = cut_section({"Sphere": wall}, "z", 0.0, U_REF)
    assert [line.surface for line in s.lines] == ["all"]  # normals horizontal: no upper/lower
    assert np.all(np.diff(s.lines[0].points[:, 0]) >= 0)
    assert cut_section({"Sphere": wall}, "y", 0.7, U_REF) is None
    with pytest.raises(ValueError):
        cut_section({"Sphere": wall}, "x", 0.0, U_REF)
    no_p = wall.copy()
    no_p.cell_data.remove("p")
    assert cut_section({"Sphere": no_p}, "y", 0.0, U_REF) is None


def test_csv_export(wall, tmp_path: Path) -> None:
    sections = [cut_section({"Sphere": wall}, "y", y, U_REF) for y in stations(-0.5, 0.5, 3)]
    path = tmp_path / "s.csv"
    rows = export_csv(sections, path)
    assert rows == sum(len(line.cp) for s in sections for line in s.lines)
    with open(path, newline="") as fh:
        table = list(csv.reader(fh))
    assert table[0] == ["section", "axis", "position_m", "chord_m", "surface", "x_m", "y_m", "z_m", "x_c", "Cp"]
    assert len(table) == rows + 1 and {r[0] for r in table[1:]} == {"1", "2", "3"}
    first = sections[0].lines[0]
    assert table[1][:5] == ["1", "y", "-0.25", f"{sections[0].chord:.6g}", "upper"]
    assert float(table[1][8]) == pytest.approx(first.x_c[0], abs=1e-6)
    assert float(table[1][9]) == pytest.approx(first.cp[0], rel=1e-5)


def test_section_tool_cuts_stations_and_plots(wall, qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.section_tool import SectionTool

    tool = SectionTool()
    qtbot.addWidget(tool)
    tool.set_results({"Sphere": wall}, U_REF, tuple(wall.bounds))
    assert tool.axis.currentText() == "y" and tool.position.value() == pytest.approx(0.0, abs=1e-4)
    assert not tool.export.isEnabled() and tool.chart.series == []
    tool.cut()
    assert [s.position for s in tool.sections] == pytest.approx([(wall.bounds[2] + wall.bounds[3]) / 2])
    assert [name for name, *_ in tool.chart.series] == [f"{tool.sections[0].label} upper", f"{tool.sections[0].label} lower"]
    assert tool.chart.invert_y and tool.export.isEnabled()
    tool.multi.setChecked(True)
    tool.count.setValue(3)
    tool.cut()
    assert [s.position for s in tool.sections] == pytest.approx(stations(wall.bounds[2], wall.bounds[3], 3))
    assert tool.sections[0].position == pytest.approx(-0.2494, abs=1e-4)
    assert len(tool.chart.series) == 6 and tool.status.text() == "3 section(s)"
    styles = {style for _n, _c, style, _p in tool.chart.series}
    assert styles == {"SolidLine", "DashLine"}
    assert tool.write_csv(tmp_path / "out.csv") > 0
    tool.single.setChecked(True)
    tool.position.setValue(0.6)
    tool.cut()
    assert tool.sections == [] and tool.status.text() == "0 section(s), 1 missed the walls"


def test_export_from_the_main_window(make_window, wall, tmp_path: Path) -> None:
    from vortexcfd.gui.section_tool import SectionTool

    w = make_window()
    w.open_sections()  # no viewer: no results to cut
    assert "No results" in w.statusBar().currentMessage()
    w.section_tool = SectionTool(w)
    w.section_tool.export_requested.connect(w.export_sections)
    w.section_tool.set_results({"Sphere": wall}, U_REF, tuple(wall.bounds))
    w.section_tool.cut()
    w.dialogs.csv_path = tmp_path / "sections.csv"
    w.section_tool.export.click()
    assert (tmp_path / "sections.csv").is_file()
    assert w.statusBar().currentMessage().startswith("Exported ") and "section points" in w.statusBar().currentMessage()


from tests.test_solver_gui import fake_mesh, make_window  # noqa: E402,F401 (fixture)
