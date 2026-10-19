"""The meshing benchmark's metric code (D-082) on small fixtures: captured checkMesh and
snappyHexMesh logs, a one-cell case with layer fields, distances to a known shape, the comparison
rules. No OpenFOAM run."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from vortexcfd.bench import metrics, report
from vortexcfd.bench.runner import LAYER_FIELDS, _read_patches

DATA = Path(__file__).parent / "data"


# -- checkMesh and snappyHexMesh logs ----------------------------------------------------------------

def test_check_mesh_quality_of_a_passing_mesh() -> None:
    q = metrics.parse_check_mesh_quality((DATA / "checkMesh_sphere_snappy.log").read_text())
    assert q["max_non_ortho"] == pytest.approx(28.943653) and q["avg_non_ortho"] == pytest.approx(10.907735)
    assert q["max_skewness"] == pytest.approx(0.4556289) and q["faces_skew_gt4"] == 0
    assert q["max_aspect_ratio"] == pytest.approx(2.077818)
    assert q["faces_non_ortho_gt70_checkmesh"] == 0
    assert q["mesh_ok"] and q["failed_checks"] == 0 and q["failed_by_type"] == {}


def test_check_mesh_quality_of_a_failing_mesh() -> None:
    q = metrics.parse_check_mesh_quality((DATA / "bench" / "checkMesh_failed.log").read_text())
    # A sheared block with three points moved across their neighbours (tests/data/bench/README.md).
    assert not q["mesh_ok"] and q["failed_checks"] == 5
    assert q["max_non_ortho"] == pytest.approx(125.43245) and q["avg_non_ortho"] == pytest.approx(69.090425)
    assert q["faces_non_ortho_gt70_checkmesh"] == 159 + 24  # severe (70-90) plus errors (above 90)
    assert q["max_skewness"] == pytest.approx(4.7046) and q["faces_skew_gt4"] == 36
    assert q["max_aspect_ratio"] == pytest.approx(2.8680969e99)
    assert q["failed_by_type"] == {"High aspect ratio cells found": 1, "Zero or negative cell volume detected": 1,
                                   "Number of non-orthogonality errors": 1, "Error in face pyramids": 1,
                                   "Max skewness": 1}


def test_failed_check_types() -> None:
    assert metrics.failed_check_type(" ***Max skewness = 5.1, 12 highly skew faces detected") == "Max skewness"
    assert metrics.failed_check_type(" ***Zero or negative cell volume detected.  Minimum") == \
        "Zero or negative cell volume detected"
    assert metrics.failed_check_type(" ***Error in face pyramids: 4 faces are incorrectly oriented.") == \
        "Error in face pyramids"
    assert metrics.failed_check_type(" ***High aspect ratio cells found, Max aspect ratio: 1203") == \
        "High aspect ratio cells found"


def test_snappy_stage_times() -> None:
    t = metrics.snappy_stage_times((DATA / "snappyHexMesh_sphere_default.log").read_text())
    assert t == {"castellation": 8.75, "snap": 11.54, "layers": 2.93, "snappy_total": 24.18}
    assert metrics.snappy_stage_times("nothing") == {"castellation": None, "snap": None, "layers": None,
                                                     "snappy_total": None}


def test_two_run_stage_times(tmp_path: Path) -> None:
    """With seeded parts the castellation comes from the castellation-only run and the totals add up
    (D-084); a single run reads as before."""
    from vortexcfd.bench.runner import snappy_stages

    (tmp_path / "log.snappyHexMesh").write_text((DATA / "snappyHexMesh_sphere_default.log").read_text())
    assert snappy_stages(tmp_path) == {"castellation": 8.75, "snap": 11.54, "layers": 2.93, "snappy_total": 24.18}
    (tmp_path / "log.snappyHexMesh.castellate").write_text("Mesh refined in = 15.62 s.\nFinished meshing in = 16.5 s.\n")
    (tmp_path / "log.snappyHexMesh").write_text("Mesh snapped in = 14.37 s.\nLayers added in = 9.62 s.\n"
                                                 "Finished meshing in = 25.76 s.\n")
    t = snappy_stages(tmp_path)
    assert t["castellation"] == 15.62 and t["snap"] == 14.37 and t["layers"] == 9.62
    assert t["snappy_total"] == pytest.approx(42.26)


def test_face_field_reader_and_counts() -> None:
    text = "FoamFile{}\ndimensions [];\ninternalField   nonuniform List<scalar> \n5\n(\n10\n66\n70\n70.5\n89\n)\n;\n"
    values = metrics.read_scalar_list_field(text)
    assert values.tolist() == [10, 66, 70, 70.5, 89]
    assert metrics.count_above(values, (65, 70)) == {"65": 4, "70": 2}
    assert metrics.read_scalar_list_field("internalField uniform 3;").tolist() == [3.0]
    with pytest.raises(ValueError):
        metrics.read_scalar_list_field("internalField   nonuniform List<scalar> 3 (1 2);")


# -- layers and zones --------------------------------------------------------------------------------

def test_layer_stats_are_area_weighted() -> None:
    area = np.array([1.0, 1.0, 2.0])
    s = metrics.layer_stats(area, np.array([3, 0, 1]), np.array([0.03, 0.0, 0.02]), np.array([1.0, 0.0, 0.5]), 3)
    assert s["coverage_percent"] == pytest.approx(25.0)  # the full stack of 3 layers
    assert s["extruded_percent"] == pytest.approx(75.0)  # at least one layer
    assert s["mean_layers"] == pytest.approx(1.25)
    assert s["mean_thickness_m"] == pytest.approx((0.03 + 0.04) / 4)
    assert s["thickness_percent"] == pytest.approx(50.0)
    empty = metrics.layer_stats(np.array([]), np.array([]), np.array([]), np.array([]), 3)
    assert empty["coverage_percent"] is None and empty["faces"] == 0


def test_zone_mask_boxes_and_segments() -> None:
    c = np.array([[0.0, 0, 0], [0.97, 1, 0], [0.5, 0.01, 0.0], [0.5, 1.0, 0.5]])
    assert metrics.zone_mask(c, boxes=((0.95, 9, -9, 9, -9, 9),)).tolist() == [False, True, False, False]
    seg = (((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),)
    assert metrics.zone_mask(c, segments=seg, width=0.02).tolist() == [True, False, True, False]
    d = metrics.point_segment_distance(np.array([[2.0, 0, 0], [0.5, 3, 4]]), (0, 0, 0), (1, 0, 0))
    assert d.tolist() == pytest.approx([1.0, 5.0])
    assert metrics.low_coverage({"a": {"coverage_percent": 79.9}, "b": {"coverage_percent": 80.0},
                                 "c": {"coverage_percent": None}}) == ["a"]


def _write_one_cell_case(case: Path) -> None:
    """A unit cube as one hex cell: patch "body" = the x faces, "outer" = the other four, and the
    snappyHexMesh layer fields with values on "body" (3 layers on x = 0, none on x = 1)."""
    header = "FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class {cls};\n    object {obj};\n}}\n"
    mesh = case / "constant" / "polyMesh"
    mesh.mkdir(parents=True)
    pts = "8\n(\n(0 0 0)\n(1 0 0)\n(1 1 0)\n(0 1 0)\n(0 0 1)\n(1 0 1)\n(1 1 1)\n(0 1 1)\n)\n"
    faces = "6\n(\n4(0 4 7 3)\n4(1 2 6 5)\n4(0 1 5 4)\n4(3 7 6 2)\n4(0 3 2 1)\n4(4 5 6 7)\n)\n"
    (mesh / "points").write_text(header.format(cls="vectorField", obj="points") + pts)
    (mesh / "faces").write_text(header.format(cls="faceList", obj="faces") + faces)
    (mesh / "owner").write_text(header.format(cls="labelList", obj="owner") + "6\n(\n0 0 0 0 0 0\n)\n")
    (mesh / "neighbour").write_text(header.format(cls="labelList", obj="neighbour") + "0\n(\n)\n")
    (mesh / "boundary").write_text(header.format(cls="polyBoundaryMesh", obj="boundary") +
                                   "2\n(\nbody\n{\n type wall;\n nFaces 2;\n startFace 0;\n}\n"
                                   "outer\n{\n type patch;\n nFaces 4;\n startFace 2;\n}\n)\n")
    zero = case / "0"
    zero.mkdir()
    values = {"nSurfaceLayers": "(3 0)", "thickness": "(0.03 0)", "thicknessFraction": "(1 0)"}
    for name, body in values.items():
        (zero / name).write_text(
            header.format(cls="volScalarField", obj=name) + "dimensions [0 0 0 0 0 0 0];\ninternalField uniform 0;\n"
            f"boundaryField\n{{\n body\n {{\n  type fixedValue;\n  value nonuniform List<scalar> 2{body};\n }}\n"
            " outer\n {\n  type fixedValue;\n  value uniform 0;\n }\n}\n")
    system = case / "system"
    system.mkdir()
    (system / "controlDict").write_text(header.format(cls="dictionary", obj="controlDict") +
                                        "application none;\nstartTime 0;\nendTime 1;\ndeltaT 1;\n")
    (case / "case.foam").touch()


def test_layer_fields_are_read_per_wall_face(tmp_path: Path) -> None:
    _write_one_cell_case(tmp_path)
    blocks = _read_patches(tmp_path, ("body",), 0.0, LAYER_FIELDS)
    assert list(blocks) == ["body"]
    body = blocks["body"]
    assert body.n_cells == 2 and np.asarray(body.cell_data["Area"]) == pytest.approx([1.0, 1.0])
    x = np.asarray(body.cell_centers().points)[:, 0]
    n = np.asarray(body.cell_data["nSurfaceLayers"])
    assert n[np.argmin(x)] == 3 and n[np.argmax(x)] == 0  # OpenFOAM's face order is kept
    s = metrics.layer_stats(np.asarray(body.cell_data["Area"]), n, np.asarray(body.cell_data["thickness"]),
                            np.asarray(body.cell_data["thicknessFraction"]), 3)
    assert s["coverage_percent"] == 50.0 and s["extruded_percent"] == 50.0
    assert s["mean_layers"] == 1.5 and s["thickness_percent"] == 50.0


# -- fidelity and y+ ---------------------------------------------------------------------------------

def test_sphere_distance_and_fidelity() -> None:
    dist = metrics.sphere_distance((1.0, 0.0, 0.0), 0.5)
    pts = np.array([[1.5, 0, 0], [1.0, 0.6, 0], [1.0, 0, -0.45], [1.0, 0.0, 0.0]])
    assert dist(pts) == pytest.approx([0.0, 0.1, 0.05, 0.5])
    f = metrics.fidelity(np.array([0.0, 0.03, 0.04]), 2.0)
    assert f["max_rel"] == pytest.approx(0.02) and f["rms_rel"] == pytest.approx(np.sqrt(0.0025 / 3) / 2)
    assert metrics.fidelity(np.array([]), 1.0)["rms_rel"] is None


def test_yplus_stats() -> None:
    s = metrics.yplus_stats(np.array([0.4, 1.0, 2.0, 5.0]), np.array([1.0, 1.0, 1.0, 2.0]), 1.0)
    assert s["min"] == 0.4 and s["max"] == 5.0
    assert s["mean"] == pytest.approx((0.4 + 1 + 2 + 10) / 5)
    assert s["in_band_percent"] == pytest.approx(40.0) and s["band"] == [0.5, 2.0]


# -- result files and comparison ---------------------------------------------------------------------

def _result(**over) -> dict:
    case = {"case": "wing", "cells": 100_000, "failed": False, "reference_length": 1.0,
            "quality": {"max_non_ortho": 60.0, "avg_non_ortho": 5.0, "faces_non_ortho_gt70": 2},
            "layers": {"walls": {"coverage_percent": 90.0}, "fidelity": {"rms_rel": 1e-4},
                       "zones": {"tips": {"coverage_percent": 70.0, "description": "tips"}}},
            "robustness": {"lost_parts": []}, "time_s": {"case_total": 100.0}}
    for key, value in over.items():
        target, *path = key.split("__")
        d = case
        for p in path[:-1] if path else []:
            d = d[p]
        d[path[-1] if path else target] = value
    return {"meta": {"cases": ["wing"]}, "cases": [case]}


def test_compare_flags_each_rule() -> None:
    old = _result()
    assert report.compare(old, _result())[1:] == ([], [])
    new = _result()
    c = new["cases"][0]
    c["layers"]["walls"]["coverage_percent"] = 87.5  # -2.5 points
    c["layers"]["zones"]["tips"]["coverage_percent"] = 67.0  # -3 points
    c["quality"]["max_non_ortho"] = 62.5  # +2.5 degrees
    c["quality"]["faces_non_ortho_gt70"] = 3  # one more
    c["cells"] = 111_000  # +11 %
    c["layers"]["fidelity"]["rms_rel"] = 1.11e-4  # +11 %
    c["time_s"]["case_total"] = 130.0  # +30 %: flag only
    _deltas, regressions, flags = report.compare(old, new)
    assert len(regressions) == 6 and len(flags) == 1
    assert any("strict layer coverage dropped 2.5" in r for r in regressions)
    assert any("zone tips" in r for r in regressions)
    assert "time is noisy" in flags[0]
    small = _result()
    small["cases"][0]["layers"]["walls"]["coverage_percent"] = 88.5  # -1.5 points: within the rule
    small["cases"][0]["cells"] = 109_000
    assert report.compare(old, small)[1] == []


def test_headline_coverage_is_strict_and_a_changed_stack_is_flagged() -> None:
    """D-087: the headline is the strict coverage (full target layer count), extruded is its own
    column; a different target layer count is flagged, while a coverage drop stays a regression."""
    head = report.markdown_table(_result()).splitlines()[0]
    assert "| Strict coverage % | Target layers | Extruded % |" in head
    old, new = _result(), _result()
    old["cases"][0]["layers"]["walls"]["target_layers"] = 3
    new["cases"][0]["layers"]["walls"].update(target_layers=10, coverage_percent=50.0)
    _deltas, regressions, flags = report.compare(old, new)
    assert any("target layer count 3 -> 10" in f for f in flags)
    assert any("strict layer coverage dropped 40.0" in r for r in regressions)


def test_compare_flags_failed_lost_and_missing_cases() -> None:
    old = _result()
    lost = _result()
    lost["cases"][0]["robustness"]["lost_parts"] = ["wing"]
    assert any("lost" in r for r in report.compare(old, lost)[1])
    failed = _result()
    failed["cases"][0]["failed"] = True
    assert any("failed" in r for r in report.compare(old, failed)[1])
    missing = {"meta": {"cases": ["wing"]}, "cases": []}
    assert any("missing" in r for r in report.compare(old, missing)[1])


def test_markdown_table_and_cli_compare(tmp_path: Path) -> None:
    old, new = _result(), _result()
    new["cases"][0]["cells"] = 200_000
    table = report.markdown_table(new)
    assert table.splitlines()[0].startswith("| Case | Status | Cells") and "200000" in table
    (tmp_path / "old.json").write_text(json.dumps(old))
    (tmp_path / "new.json").write_text(json.dumps(new))
    run = subprocess.run([sys.executable, "-m", "vortexcfd.bench", "--result", str(tmp_path / "new.json"),
                          "--compare", str(tmp_path / "old.json")], capture_output=True, text=True)
    assert run.returncode == 1 and "REGRESSION wing: cells up 100.0 %" in run.stdout
    same = subprocess.run([sys.executable, "-m", "vortexcfd.bench", "--result", str(tmp_path / "old.json"),
                           "--compare", str(tmp_path / "old.json")], capture_output=True, text=True)
    assert same.returncode == 0 and "no regressions" in same.stdout


def test_the_benchmark_never_loads_qt() -> None:
    code = ("import sys, vortexcfd.bench.cli, vortexcfd.bench.runner; "
            "print(any(m.split('.')[0] in ('PySide6', 'pyvistaqt') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_layer_diagnostics_per_area() -> None:
    """D-091: mean / target, the share with at least 80 % of the target count, the share with none and
    the area per layer count."""
    area = np.array([1.0, 1.0, 1.0, 1.0])
    n = np.array([10, 8, 5, 0])
    s = metrics.layer_stats(area, n, np.ones(4), np.ones(4), 10)
    assert s["mean_over_target_percent"] == pytest.approx(57.5)
    assert s["near_full_percent"] == pytest.approx(50.0)  # 10 and 8 layers of 10
    assert s["zero_layers_percent"] == pytest.approx(25.0)
    assert s["layers_area_percent"] == {"0": 25.0, "5": 25.0, "8": 25.0, "10": 25.0}


LAYER_LOG = """Snapping
Moving mesh using displacement scaling : min:1 max:1
Checking faces in error :
    non-orthogonality > 65  degrees                        : 7
