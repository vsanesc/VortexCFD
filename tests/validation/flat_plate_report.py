"""Flat plate result files: residual and Cf CSVs, the Case B grid study (Celik GCI against the TMR
reference), and the generated tables of docs/validation/flat_plate/README.md.

Shared by the pytest validation (tests/validation/test_flat_plate.py) and the full study
(scripts/validation/flat_plate_study.py).
"""

import csv
import json
import re
from pathlib import Path

import numpy as np

from tests.validation import tmr
from tests.validation.flat_plate_case import (
    CASE_B_GRIDS,
    PlateCase,
    PlateResult,
    boundary_layer_cells,
    cf_at,
    laws,
)
from vortexcfd.foam.logparse import LogParser

OUT = Path(__file__).resolve().parents[2] / "docs" / "validation" / "flat_plate"
STUDY_JSON = "case_b_grid_study.json"  # the committed full study (fine grid included)
DISTRIBUTION_RANGE = (0.1, 1.9)  # x range of the Cf(x) comparison with the TMR distribution


def write_artifacts(out: Path, tag: str, case: PlateCase, result: PlateResult) -> None:
    """case_<tag>_residuals.csv (initial residuals per iteration) and case_<tag>_cf_comparison.csv."""
    out.mkdir(parents=True, exist_ok=True)
    parser = LogParser()
    for line in (case.case_dir / "log.simpleFoam").read_text().splitlines():
        parser.feed(line)
    fields = ["Ux", "Uz", "p", "k", "omega"]  # y is the empty direction
    with open(out / f"case_{tag}_residuals.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["iteration", *[f"initial_residual_{f}" for f in fields]])
        for step in parser:
            first = {name: init for name, init, _, _ in reversed(step.residuals)}
            writer.writerow([int(step.time), *[f"{first.get(f, float('nan')):.6g}" for f in fields]])
    re_x, power, white = laws(result.x, case.setup)
    tmr_columns = tag == "B"  # the TMR distribution is for Case B's Reynolds number only
    x_tmr, cf_tmr = (np.asarray(v) for v in tmr.cf_plate("CFL3D"))
    ref = np.interp(result.x, x_tmr, cf_tmr)  # TMR CFL3D (compressible, finest grid)
    with open(out / f"case_{tag}_cf_comparison.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["x_m", "Re_x", "Cf_simulation",
                         *(["Cf_TMR_CFL3D", "error_vs_TMR_CFL3D"] if tmr_columns else []),
                         "Cf_0.0592_Re^-0.2", "error_vs_0.0592",
                         "Cf_0.455_ln2(0.06Re)", "error_vs_0.455_ln2", "yplus_first_cell"])
        for x, r, cf, t, c, w, yp in zip(result.x, re_x, result.cf, ref, power, white, result.yplus):
            writer.writerow([f"{x:.4f}", f"{r:.6g}", f"{cf:.6g}",
                             *([f"{t:.6g}", f"{(cf - t) / t:+.4f}"] if tmr_columns else []),
                             f"{c:.6g}", f"{(cf - c) / c:+.4f}", f"{w:.6g}", f"{(cf - w) / w:+.4f}", f"{yp:.4f}"])


def grid_row(case: PlateCase, result: PlateResult) -> dict:
    """One grid of the study: resolution, y+ and boundary-layer cells at X_REF, Cf(X_REF), cost."""
    i = int(np.argmin(np.abs(result.x - tmr.X_REF)))
    delta, cells = boundary_layer_cells(case, tmr.X_REF)
    _, reference = tmr.incompressible_reference()
    cf = cf_at(result, tmr.X_REF)
    return {"cells_normal": case.setup.cells_normal, "first_cell_m": case.first_cell,
            "expansion": case.expansion, "yplus_0.97": float(result.yplus[i]),
            "delta99_m": delta, "cells_in_delta99": cells, "cf_0.97": cf,
            "error": (cf - reference) / reference, "iterations": result.iterations,
            "converged": result.converged, "wall_time_s": result.wall_time_s}


def grid_study(rows: list[dict]) -> dict:
    """Celik GCI of Cf(X_REF) over three grid rows (coarse first) and the error of the extrapolated
    value against the TMR incompressible reference."""
    fine, medium, coarse = (r["cf_0.97"] for r in reversed(rows))
    gci = tmr.celik_gci(fine, medium, coarse, 2.0, 2.0)
    finest_ref, reference = tmr.incompressible_reference()
    error = (gci.extrapolated - reference) / reference
    return {"grids": rows, "order": gci.order, "monotonic": gci.convergence == "monotonic",
            "extrapolated": gci.extrapolated, "gci_fine": gci.gci_fine,
            "approx_error": gci.approx_error, "extrapolated_error": gci.extrapolated_error,
            "reference": reference, "reference_finest_grids": finest_ref,
            "error": error, "error_fine_grid": rows[-1]["error"], "verdict": tmr.verdict(error)}


