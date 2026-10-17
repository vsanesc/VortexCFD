"""Residual series from a REAL simpleFoam log, and forceCoeffs / yPlus parsing from REAL output files
(tests/data/sphere_run/, described in tests/data/README.md)."""

import shutil
from pathlib import Path

import pytest

from vortexcfd.foam.logparse import TimeStep, parse_log_text
from vortexcfd.foam.postprocessing import (
    FORCE_COEFFS,
    FORCE_COEFFS_FILE,
    YPLUS,
    YPLUS_FILE,
    ForceCoeffsTail,
    ReportMonitor,
    TailReader,
    YPlusTail,
    output_file,
)
from vortexcfd.foam.residuals import ResidualHistory, decimate

RUN = Path(__file__).parent / "data" / "sphere_run"


# -- residual series -----------------------------------------------------------------------------------


def test_residual_series_from_the_real_log() -> None:
    parser = parse_log_text((RUN / "log.simpleFoam").read_text())
    history = ResidualHistory()
    history.extend(parser)
    assert list(history.series) == ["Ux", "Uy", "Uz", "p", "omega", "k"]
    assert all(len(s) == 20 for s in history.series.values())
    assert [t for t, _ in history.series["p"]] == [float(i) for i in range(1, 21)]
    # Time = 20 in the log: Ux 0.00532555, p 0.0064349, k 0.000659443
    assert history.series["Ux"][-1] == (20.0, 0.00532555)
    assert history.series["p"][-1] == (20.0, 0.0064349)
    assert history.series["k"][-1] == (20.0, 0.000659443)
    assert history.series["p"][0][1] == 1.0  # the first p residual is normalised to 1
    assert history.last_iteration == 20.0


def test_first_solve_per_iteration_and_unplottable_values() -> None:
    history = ResidualHistory()
    history.add(TimeStep(1.0, residuals=[("p", 0.5, 0.01, 3), ("p", 0.2, 0.01, 3), ("k", 0.0, 0.0, 1),
                                         ("omega", float("nan"), 0.0, 1)]))
    assert history.series == {"p": [(1.0, 0.5)]}


def test_decimation_bounds_points_and_keeps_extremes() -> None:
    points = [(float(i), 1.0 / (i + 1)) for i in range(10_000)]
    points[5000] = (5000.0, 10.0)  # a spike
    out = decimate(points, 2000)
    assert len(out) <= 2000 and out[0] == points[0] and out[-1] == points[-1]
    assert (5000.0, 10.0) in out
    assert [p[0] for p in out] == sorted(p[0] for p in out)
    short = points[:100]
    assert decimate(short, 2000) == short
    history = ResidualHistory()
    for i in range(1, 5001):
        history.add(TimeStep(float(i), residuals=[("p", 1.0 / i, 0.0, 1)]))
    assert len(history.decimated()["p"]) <= 2000


# -- forceCoeffs ------------------------------------------------------------------------------------------


def test_force_coeffs_columns_and_values_from_the_real_file() -> None:
    tail = ForceCoeffsTail(RUN / FORCE_COEFFS_FILE)
    assert tail.poll() == 20
    assert tail.columns == ["Cd", "Cd(f)", "Cd(r)", "Cl", "Cl(f)", "Cl(r)", "CmPitch", "CmRoll", "CmYaw",
                            "Cs", "Cs(f)", "Cs(r)"]
    assert tail.series["Cd"][0] == (1.0, 2.135677)
    assert tail.series["Cl"][0] == (1.0, -0.06637064)
    assert tail.series["CmPitch"][0] == (1.0, 4.159671e-06)
    assert len(tail.series["Cd"]) == 20 and tail.series["Cd"][-1][0] == 20.0
    assert tail.poll() == 0  # nothing new


def test_force_coeffs_tail_tolerates_a_partial_last_line(tmp_path: Path) -> None:
    text = (RUN / FORCE_COEFFS_FILE).read_text()
    lines = text.splitlines(keepends=True)
    header = [l for l in lines if l.startswith("#")]
    rows = [l for l in lines if not l.startswith("#")]
    path = tmp_path / FORCE_COEFFS_FILE
    path.write_text("".join(header) + rows[0] + rows[1][:25])  # row 2 is half written
    tail = ForceCoeffsTail(path)
    assert tail.poll() == 1 and len(tail.series["Cd"]) == 1
    with open(path, "a") as fh:
        fh.write(rows[1][25:] + rows[2])
    assert tail.poll() == 2
    assert [t for t, _ in tail.series["Cd"]] == [1.0, 2.0, 3.0]
    assert tail.series["Cd"][1][1] == pytest.approx(1.404513)


def test_tail_reader_restarts_on_a_replaced_file(tmp_path: Path) -> None:
    path = tmp_path / "f.dat"
    reader = TailReader(path)
    assert reader.read_lines() == []  # missing file
    path.write_text("a\nb\n")
    assert reader.read_lines() == ["a", "b"]
    path.write_text("c\n")  # shorter: a new run replaced it
    assert reader.read_lines() == ["c"]


# -- yPlus ---------------------------------------------------------------------------------------------------