Shrinking and layer addition phase
----------------------------------
Handling feature edges (angle < 60) ...
Set displacement to zero for points on 668 feature edges
Layer addition iteration 0
--------------------------
displacementMedialAxis : Reducing layer thickness at 3 nodes where thickness to medial axis distance is large
displacementMedialAxis : Number of isolated points extrusion stopped : 8
Moving mesh using displacement scaling : min:1 max:1
Checking faces in error :
    non-orthogonality > 65  degrees                        : 441
    faces with face twist < 0.02                           : 0
    faces on cells with determinant < 0.001                : 5
Moving mesh using displacement scaling : min:0.75 max:1
Checking faces in error :
    non-orthogonality > 65  degrees                        : 12
Checking mesh with layer ...
Checking faces in error :
    non-orthogonality > 65  degrees                        : 0
    faces with face twist < 0.02                           : 2
Detected 0 illegal faces (concave, zero area or negative cell pyramid volume)
Extruding 11540 out of 11560 faces (99.82699%). Removed extrusion at 2 faces.
Layer addition iteration 1
Checking mesh with layer ...
Detected 0 illegal faces (concave, zero area or negative cell pyramid volume)
Extruding 11538 out of 11560 faces (99.8%). Removed extrusion at 0 faces.
"""


def test_layer_log_diagnostics() -> None:
    d = metrics.layer_log_diagnostics(LAYER_LOG)
    assert (d["layer_iterations"], d["removed_by_quality"]) == (2, 2)
    assert d["layer_check_errors"] == {"faces with face twist < 0.02": 2}
    # the snapping phase's errors (before the layer phase) are not counted
    assert d["shrink_errors"] == {"non-orthogonality > 65 degrees": 441, "faces on cells with determinant < 0.001": 5}
    assert d["shrink_scaling_steps"] == 2
    assert (d["feature_edges_zero_displacement"], d["isolated_points_stopped"], d["medial_axis_reduced_nodes"]) == (668, 8, 3)
    assert (d["extruded_faces"], d["total_faces"]) == (11538, 11560)
    assert metrics.layer_log_diagnostics("nothing")["removed_by_quality"] == 0


def test_fidelity_in_metres_and_like_for_like_comparison() -> None:
    f = metrics.fidelity(np.array([0.001, 0.002]), 2.0)
    assert (f["max_m"], f["reference_m"], f["max_rel"]) == (0.002, 2.0, 0.001)
    assert f["rms_m"] == pytest.approx(np.sqrt(2.5e-6))
    # an old result without metres: relative value times its reference length
    old, new = _result(), _result()
    old["cases"][0]["reference_length"] = 3.0  # relative to 3 m: 3e-4 m RMS
    new["cases"][0]["layers"]["fidelity"] = {"rms_rel": 3e-4, "max_rel": 1e-3, "rms_m": 3e-4, "max_m": 1e-3,
                                             "reference_m": 1.0}
    assert report.case_row(old["cases"][0])["fidelity_rms_m"] == pytest.approx(3e-4)
    deltas, regressions, _flags = report.compare(old, new)
    assert not any("fidelity" in r for r in regressions)  # the same RMS in metres despite a 3x relative rise
    assert "fidelity_rms_mm 0.3 -> 0.3" in deltas[0] and "(ref 3 m)" in deltas[0] and "(ref 1 m)" in deltas[0]
    head = report.markdown_table(new).splitlines()[0]
    for col in ("Mean / target %", ">=80 % of target %", "No layer %", "Layer faces removed by checks",
                "Fidelity RMS mm", "ref m", "y+ cores"):
        assert col in head
