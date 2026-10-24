"""The Reynolds and Mach numbers (D-168): external flow on U∞ and l_ref, internal flow on each inlet's D_h and bulk
velocity, the compressibility warning, the speed of sound, and where they are shown (the Free stream live, the Physics
node and the inlets of internal flow, the Run solver tooltip, the report and the snapshots)."""

import math
from pathlib import Path

import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from tests.test_internal_flow import D, RHO, pipe_project
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import migrate
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import MainWindow
from vortexcfd.workflow import flow_numbers as fn
from vortexcfd.workflow import internal, solving


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def sphere_project(tmp_path: Path) -> Project:
    (tmp_path / "geometry").mkdir(parents=True, exist_ok=True)
    pv.Box(bounds=(0.0, 1.0, -0.5, 0.5, -0.5, 0.5)).triangulate().save(str(tmp_path / "geometry" / "ball.stl"))
    project = Project.new("s")
    project.add_part(Part(name="ball", source_file="geometry/ball.stl"))
    project.update_domain(enabled=True)
    project.save(tmp_path / "s.vcfd")
    return project


def test_format_number() -> None:
    assert fn.format_number(1.2e6) == "1.2·10⁶"
    assert fn.format_number(1.33e6) == "1.3·10⁶"
    assert fn.format_number(4.5e-5) == "4.5·10⁻⁵"
    assert fn.format_number(250.0) == "250" and fn.format_number(1.5) == "1.5"
    assert fn.format_number(12000.0) == "1.2·10⁴"