def test_yplus_rows_from_the_real_file() -> None:
    tail = YPlusTail(RUN / YPLUS_FILE)
    assert tail.poll() == 2
    assert tail.rows[20.0] == {"Sphere": (7.312778, 275.6301, 172.1799)}
    assert tail.series("min") == [(10.0, 8.662008), (20.0, 7.312778)]
    assert tail.series("max")[-1] == (20.0, 275.6301)
    assert tail.series("average")[-1] == (20.0, 172.1799)


def test_yplus_combines_several_wall_patches_without_counts(tmp_path: Path) -> None:
    path = tmp_path / YPLUS_FILE
    path.write_text("# y+ ()\n# Time\tpatch\tmin\tmax\taverage\n"
                    "5\tWing\t1\t50\t20\n5\tTail\t0.5\t30\t10\n7\tWing\t2")  # last row partial
    tail = YPlusTail(path)
    assert tail.poll() == 2
    assert tail.series("min") == [(5.0, 0.5)] and tail.series("max") == [(5.0, 50.0)]
    assert tail.series("average") == [(5.0, 15.0)]  # mean of the patch averages


# -- report monitor on a case layout ---------------------------------------------------------------------------


def test_report_monitor_finds_the_files_in_the_case(tmp_path: Path) -> None:
    case = tmp_path / "case"
    monitor = ReportMonitor(case)
    assert not monitor.poll() and monitor.series("Cd") == [] and monitor.series("yplus_avg") == []
    (case / "postProcessing" / FORCE_COEFFS / "0").mkdir(parents=True)
    (case / "postProcessing" / YPLUS / "0").mkdir(parents=True)
    shutil.copy(RUN / FORCE_COEFFS_FILE, case / "postProcessing" / FORCE_COEFFS / "0")
    shutil.copy(RUN / YPLUS_FILE, case / "postProcessing" / YPLUS / "0")
    assert output_file(case, FORCE_COEFFS, FORCE_COEFFS_FILE).parent.name == "0"
    assert monitor.poll()
    assert monitor.series("Cd")[-1][0] == 20.0 and monitor.series("Cl")[0][1] == pytest.approx(-0.06637064)
    assert monitor.series("CmPitch")[0][1] == pytest.approx(4.159671e-06)
    assert monitor.series("yplus_min")[-1] == (20.0, 7.312778)
    assert monitor.series("yplus_avg")[-1] == (20.0, 172.1799)
    with pytest.raises(KeyError):
        monitor.series("bogus")


# -- y+ across several walls (real two-wall run, tests/data/two_walls/) ---------------------------------------

TWO = Path(__file__).parent / "data" / "two_walls"


def test_patch_face_counts_from_the_real_boundary_file(tmp_path: Path) -> None:
    from vortexcfd.foam.postprocessing import patch_face_counts

    case = tmp_path / "case"
    (case / "constant" / "polyMesh").mkdir(parents=True)
    assert patch_face_counts(case) == {}  # no boundary file
    shutil.copy(TWO / "boundary", case / "constant" / "polyMesh" / "boundary")
    counts = patch_face_counts(case)
    assert counts["Ball"] == 2032 and counts["Pod"] == 856 and set(counts) >= {"inlet", "outlet", "sides"}


def test_yplus_aggregation_over_two_real_walls_is_face_weighted(tmp_path: Path) -> None:
    """min of the minima, max of the maxima, and the face-count-weighted average, which equals the
    mean over all wall faces of the real yPlus field written at the same time."""
    import numpy as np

    from vortexcfd.foam.dictfile import read_foam_file

    case = tmp_path / "case"
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "postProcessing" / YPLUS / "0").mkdir(parents=True)
    shutil.copy(TWO / "boundary", case / "constant" / "polyMesh" / "boundary")
    shutil.copy(TWO / YPLUS_FILE, case / "postProcessing" / YPLUS / "0")
    monitor = ReportMonitor(case)
    assert monitor.poll()
    field = read_foam_file(TWO / "yPlus")["boundaryField"]
    ball, pod = np.asarray(field["Ball"]["value"]), np.asarray(field["Pod"]["value"])
    all_faces = np.concatenate([ball, pod])
    assert monitor.series("yplus_min") == [(10.0, 28.7742)]
    assert monitor.series("yplus_max") == [(10.0, 1185.594)]
    # the field is written with writePrecision 6, the .dat file with 7 digits
    assert min(ball.min(), pod.min()) == pytest.approx(28.7742, rel=1e-5)
    assert max(ball.max(), pod.max()) == pytest.approx(1185.594, rel=1e-5)
    (t, avg), = monitor.series("yplus_avg")
    assert avg == pytest.approx((2032 * 353.1563 + 856 * 206.1641) / (2032 + 856))
    assert avg == pytest.approx(all_faces.mean(), rel=1e-5)
    plain = (353.1563 + 206.1641) / 2  # the unweighted mean would be about 10 % high
    assert abs(plain - avg) / avg > 0.05


def test_yplus_average_falls_back_without_face_counts(tmp_path: Path) -> None:
    tail = YPlusTail(TWO / YPLUS_FILE)
    tail.poll()
    assert tail.series("average") == [(10.0, pytest.approx((353.1563 + 206.1641) / 2))]
    assert tail.series("average", {"Ball": 2032}) == tail.series("average")  # Pod missing: plain mean
