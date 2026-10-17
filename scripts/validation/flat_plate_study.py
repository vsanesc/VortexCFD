"""Full flat plate Case B verification against the NASA TMR (D-036): the three nested wall-normal grids
(first-cell y+ about 1, 0.5, 0.25), the Celik GCI of Cf(x = 0.97), the error against the TMR
incompressible SST reference, the Cf(x) comparison with the TMR CFL3D distribution and, with --k-wall,
the k wall BC sensitivity on the finest grid (diagnostic).

    .venv/bin/python scripts/validation/flat_plate_study.py [--k-wall]

Takes about 80 min (the finest grid; the runs are concurrent single-core solvers), about 2 h with
--k-wall (five solvers).
Writes case_B_residuals.csv and case_B_cf_comparison.csv (finest grid), case_b_grid_study.json/.csv
and the generated tables of README.md under docs/validation/flat_plate/ (or --out). A case directory
under --work that already holds a finished run of exactly the same set-up (every generated file
identical) is reused instead of being run again.
"""

import argparse
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.validation import flat_plate_report as report  # noqa: E402
from tests.validation import tmr  # noqa: E402
from tests.validation.flat_plate_case import (  # noqa: E402
    CASE_B_GRIDS,
    PlateCase,
    build_plate_case,
    case_matches,
    cf_at,
    first_cell_height,
    growth_ratio,
    read_plate_result,
    run_plate_case,
)

GRID_TIMEOUT_S = 4 * 3600
K_WALL_VARIANTS = {  # k on the plate; omega and nut unchanged
    "kLowReWallFunction": {"type": "kLowReWallFunction", "value": 1e-10},
    "fixedValue 1e-10": {"type": "fixedValue", "value": 1e-10},
}


def run_job(work: Path, tag: str, setup, k_wall):
    case_dir = work / tag / "case"
    if case_matches(case_dir, setup, k_wall):
        print(f"{tag}: reusing the finished run in {case_dir}", flush=True)
        first = first_cell_height(setup)
        r = growth_ratio(first, setup.height, setup.cells_normal)
        case = PlateCase(case_dir, first, r ** (setup.cells_normal - 1), r, setup)
        return case, read_plate_result(case)
    if case_dir.exists():
        shutil.rmtree(case_dir)
    print(f"{tag}: running {setup.cells_plate + setup.cells_slip} x {setup.cells_normal} cells", flush=True)
    case = build_plate_case(case_dir, setup, k_wall=k_wall)
    result = run_plate_case(case, timeout_s=GRID_TIMEOUT_S)
    print(f"{tag}: {result.iterations} iterations, {result.wall_time_s:.0f} s", flush=True)
    return case, result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, default=ROOT / "run" / "validation" / "flat_plate_study",
                        help="case directories (default: run/validation/flat_plate_study)")
    parser.add_argument("--out", type=Path, default=report.OUT, help="result files (default: docs/validation/flat_plate)")
    parser.add_argument("--k-wall", action="store_true", help="also run the k wall BC variants on the finest grid")
    args = parser.parse_args(argv)

    jobs = {f"grid{i + 1}": (setup, None) for i, setup in enumerate(CASE_B_GRIDS)}
    if args.k_wall:
        jobs.update({"k_" + name.split()[0]: (CASE_B_GRIDS[-1], bc) for name, bc in K_WALL_VARIANTS.items()})
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        done = dict(zip(jobs, pool.map(lambda item: run_job(args.work, item[0], *item[1]), jobs.items())))

    grids = [done[f"grid{i + 1}"] for i in range(len(CASE_B_GRIDS))]
    for tag, (case, result) in done.items():
        if not result.converged:
            print(f"{tag}: residualControl not met after {result.iterations} iterations", file=sys.stderr)
            return 1
    study = report.grid_study([report.grid_row(c, r) for c, r in grids])
    study["distribution_fine_grid"] = report.distribution_error(grids[-1][1])
    if args.k_wall:
        study["k_wall"] = {}
        for name, (case, result) in [("kqRWallFunction (default)", grids[-1]),
                                     *[(n, done["k_" + n.split()[0]]) for n in K_WALL_VARIANTS]]:
            cf = cf_at(result, tmr.X_REF)
            study["k_wall"][name] = {"cf_0.97": cf, "error": (cf - study["reference"]) / study["reference"],
                                     "iterations": result.iterations}
    elif (args.out / report.STUDY_JSON).is_file():  # keep the last k wall diagnostic
        study["k_wall"] = report.load_study(args.out).get("k_wall", {})

    report.write_artifacts(args.out, "B", *grids[-1])
    report.write_study(args.out, study)
    readme = args.out / "README.md"
    if readme.is_file():
        text = report.replace_block(readme.read_text(), "grid study", report.study_tables(study))
        if study.get("k_wall"):
            text = report.replace_block(text, "k wall", report.k_wall_table(study))
        readme.write_text(text)
    print(report.study_tables(study))
    print(f"\nTotal {time.monotonic() - t0:.0f} s; results in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