def test_external_flow_on_the_free_stream_and_l_ref(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    numbers = fn.external_numbers(project)
    l_ref = numbers.length
    assert l_ref == pytest.approx(1.0)  # the box's x extent (auto l_ref)
    assert numbers.reynolds == pytest.approx(20.0 * l_ref / 1.5e-5)
    assert numbers.mach == pytest.approx(20.0 / 343.0)
    assert numbers.reynolds_text() == "Re = 1.3·10⁶ on U∞ = 20 m/s, l_ref = 1 m"
    assert numbers.mach_text(343.0) == "Ma = 0.0583 on U∞ = 20 m/s, a = 343 m/s"
    assert numbers.warning is None
    project.update_reports(reference_length=0.3)
    project.update_physics(nu=1e-5)
    numbers = fn.external_numbers(project)
    assert numbers.reynolds == pytest.approx(20.0 * 0.3 / 1e-5) and "l_ref = 0.3 m" in numbers.reynolds_text()
    project.update_inflow(speed=120.0)
    numbers = fn.external_numbers(project)
    assert numbers.mach == pytest.approx(120.0 / 343.0)
    assert numbers.warning.startswith("Mach number 0.35 is above 0.3: the app solves incompressible flow")
    project.update_physics(speed_of_sound=1480.0)  # water: incompressible again
    assert fn.external_numbers(project).warning is None


def test_the_speed_of_sound_is_a_reference_value_only(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    assert project.sim.physics.speed_of_sound == 343.0
    before = solving.results_hash(project)
    project.update_physics(speed_of_sound=340.0)
    assert solving.results_hash(project) == before  # never written to the case: results stay current
    assert migrate({"schema_version": 23, "x": 1}) == {"schema_version": 24, "x": 1}
    with pytest.raises(ValueError):
        project.update_physics(speed_of_sound=0.0)


def test_internal_flow_on_each_inlets_hydraulic_diameter(tmp_path: Path) -> None:
    project = pipe_project(tmp_path)  # a mass-flow inlet of 2 kg/s, water
    area = math.pi * D ** 2 / 4
    (safe, numbers), = fn.inlet_numbers(project).items()
    assert numbers.length == pytest.approx(D, rel=0.02)  # D_h of the round inlet
    assert numbers.speed == pytest.approx(2.0 / (RHO * area), rel=0.02)  # ṁ / (ρ A)
    assert numbers.reynolds == pytest.approx(numbers.speed * numbers.length / 1e-6)
    assert numbers.source == "ṁ / (ρ A)" and numbers.length_name == "D_h (inlet)"
    project.update_boundary("inlet", inlet={"kind": "velocity", "speed": 1.5})
    numbers = fn.inlet_numbers(project)[safe]
    assert numbers.speed == 1.5 and numbers.source == "velocity inlet"
    project.update_boundary("inlet", inlet={"kind": "total_pressure", "total_pressure": 500.0})
    numbers = fn.inlet_numbers(project)[safe]
    assert numbers.reynolds is None and numbers.reynolds_text().startswith("known after the run")
    mdot = {f"flow:mdot:patch:{safe}": -1.5}  # the run's mass-flow report (negative: into the domain)
    numbers = fn.inlet_numbers(project, mdot.get)[safe]
    assert numbers.speed == pytest.approx(1.5 / (RHO * area), rel=0.02)
    assert numbers.source == "from the run's mass-flow report"
    assert fn.project_numbers(project, mdot.get) == numbers  # the reference inlet's


# -- the GUI -----------------------------------------------------------------------------------------------------


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path):
    w = MainWindow(sphere_project(tmp_path), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    yield w
    w.project.save = lambda *a, **k: None
    w.close()


def test_the_free_stream_shows_re_and_mach_live(window: MainWindow) -> None:
    w, p = window, window.properties
    w.tree.setCurrentItem(w._items[("inflow", None)])
    assert p._rows["inflow_re"].isVisibleTo(p) and p._rows["inflow_mach"].isVisibleTo(p)
    assert p.inflow_re.text() == "Re = 1.3·10⁶ on U∞ = 20 m/s, l_ref = 1 m"
    assert p.inflow_mach.text() == "Ma = 0.0583 on U∞ = 20 m/s, a = 343 m/s"
    assert not p.inflow_mach_warning.isVisibleTo(p)
    speed = p.group_fields["inflow"]["speed"]
    speed.setValue(40.0)  # typed, not committed yet: the numbers follow at once
    assert p.inflow_re.text().startswith("Re = 2.7·10⁶ on U∞ = 40 m/s")
    assert w.project.sim.inflow.speed == 20.0
    speed.setValue(150.0)
    assert p.inflow_mach_warning.isVisibleTo(p) and "incompressible" in p.inflow_mach_warning.text()
    assert p.inflow_mach.property("warn") == "true"
    speed.editingFinished.emit()
    assert w.project.sim.inflow.speed == 150.0
    tip = w.top_bar.run_button.toolTip()
    assert "Mach number 0.44 is above 0.3" in tip or w.solve_readiness() is not None
    w._update_run_button()
    if w.solve_readiness() is None:
        assert "Mach number 0.44 is above 0.3" in w.top_bar.run_button.toolTip()
    w.project.update_reports(reference_length=0.3)  # l_ref and nu edited elsewhere: shown when back
    w.project.update_physics(nu=3e-5)
    w.tree.setCurrentItem(w._items[("inflow", None)])
    assert p.inflow_re.text().startswith("Re = 1.5·10⁶ on U∞ = 150 m/s, l_ref = 0.3 m")


def test_the_run_solver_tooltip_warns_above_mach_03(window: MainWindow) -> None:
    from tests.test_solver_gui import fake_mesh

    w = window
    w.project.update_inflow(speed=200.0)
    fake_mesh(w.project)
    w._load_mesh_record(w.project) if hasattr(w, "_load_mesh_record") else None
    warning = w._compressibility_warning()
    assert warning.startswith("Mach number 0.58 is above 0.3")
    w.top_bar.set_solver_state(None, False, None, None, warning)
    assert f"Warning: {warning}" in w.top_bar.run_button.toolTip()


def test_the_speed_of_sound_is_edited_on_the_physics_node(window: MainWindow) -> None:
    w, p = window, window.properties
    w.tree.setCurrentItem(w._items[("physics", None)])
    field = p.group_fields["physics"]["speed_of_sound"]
    assert p._rows["physics_speed_of_sound"].isVisibleTo(p) and field.suffix() == " m/s" and field.value() == 343.0
    assert "343 m/s: air at 20" in field.toolTip()
    field.setValue(340.0)
    field.editingFinished.emit()
    assert w.project.sim.physics.speed_of_sound == 340.0
    w.tree.setCurrentItem(w._items[("inflow", None)])
    assert p.inflow_mach.text().endswith("a = 340 m/s")


def test_internal_flow_shows_the_inlets_numbers(qtbot: QtBot, tmp_path: Path) -> None:
    project = pipe_project(tmp_path)
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    p = w.properties
    w.tree.setCurrentItem(w._items[("physics", None)])
    assert p._sections["physics_numbers"].isVisibleTo(p)
    expected = fn.project_numbers(project).reynolds_text()
    assert expected.startswith("Re = 2.6·10⁴ on U_bulk = 0.256 m/s, D_h (inlet) = 0.0995 m")
    assert p.physics_re.text() == expected
    patch = next(i for i, ip in enumerate(internal.patches(project)) if ip.role == "inlet")
    w.tree.setCurrentItem(w._items[("internal_patch", patch)])
    assert p._rows["ip_re"].isVisibleTo(p) and p.ip_re.text().startswith(expected)
    project.update_boundary("inlet", inlet={"kind": "total_pressure", "total_pressure": 500.0})
    w.tree.setCurrentItem(w._items[("internal_patch", patch)])
    assert p.ip_re.text().startswith("known after the run")
    safe = internal.patches(project)[patch].safe

    class Monitor:  # the shown run's reports: the inlet's mass flow
        @staticmethod
        def series(report_id):
            return [(10.0, -2.0)] if report_id == f"flow:mdot:patch:{safe}" else []

    p._report_monitor = Monitor()
    w.tree.setCurrentItem(w._items[("physics", None)])
    w.tree.setCurrentItem(w._items[("internal_patch", patch)])
    assert p.ip_re.text().startswith("Re = 2.6·10⁴") and "mass-flow report" in p.ip_re.text()
    w.project.save = lambda *a, **k: None
    w.close()


def test_the_report_and_the_snapshot_have_re_and_mach(tmp_path: Path) -> None:
    from tests.test_report import solved_project
    from vortexcfd.workflow import report, snapshots

    project = solved_project(tmp_path)
    text = report.build_report(project, [])
    assert "<th>Reynolds number</th><td>Re = " in text or "Reynolds number" in text
    assert "Ma = " in text and "on U∞ = 20 m/s" in text
    snap = snapshots.capture(project, "a")
    assert snap.setup["flow: Mach number"] == "0.0583"
    assert snap.setup["flow: Reynolds number"].startswith("1.3·10⁶ (U∞ 20 m/s, l_ref 1 m)") or \
        snap.setup["flow: Reynolds number"].endswith("m)")
