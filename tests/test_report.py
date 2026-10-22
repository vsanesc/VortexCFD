"""The HTML report (D-134): a report from a fixture project with a mesh and results has every section with data, the
empty ones are left out with a one-line note, it parses as HTML and its images are embedded PNGs.

The fixture project: tests/data/results_case (a real solved box) as its case, with a mesh record, a run record, the
real forces / mass-flow / y+ outputs of tests/data/breakdown_run and a real simpleFoam log
(tests/data/pitzDaily_simpleFoam.log)."""

import base64
import io
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path

import pytest
import pyvista as pv
from PIL import Image
from pytestqt.qtbot import QtBot

from tests.test_scene_objects import results_window  # noqa: F401 (fixture)
from vortexcfd.core.model import MeanStableCriterion, Part, StoppingCriteria
from vortexcfd.core.presets import BUILTIN_PRESETS, apply_preset
from vortexcfd.core.model import Simulation
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_record import MeshRecord, write_mesh_record
from vortexcfd.foam.mesh_report import FirstCell, LayerCoverage, MeshReport
from vortexcfd.foam.run_record import RunRecord, write_run_record
from vortexcfd.workflow import report, solving
from vortexcfd.workflow.meshing import inputs_hash

DATA = Path(__file__).parent / "data"
SECTIONS = ["Project and set-up", "Geometry", "Mesh report", "Convergence", "Forces", "Mesh study", "Polar sweep",
            "Line plots", "Saved views"]