def distribution_error(result: PlateResult) -> dict:
    """Cf(x) against the TMR CFL3D distribution (compressible, finest grid) and White's law for x in
    DISTRIBUTION_RANGE."""
    x_ref, cf_ref = (np.asarray(v) for v in tmr.cf_plate("CFL3D"))
    mask = (result.x > DISTRIBUTION_RANGE[0]) & (result.x < DISTRIBUTION_RANGE[1])
    ref = np.interp(result.x[mask], x_ref, cf_ref)
    err = (result.cf[mask] - ref) / ref
    _, _, white = laws(result.x[mask], CASE_B_GRIDS[-1])
    err_white = (result.cf[mask] - white) / white
    return {"faces": int(mask.sum()), "mean_abs": float(np.abs(err).mean()), "max_abs": float(np.abs(err).max()),
            "mean_signed": float(err.mean()), "white_mean_abs": float(np.abs(err_white).mean()),
            "white_max_abs": float(np.abs(err_white).max())}


def load_study(out: Path = OUT) -> dict:
    return json.loads((out / STUDY_JSON).read_text())


def write_study(out: Path, study: dict) -> None:
    """case_b_grid_study.json and case_b_grid_study.csv (one row per grid)."""
    out.mkdir(parents=True, exist_ok=True)
    (out / STUDY_JSON).write_text(json.dumps(study, indent=2) + "\n")
    keys = list(study["grids"][0])
    with open(out / "case_b_grid_study.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["grid", *keys])
        for i, row in enumerate(study["grids"], 1):
            writer.writerow([i, *[f"{row[k]:.6g}" if isinstance(row[k], float) else row[k] for k in keys]])


def _pct(v: float) -> str:
    return f"{v:+.2%}".replace("%", " %")


def study_tables(study: dict) -> str:
    """Markdown tables of the grid study (the README's generated block)."""
    names = {0: "1 (coarse)", len(study["grids"]) - 1: f"{len(study['grids'])} (fine)"}
    lines = ["| Grid | Wall-normal cells | First cell [m] | Expansion ratio | y+ (x 0.97) | delta99 [mm] | "
             "Cells in delta99 | Cf(0.97) | Error vs reference | Iterations / time |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(study["grids"]):
        lines.append(f"| {names.get(i, i + 1)} | {r['cells_normal']} | {r['first_cell_m']:.4g} | {r['expansion']:.4f} | "
                     f"{r['yplus_0.97']:.3f} | {1000 * r['delta99_m']:.1f} | {r['cells_in_delta99']} | "
                     f"{r['cf_0.97']:.4e} | {_pct(r['error'])} | {r['iterations']} / {r['wall_time_s']:.0f} s |")
    lines += ["", "| Quantity | Value |", "|---|---|",
              f"| Observed order p | {study['order']:.2f} ({'monotonic' if study['monotonic'] else 'oscillatory'} convergence) |",
              f"| Extrapolated Cf(0.97) | {study['extrapolated']:.4e} |",
              f"| e_a^21 / e_ext^21 | {study['approx_error']:.3%} / {study['extrapolated_error']:.3%} |".replace("%", " %"),
              f"| GCI_fine^21 | {study['gci_fine']:.3%} |".replace("%", " %"),
              f"| Reference (TMR incompressible SST, extrapolated mean) | {study['reference']:.4e} |",
              f"| **Error of the extrapolated value vs the reference** | **{_pct(study['error'])}: {study['verdict']}** |"]
    d = study.get("distribution_fine_grid")
    if d:
        lines += ["", f"Cf(x) on the finest grid, {DISTRIBUTION_RANGE[0]} < x < {DISTRIBUTION_RANGE[1]} "
                      f"({d['faces']} faces; informative):", "",
                  "| Against | Mean abs. error | Max abs. error |", "|---|---|---|",
                  f"| TMR CFL3D distribution (compressible, 545 x 385) | {d['mean_abs']:.1%} "
                  f"(mean signed {d['mean_signed']:+.1%}) | {d['max_abs']:.1%} |".replace("%", " %"),
                  f"| White 0.455 / ln^2(0.06 Re_x) | {d['white_mean_abs']:.1%} | {d['white_max_abs']:.1%} |".replace("%", " %")]
    return "\n".join(lines)


def k_wall_table(study: dict) -> str:
    lines = ["| k wall BC | Cf(0.97) | Error vs reference | Iterations |", "|---|---|---|---|"]
    for name, r in study["k_wall"].items():
        lines.append(f"| {name} | {r['cf_0.97']:.6e} | {r['error']:+.3%} | {r['iterations']} |".replace("%", " %"))
    return "\n".join(lines)


def replace_block(text: str, name: str, body: str) -> str:
    """Replace the README block between <!-- BEGIN generated: name --> and <!-- END generated: name -->."""
    pattern = re.compile(rf"(<!-- BEGIN generated: {re.escape(name)} -->\n).*?(<!-- END generated: {re.escape(name)} -->)",
                         re.DOTALL)
    if not pattern.search(text):
        raise ValueError(f"README has no generated block {name!r}")
    return pattern.sub(lambda m: m.group(1) + body + "\n" + m.group(2), text)
