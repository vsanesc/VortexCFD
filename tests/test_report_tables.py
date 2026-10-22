"""The report's mesh study and polar sweep tables, its line plots and the choice of its sections (D-136).

Fixtures: tests/data/study_naca0012_r3.json (the real NACA 0012 round 3 study record), tests/data/sweep_naca0012_r3.json
(a sweep record of the round 3 per-angle results) and the solved project of tests/test_report.py."""

import base64
import io
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from tests.test_report import SECTIONS, _check, solved_project
from tests.test_scene_objects import results_window  # noqa: F401 (fixture)
from vortexcfd.core.model import REPORT_SECTIONS, Simulation
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import migrate
from vortexcfd.foam import mesh_study, polar_sweep
from vortexcfd.workflow import report

DATA = Path(__file__).parent / "data"


def _with_records(tmp_path: Path, dimensions: int | None = None) -> Project:
    project = Project.create(tmp_path, "naca", Simulation(name="naca"))
    study = project.folder / mesh_study.STUDY_DIR_NAME
    study.mkdir()
    data = json.loads((DATA / "study_naca0012_r3.json").read_text())
    if dimensions is not None:
        data["dimensions"] = dimensions
    (study / mesh_study.STUDY_JSON).write_text(json.dumps(data))
    sweep = project.folder / polar_sweep.SWEEP_DIR_NAME
    sweep.mkdir()
    shutil.copy(DATA / "sweep_naca0012_r3.json", sweep / polar_sweep.SWEEP_JSON)
    return project


def _decode(src: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(src.split(",", 1)[1])))


def test_the_mesh_study_table_has_the_gci_or_why_not(tmp_path: Path) -> None:
    project = _with_records(tmp_path)
    section = report.study_section(project)
    assert section.body is not None
    rows = {r.quantity: r for r in mesh_study.quantity_rows(mesh_study.read_record(project.folder / "case_study"))}
    cl = rows["Cl"].result
    assert cl.applicable and f"{100 * cl.gci_fine:.3g} %" in section.body  # the GCI of CL (RESULT.md: 1.9 %)
    assert "<td>Cl</td>" in section.body or "<td>CL</td>" in section.body
    assert "oscillatory, GCI not applicable" in section.body  # CD viscous: why there is no GCI
    assert "176,110 cells" in section.body  # the medium level
    assert "indicative" not in section.body  # a 2D study
    assert "indicative" in report.study_section(_with_records(tmp_path / "3d", dimensions=3)).body


def test_the_polar_sweep_table_and_plot(tmp_path: Path) -> None:
    project = _with_records(tmp_path)
    text = report.build_report(project)
    checker = _check(text)
    assert checker.h2 == SECTIONS
    section = report.sweep_section(project)
    for value in ("1.4752", "0.023137", "0.009138", "2363"):  # CL 15, CD 15, CM 10, iterations 10
        assert value in section.body
    assert section.body.count("<tr>") == 3 + 4  # the summary (header + 2 rows), the polar table (header + 3 angles)
    (src,) = [s for s in checker.images]  # the polar plot (no solver log, no views)
    with _decode(src) as png:
        assert png.format == "PNG" and png.size == (900, 320)


def test_a_line_plot_in_the_report(tmp_path: Path) -> None:
    project = solved_project(tmp_path)
    project.add_scene_object("line_plot", point1=(-0.5, 0.0, 0.5), point2=(2.5, 0.0, 0.5), n_samples=31,
                             fields=["U_mag", "p"])
    project.add_scene_object("line_plot", point1=(5.0, 0.0, 0.5), point2=(6.0, 0.0, 0.5))
    section = report.line_plots_section(project)
    assert section.body.count("<figure>") == 1
    assert "Line plot 1: from (-0.5, 0, 0.5) to (2.5, 0, 0.5) m, 31 samples (21 of 31 samples inside the fluid)" in section.body
    assert "Line plot 2" in section.body and "the line is outside the fluid" in section.body
    checker = _check(report.build_report(project))
    assert "Line plots" in checker.h2


def test_omitted_sections_are_not_in_the_report(tmp_path: Path) -> None:
    project = _with_records(tmp_path)
    text = report.build_report(project, omit=["geometry", "sweep", "views"])
    assert _check(text).h2 == [s for s in SECTIONS if s not in ("Geometry", "Polar sweep", "Saved views")]
    project.set_report_omit(["mesh", "line_plots"])
    assert project.sim.results.report_omit == ["mesh", "line_plots"] and project.can_undo
    assert "Mesh report" not in _check(report.build_report(project)).h2  # the project's choice by default
    project.save()
    assert Project.open(project.path).sim.results.report_omit == ["mesh", "line_plots"]
    with pytest.raises(ValueError):
        project.set_report_omit(["nonsense"])
    assert list(REPORT_SECTIONS) == ["setup", "geometry", "mesh", "convergence", "reports", "study", "sweep",
                                     "line_plots", "views"]


def test_a_v20_project_migrates_to_v21() -> None:
    raw = json.loads((DATA / "project_v19.json").read_text())
    data = migrate(raw)
    sim = Simulation.model_validate(data)
    assert sim.schema_version == 21 and sim.results.report_omit == []


def test_the_window_asks_for_the_sections_and_remembers_them(results_window, qtbot: QtBot) -> None:
    w = results_window()
    w.dialogs.report_omit = ["geometry", "views"]
    path = w.create_report()
    assert w.dialogs.report_sections_asked == [[]]
    assert w.project.sim.results.report_omit == ["geometry", "views"]
    h2 = _check(path.read_text()).h2
    assert "Geometry" not in h2 and "Saved views" not in h2 and "Mesh report" in h2
    w.dialogs.report_omit = None  # keeps the project's choice: the dialog starts from it
    w.create_report()
    assert w.dialogs.report_sections_asked[-1] == ["geometry", "views"]
    w.dialogs.ask_report_sections = lambda omit: None  # cancelled: no report
    assert w.create_report() is None