class _Checker(HTMLParser):
    """Collects the tags (void ones excluded) to check they nest, the h2 titles and the image sources."""

    VOID = {"meta", "img", "br", "hr", "link"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.h2: list[str] = []
        self.images: list[str] = []
        self.links: list[str] = []
        self._in_h2 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img":
            self.images.append(attrs.get("src", ""))
        if tag in ("a", "link", "script") and (attrs.get("href") or attrs.get("src")):
            self.links.append(attrs.get("href") or attrs.get("src"))
        if tag not in self.VOID:
            self.stack.append(tag)
        self._in_h2 = tag == "h2"

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
        else:
            self.stack.pop()
        self._in_h2 = False

    def handle_data(self, data):
        if self._in_h2:
            self.h2.append(data)


def _check(text: str) -> _Checker:
    checker = _Checker()
    checker.feed(text)
    checker.close()
    assert text.startswith("<!DOCTYPE html>") and checker.errors == [] and checker.stack == []
    return checker


def solved_project(tmp_path: Path) -> Project:
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    pv.Box(bounds=(0.5, 1.5, -0.5, 0.5, 0.0, 0.1)).triangulate().save(str(folder / "geometry" / "ball.stl"))
    project = Project.new("demo")
    project.add_part(Part(name="Ball", source_file="geometry/ball.stl"))
    project.update_solver(stopping=StoppingCriteria(criteria=[MeanStableCriterion(quantity="Cd", window=50)]))
    project.save(folder / "demo.vcfd")
    case = folder / "case"
    shutil.copytree(DATA / "results_case", case)
    shutil.copytree(DATA / "breakdown_run" / "postProcessing", case / "postProcessing")
    shutil.copy(DATA / "breakdown_run" / "system" / "controlDict", case / "system" / "controlDict")
    shutil.copy(DATA / "pitzDaily_simpleFoam.log", case / "log.simpleFoam")
    mesh = MeshReport(1000, 3200, 128, 41.2, 7.1, 0.85, 0, True,
                      layers=(LayerCoverage("Ball", 64, 6, 5.9, 0.012, 98.5, "thickness"),),
                      extruded_percent=99.0, first_cell=FirstCell(0.0018, 0.0019, 0.0018, None, 0.01))
    write_mesh_record(case, MeshRecord(mesh, inputs_hash(project), ("Ball",)))
    write_run_record(case, RunRecord("criteria_met", 300, {"p": 1e-4, "Ux": 2e-6}, solving.results_hash(project), 0,
                                     met_labels=("Cd mean stable",), met_iteration=300, duration_s=12.0, cores=2))
    return project


def test_a_report_with_every_section(tmp_path: Path) -> None:
    project = solved_project(tmp_path)
    view = report.ReportImage("View: front", _png())
    text = report.build_report(project, [view])
    checker = _check(text)
    assert checker.h2 == SECTIONS
    # no section with data is left out (the study, sweep and line plots are tested in tests/test_report_tables.py)
    assert [n for n in re.findall(r'<p class="note">(No [^<]*)</p>', text)] == [
        "No mesh study has been run.", "No polar sweep has been run.", "No line plots (Results &gt; Line plot)."]
    assert checker.links == []  # self-contained
    assert len(checker.images) == 2  # the residual plot and the view
    for src in checker.images:
        assert src.startswith("data:image/png;base64,")
        with Image.open(io.BytesIO(base64.b64decode(src.split(",", 1)[1]))) as png:
            assert png.format == "PNG"
    assert "1,000" in text and "Mesh OK" in text and "98.5" in text  # the mesh record
    assert "Criteria met: Cd mean stable" in text  # the stop reason
    assert re.search(r"<td>All walls</td><td>Cd</td><td class=\"num\">0\.\d+</td>", text)  # windowed means
    assert "over 50" in text  # the mean-stable window of Cd
    assert "y+ average" in text


def test_empty_sections_are_left_out_with_a_note(tmp_path: Path) -> None:
    project = Project.create(tmp_path, "bare", apply_preset(Simulation(name="bare"), BUILTIN_PRESETS[0]))
    text = report.build_report(project)
    checker = _check(text)
    assert checker.h2 == SECTIONS
    for note in ("No part has been imported.", "No mesh has been generated.", "The solver has not been run.",
                 "No solver results.", "No mesh study has been run.", "No polar sweep has been run.",
                 "No line plots (Results &gt; Line plot).", "No saved views (Results &gt; Save view)."):
        assert f'<p class="note">{note}</p>' in text
    assert checker.images == []
    path = report.write_report(project)
    assert path.parent == project.folder / "reports" and path.suffix == ".html"
    assert _check(path.read_text()).h2 == SECTIONS


def test_an_internal_flow_report(tmp_path: Path) -> None:
    project = Project.create(tmp_path, "duct", apply_preset(Simulation(name="duct"), BUILTIN_PRESETS[3]))
    project.update_boundary("inlet", role="inlet", inlet={"kind": "mass_flow", "mass_flow": 1.5})
    project.update_reports(pressure_drops=[{"name": "loss", "upstream": "patch:inlet_1", "downstream": "patch:outlet_1"}])
    case = project.folder / "case"
    shutil.copytree(DATA / "internal_run", case, dirs_exist_ok=True)
    text = report.build_report(project)
    checker = _check(text)
    assert checker.h2[4] == "Internal-flow reports"
    assert "<td>patch outlet_1</td><td>Mass flow (kg/s)</td><td class=\"num\">1.500" in text  # the mean of 6 rows
    assert "<td>drop loss</td><td>dp static (Pa)</td>" in text
    assert "Mass-flow inlet" in text and "1.5 kg/s" in text  # the boundaries table


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 4), (200, 10, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_window_renders_the_saved_views_into_the_report(results_window, qtbot: QtBot) -> None:
    w = results_window()
    w.results_tab.click()
    qtbot.waitUntil(lambda: w.results_view.has_results, timeout=15000)
    w._select_node("results", None)
    w.properties.sc_save_view.click()
    w.viewer.camera.position = (5.0, 5.0, 5.0)
    w.properties.sc_report.click()
    (path,) = (w.project.folder / "reports").glob("*.html")
    checker = _check(path.read_text())
    assert "View: View 1" in path.read_text() and len(checker.images) == 1  # the view (no solver log: no plot)
    with Image.open(io.BytesIO(base64.b64decode(checker.images[0].split(",", 1)[1]))) as png:
        assert png.size == w.REPORT_IMAGE_SIZE
    assert tuple(w.viewer.camera.position) == pytest.approx((5.0, 5.0, 5.0))  # the camera is restored
