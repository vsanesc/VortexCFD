"""The achieved first cell reported after meshing (D-109): one healthy and one collapsed fixture. [NUMERICS-REVIEW]"""

from pathlib import Path

import numpy as np
import pytest

from tests.test_cfmesh_case import needs_openfoam, write_column
from vortexcfd.foam.layer_walk import first_cell_stats, walk_layers, weighted_percentile
from vortexcfd.foam.mesh_record import MeshRecord, read_mesh_record, write_mesh_record
from vortexcfd.foam.mesh_report import FIRST_CELL_DRIFT, FirstCell, MeshReport
from vortexcfd.foam.mesh_run import MeshRun, measure_first_cell
from vortexcfd.foam.polymesh import PolyMesh

STACK = [1e-3 * 1.2 ** k for k in range(5)]  # five layers from a 1 mm first layer


def _report(first_cell: FirstCell | None) -> MeshReport:
    return MeshReport(points=1, faces=1, cells=7, max_non_orthogonality=0.0, avg_non_orthogonality=0.0,
                      max_skewness=0.0, failed_checks=0, mesh_ok=True, first_cell=first_cell)


def test_healthy_stack_reports_the_planned_first_cell(tmp_path: Path) -> None:
    write_column(tmp_path, STACK + [0.05, 0.05])
    fc = measure_first_cell(tmp_path, ("wall",), 1e-3, 5)
    assert fc.error is None and fc.mean_m == pytest.approx(1e-3) and fc.p95_m == pytest.approx(1e-3)
    assert fc.ratio == pytest.approx(1.0) and fc.warning() is None
    assert fc.description() == "1 mm mean, 1 mm 95th percentile (planned 1 mm)"
    assert _report(fc).first_cell_warning() is None


def test_collapsed_stack_warns_about_the_y_plus_drift(tmp_path: Path) -> None:
    write_column(tmp_path, [0.05, 0.05])  # no layer left: a 50 mm core cell on the wall
    fc = measure_first_cell(tmp_path, ("wall",), 1e-3, 5)
    assert fc.error is None and fc.mean_m == pytest.approx(0.05)
    assert fc.warning() == ("Layers collapsed near the wall: first cell 50 mm vs 1 mm planned; "
                            "y+ will be about 50.0 times the target.")
    assert _report(fc).first_cell_warning() == fc.warning()


def test_the_warning_starts_above_one_and_a_half_times_the_plan() -> None:
    assert FIRST_CELL_DRIFT == 1.5
    assert FirstCell(mean_m=1.5e-3, p95_m=2e-3, planned_m=1e-3).warning() is None
    assert "about 1.6 times" in FirstCell(mean_m=1.6e-3, p95_m=2e-3, planned_m=1e-3).warning()
    assert FirstCell(planned_m=1e-3, error="x").warning() is None and _report(None).first_cell_warning() is None


def test_a_failed_measurement_is_recorded_not_raised(tmp_path: Path) -> None:
    fc = measure_first_cell(tmp_path / "missing", ("wall",), 1e-3, 5)  # no polyMesh
    assert fc.mean_m is None and fc.error and fc.warning() is None
    assert fc.description().startswith("not measured (")
    write_column(tmp_path / "col", STACK)
    assert measure_first_cell(tmp_path / "col", ("nowall",), 1e-3, 5).error == "no wall patch in the mesh"


def test_first_cell_statistics_are_area_weighted() -> None:
    area = np.array([1.0, 1.0, 98.0])
    cell = np.array([5.0, 3.0, 1.0])
    stats = first_cell_stats(area, cell, np.array([0, 2, 3]))
    assert stats["mean_m"] == pytest.approx((5 + 3 + 98) / 100)
    assert stats["p95_m"] == 1.0 and stats["max_extruded_m"] == 3.0  # the 5 is on a face without layers
    assert weighted_percentile(cell, area, 99.5) == 5.0
    assert first_cell_stats(np.array([]), np.array([]), np.array([]))["mean_m"] is None


def test_the_walk_records_the_wall_cell_with_and_without_layers(tmp_path: Path) -> None:
    write_column(tmp_path, STACK + [0.05])
    walked = walk_layers(PolyMesh.read(tmp_path), ("wall",), 10)["wall"]
    assert walked["layers"].tolist() == [5] and walked["first_cell"][0] == pytest.approx(1e-3)


def test_the_record_keeps_the_first_cell(tmp_path: Path) -> None:
    fc = FirstCell(mean_m=3e-3, p95_m=4e-3, planned_m=1e-3)
    write_mesh_record(tmp_path, MeshRecord(_report(fc), "h", ("wall",)))
    assert read_mesh_record(tmp_path).report.first_cell == fc
    write_mesh_record(tmp_path, MeshRecord(_report(None), "h", ("wall",)))  # relative sizing: not measured
    assert read_mesh_record(tmp_path).report.first_cell is None


@needs_openfoam
def test_the_mesh_run_measures_after_check_mesh(tmp_path: Path) -> None:
    write_column(tmp_path, [0.05, 0.05])
    steps = (("checkMesh", ["echo", "Mesh OK."]),)
    run = MeshRun(tmp_path, steps=steps, parts=("wall",), first_layer=(1e-3, 5), step_timeout_s=60)
    run.start()
    result = run.wait()
    assert result.success and result.report.first_cell.mean_m == pytest.approx(0.05)
    assert "Layers collapsed near the wall" in result.report.first_cell_warning()
    plain = MeshRun(tmp_path, steps=steps, parts=("wall",), step_timeout_s=60)  # relative sizing: no measure
    plain.start()
    assert plain.wait().report.first_cell is None
