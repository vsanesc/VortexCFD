"""Benchmark result files, the Markdown table and the comparison with an earlier result (D-082)."""

import json
from pathlib import Path

# Regression rules of --compare (D-082). Time is noisy: flagged, never a failure.
COVERAGE_DROP_POINTS = 2.0
NON_ORTHO_RISE_DEG = 2.0
CELLS_RISE = 0.10
TIME_RISE = 0.25
FIDELITY_RMS_RISE = 0.10


def _get(d: dict | None, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _fmt(v, spec: str = "g") -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return format(v, spec)
    return str(v)


def worst_zone(case: dict) -> tuple[str | None, float | None]:
    zones = _get(case, "layers", "zones") or {}
    rows = [(n, z.get("coverage_percent")) for n, z in zones.items() if z.get("coverage_percent") is not None]
    return min(rows, key=lambda r: r[1]) if rows else (None, None)


def case_row(case: dict) -> dict:
    """The values of the summary table for one case."""
    zone, zone_cov = worst_zone(case)
    walls = _get(case, "layers", "walls") or {}
    thick = walls.get("mean_thickness_m")
    frac = walls.get("thickness_percent")
    return {
        "case": case.get("case"),
        "status": "FAILED" if case.get("failed") else "ok",
        "cells": case.get("cells"),
        "max_non_ortho": _get(case, "quality", "max_non_ortho"),
        "avg_non_ortho": _get(case, "quality", "avg_non_ortho"),
        "faces_gt65": _get(case, "quality", "faces_non_ortho_gt65"),
        "faces_gt70": _get(case, "quality", "faces_non_ortho_gt70"),
        "max_skewness": _get(case, "quality", "max_skewness"),
        "faces_skew_gt4": _get(case, "quality", "faces_skew_gt4"),
        "max_aspect": _get(case, "quality", "max_aspect_ratio"),
        "failed_checks": _get(case, "quality", "failed_checks"),
        "coverage": walls.get("coverage_percent"),
        "extruded": walls.get("extruded_percent"),
        "mean_layers": walls.get("mean_layers"),
        "target_layers": walls.get("target_layers"),
        "worst_zone": zone,
        "worst_zone_coverage": zone_cov,
        "thickness_m": thick,
        "thickness_percent": frac,
        "fidelity_max": _get(case, "layers", "fidelity", "max_rel"),
        "fidelity_rms": _get(case, "layers", "fidelity", "rms_rel"),
        "yplus_mean": _get(case, "yplus", "mean"),
        "yplus_in_band": _get(case, "yplus", "in_band_percent"),
        "mesh_time": _get(case, "time_s", "mesh_total"),
        "total_time": _get(case, "time_s", "case_total"),
        "lost_parts": len(_get(case, "robustness", "lost_parts") or []),
    }


TABLE_COLUMNS = (
    ("case", "Case", "s"), ("status", "Status", "s"), ("cells", "Cells", "d"),
    ("max_non_ortho", "Max non-ortho", ".1f"), ("avg_non_ortho", "Avg non-ortho", ".2f"),
    ("faces_gt65", "Faces >65", "d"), ("faces_gt70", "Faces >70", "d"),
    ("max_skewness", "Max skew", ".2f"), ("faces_skew_gt4", "Faces skew>4", "d"),
    ("max_aspect", "Max AR", ".1f"), ("failed_checks", "Failed checks", "d"),
    # headline layer metric: strict coverage, the wall area with the full target layer count (D-087)
    ("coverage", "Strict coverage %", ".1f"), ("target_layers", "Target layers", "d"),
    ("extruded", "Extruded %", ".1f"), ("mean_layers", "Mean layers", ".2f"),
    ("worst_zone", "Worst zone", "s"), ("worst_zone_coverage", "Worst zone %", ".1f"),
    ("thickness_percent", "Thickness % of target", ".1f"),
    ("fidelity_rms", "Fidelity RMS/L", ".2e"), ("fidelity_max", "Fidelity max/L", ".2e"),
    ("yplus_mean", "y+ mean", ".1f"), ("yplus_in_band", "y+ in band %", ".1f"),
    ("mesh_time", "Mesh s", ".0f"), ("total_time", "Total s", ".0f"),
)


def markdown_table(result: dict) -> str:
    rows = [case_row(c) for c in result.get("cases", [])]
    head = "| " + " | ".join(t for _, t, _ in TABLE_COLUMNS) + " |"
    sep = "|" + "|".join("---" for _ in TABLE_COLUMNS) + "|"
    lines = [head, sep]
    for r in rows:
        cells = []
        for key, _, spec in TABLE_COLUMNS:
            v = r[key]
            cells.append(_fmt(float(v), spec) if isinstance(v, (int, float)) and spec not in ("s", "d") else _fmt(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def markdown_report(result: dict) -> str:
    meta = result.get("meta", {})
    out = [f"# Meshing benchmark {meta.get('stamp', '')}", "",
           f"git {meta.get('git_sha', '?')}, {meta.get('utc', '?')} UTC, wall-clock {_fmt(meta.get('wall_s'), '.0f')} s, "
           f"{meta.get('physical_cores', '?')} physical cores.", "",
           "y+ values are indicative, not converged (a fixed short run).", "", markdown_table(result), ""]
    for case in result.get("cases", []):
        out.append(f"## {case.get('case')}")
        out.append("")
        out.append(f"- {case.get('description')}")
        if case.get("failure"):
            out.append(f"- failure: {case['failure']}")
        for line in case.get("deviations", []):
            out.append(f"- deviation: {line}")
        fb = _get(case, "quality", "failed_by_type") or {}
        if fb:
            out.append("- failed checks: " + ", ".join(f"{k} ({v})" for k, v in fb.items()))
        for name, z in (_get(case, "layers", "zones") or {}).items():
            out.append(f"- zone {name} ({z.get('description')}): coverage {_fmt(z.get('coverage_percent'), '.1f')} %, "
                       f"extruded {_fmt(z.get('extruded_percent'), '.1f')} %, "
                       f"mean layers {_fmt(z.get('mean_layers'), '.2f')}, thickness {_fmt(z.get('thickness_percent'), '.1f')} %")
        for name, p in (_get(case, "layers", "patches") or {}).items():
            out.append(f"- patch {name}: coverage {_fmt(p.get('coverage_percent'), '.1f')} %, extruded "
                       f"{_fmt(p.get('extruded_percent'), '.1f')} %, mean layers "
                       f"{_fmt(p.get('mean_layers'), '.2f')} / {p.get('target_layers')}, thickness "
                       f"{_fmt(p.get('mean_thickness_m'), '.3g')} m ({_fmt(p.get('thickness_percent'), '.1f')} % of target)")
        low = _get(case, "layers", "low_coverage") or []
        out.append(f"- coverage under 80 %: {', '.join(low) if low else 'none'}")
        t = case.get("time_s") or {}
        out.append(f"- time s: castellation {_fmt(t.get('castellation'), '.1f')}, snap {_fmt(t.get('snap'), '.1f')}, "
                   f"layers {_fmt(t.get('layers'), '.1f')}, mesh total {_fmt(t.get('mesh_total'), '.1f')}, "
                   f"case total {_fmt(t.get('case_total'), '.1f')}")
        out.append(f"- peak memory of a child process: mesh {_fmt(case.get('mesh_peak_mb'), '.0f')} MiB, "
                   f"with the solver {_fmt(case.get('solve_peak_mb'), '.0f')} MiB")
        y = case.get("yplus") or {}
        if y:
            out.append(f"- y+ ({y.get('label')}, {y.get('iterations')} iterations on {y.get('cores')} cores, "
                       f"target {y.get('target')}): min {_fmt(y.get('min'), '.3g')}, mean {_fmt(y.get('mean'), '.3g')}, "
                       f"max {_fmt(y.get('max'), '.3g')}, area in [{_fmt((y.get('band') or [None])[0])}, "
                       f"{_fmt((y.get('band') or [None, None])[1])}]: {_fmt(y.get('in_band_percent'), '.1f')} %")
        r = case.get("robustness") or {}
        out.append(f"- lost parts: {', '.join(r.get('lost_parts') or []) or 'none'}; domain errors: "
                   f"{'; '.join(r.get('domain_errors') or []) or 'none'}")
        out.append("")
    return "\n".join(out)


def write_result(result: dict, folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    meta = result["meta"]
    stem = f"{meta['stamp']}_{meta['git_sha']}"
    json_path, md_path = folder / f"{stem}.json", folder / f"{stem}.md"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(result) + "\n", encoding="utf-8")
    return json_path, md_path


def compare(old: dict, new: dict) -> tuple[list[str], list[str], list[str]]:
    """(delta lines, regressions, time flags) of ``new`` against ``old``, per case present in both
    (a case missing from ``new`` is a regression)."""
    old_cases = {c["case"]: c for c in old.get("cases", [])}
    deltas, regressions, flags = [], [], []

    def d(a, b):
        return None if a is None or b is None else b - a

    for case in new.get("cases", []):
        name = case["case"]
        a, b = case_row(old_cases[name]) if name in old_cases else None, case_row(case)
        if b["status"] == "FAILED" or b["lost_parts"]:
            regressions.append(f"{name}: mesh failed or a part was lost ({case.get('failure') or 'lost parts'})")
        if a is None:
            deltas.append(f"{name}: not in the reference result")
            continue
        parts = []
        for key in ("cells", "max_non_ortho", "faces_gt70", "coverage", "target_layers", "worst_zone_coverage",
                    "fidelity_rms", "yplus_mean", "total_time"):
            delta = d(a[key], b[key])
            parts.append(f"{key} {_fmt(a[key], '.4g')} -> {_fmt(b[key], '.4g')} ({_fmt(delta, '+.4g')})")
        deltas.append(f"{name}: " + "; ".join(parts))
        cov = d(a["coverage"], b["coverage"])
        if cov is not None and cov < -COVERAGE_DROP_POINTS:
            regressions.append(f"{name}: strict layer coverage dropped {-cov:.1f} points")
        if a["target_layers"] is not None and b["target_layers"] is not None and a["target_layers"] != b["target_layers"]:
            flags.append(f"{name}: target layer count {a['target_layers']} -> {b['target_layers']}: strict coverage "
                         "counts the full stack, so the coverage figures measure different stacks")
        old_zones = _get(old_cases[name], "layers", "zones") or {}
        for zname, z in (_get(case, "layers", "zones") or {}).items():
            dz = d((old_zones.get(zname) or {}).get("coverage_percent"), z.get("coverage_percent"))
            if dz is not None and dz < -COVERAGE_DROP_POINTS:
                regressions.append(f"{name}: zone {zname} coverage dropped {-dz:.1f} points")
        no = d(a["max_non_ortho"], b["max_non_ortho"])
        if no is not None and no > NON_ORTHO_RISE_DEG:
            regressions.append(f"{name}: max non-orthogonality up {no:.1f} degrees")
        f70 = d(a["faces_gt70"], b["faces_gt70"])
        if f70 is not None and f70 > 0:
            regressions.append(f"{name}: {f70} more faces above 70 degrees")
        if a["cells"] and b["cells"] and b["cells"] > a["cells"] * (1 + CELLS_RISE):
            regressions.append(f"{name}: cells up {100 * (b['cells'] / a['cells'] - 1):.1f} %")
        if a["fidelity_rms"] and b["fidelity_rms"] and b["fidelity_rms"] > a["fidelity_rms"] * (1 + FIDELITY_RMS_RISE):
            regressions.append(f"{name}: surface fidelity RMS worse by {100 * (b['fidelity_rms'] / a['fidelity_rms'] - 1):.1f} %")
        if a["total_time"] and b["total_time"] and b["total_time"] > a["total_time"] * (1 + TIME_RISE):
            flags.append(f"{name}: total time up {100 * (b['total_time'] / a['total_time'] - 1):.0f} % (time is noisy: flag only)")
    new_names = {c["case"] for c in new.get("cases", [])}
    requested = set(new.get("meta", {}).get("cases") or new_names)
    for name in old_cases:
        if name in requested and name not in new_names:
            regressions.append(f"{name}: missing from the new result")
    return deltas, regressions, flags
