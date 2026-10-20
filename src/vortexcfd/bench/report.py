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


def has_walk(case: dict) -> bool:
    """Whether the case holds the layers counted from the mesh (bench/layer_walk, D-102)."""
    return bool(_get(case, "layers_walk", "walls"))


def layer_key(case: dict, walk: bool | None = None) -> str:
    """The layer measure of the headline: "layers_walk", the layers counted from the mesh (D-105),
    when the case has them (and ``walk`` is not False), else "layers", snappyHexMesh's own fields."""
    if walk is None:
        walk = has_walk(case)
    return "layers_walk" if walk and has_walk(case) else "layers"


def worst_zone(case: dict, walk: bool | None = None) -> tuple[str | None, float | None]:
    zones = _get(case, layer_key(case, walk), "zones") or {}
    rows = [(n, z.get("coverage_percent")) for n, z in zones.items() if z.get("coverage_percent") is not None]
    return min(rows, key=lambda r: r[1]) if rows else (None, None)


def _metres(case: dict, kind: str) -> float | None:
    fid = _get(case, "layers", "fidelity") or {}
    if fid.get(f"{kind}_m") is not None:
        return fid[f"{kind}_m"]
    rel, ref = fid.get(f"{kind}_rel"), fid.get("reference_m") or case.get("reference_length")
    return None if rel is None or ref is None else rel * ref


def case_row(case: dict, walk: bool | None = None) -> dict:
    """The values of the summary table for one case. The layer columns come from the layers counted
    from the mesh when the case has them (D-105; ``walk`` False forces snappyHexMesh's own fields),
    with snappyHexMesh's strict coverage as ``coverage_fields``."""
    key = layer_key(case, walk)
    zone, zone_cov = worst_zone(case, walk)
    walls = _get(case, key, "walls") or {}
    checks = case.get("checks") or {}
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
        "hard_failures": checks.get("hard"),
        "soft_failures": checks.get("soft"),
        "layer_basis": "mesh" if key == "layers_walk" else "fields",
        "coverage": walls.get("coverage_percent"),
        "coverage_fields": _get(case, "layers", "walls", "coverage_percent"),
        "mean_over_target": walls.get("mean_over_target_percent"),
        "near_full": walls.get("near_full_percent"),
        "zero_layers": walls.get("zero_layers_percent"),
        "removed_by_quality": _get(case, "layers", "log", "removed_by_quality"),
        "yplus_cores": _get(case, "yplus", "cores"),
        "extruded": walls.get("extruded_percent"),
        "mean_layers": walls.get("mean_layers"),
        "target_layers": walls.get("target_layers"),
        "worst_zone": zone,
        "worst_zone_coverage": zone_cov,
        "thickness_m": thick,
        "thickness_percent": frac,
        "fidelity_max": _get(case, "layers", "fidelity", "max_rel"),
        "fidelity_rms": _get(case, "layers", "fidelity", "rms_rel"),
        # metres (D-091): stored since 5.1b, otherwise the relative value times the case's reference
        "fidelity_max_m": _metres(case, "max"),
        "fidelity_rms_m": _metres(case, "rms"),
        "fidelity_reference_m": _get(case, "layers", "fidelity", "reference_m") or case.get("reference_length"),
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
    ("hard_failures", "Hard", "d"), ("soft_failures", "Soft", "d"),
    # headline layer metric: strict coverage, the wall area with the full target layer count (D-087),
    # counted from the mesh when the result has the walk (D-105); snappyHexMesh's own figure next to it
    ("coverage", "Strict coverage %", ".1f"), ("layer_basis", "Basis", "s"),
    ("coverage_fields", "Strict cov. % (snappy fields)", ".1f"), ("target_layers", "Target layers", "d"),
    ("extruded", "Extruded %", ".1f"), ("mean_layers", "Mean layers", ".2f"),
    ("mean_over_target", "Mean / target %", ".1f"), ("near_full", ">=80 % of target %", ".1f"),
    ("zero_layers", "No layer %", ".1f"), ("removed_by_quality", "Layer faces removed by checks", "d"),
    ("worst_zone", "Worst zone", "s"), ("worst_zone_coverage", "Worst zone %", ".1f"),
    ("thickness_percent", "Thickness % of target", ".1f"),
    ("fidelity_rms_m", "Fidelity RMS mm", "mm"), ("fidelity_max_m", "Fidelity max mm", "mm"),
    ("fidelity_rms", "Fidelity RMS/ref", ".2e"), ("fidelity_max", "Fidelity max/ref", ".2e"),
    ("fidelity_reference_m", "ref m", ".4g"),
    ("yplus_mean", "y+ mean", ".1f"), ("yplus_in_band", "y+ in band %", ".1f"), ("yplus_cores", "y+ cores", "d"),
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
            if spec == "mm":
                cells.append(_fmt(None if v is None else 1000.0 * float(v), ".3f"))
            else:
                cells.append(_fmt(float(v), spec) if isinstance(v, (int, float)) and spec not in ("s", "d") else _fmt(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _checks(errors: dict | None) -> str:
    return ", ".join(f"{k}: {v}" for k, v in (errors or {}).items()) or "none"


# -- local cases (D-094) ---------------------------------------------------------------------------------

LOCAL_COLUMNS = (
    ("case", "Case"), ("status", "Status"), ("cells", "Cells"), ("failed_checks", "Failed checks"),
    ("hard_failures", "Hard"), ("soft_failures", "Soft"),
    ("max_non_ortho", "Max non-ortho"), ("faces_gt70", "Faces >70"), ("coverage", "Strict coverage %"),
    ("coverage_fields", "Strict cov. % (snappy fields)"),
    ("target_layers", "Target layers"), ("m2r_rms", "Mesh->ref RMS mm"), ("m2r_max", "Mesh->ref max mm"),
    ("m2r_far", "Mesh->ref far %"), ("r2m_rms", "Ref->mesh RMS mm"), ("r2m_max", "Ref->mesh max mm"),
    ("r2m_far", "Ref->mesh far %"), ("internal_points", "Internal points"), ("internal_area", "Internal area m2"),
    ("patches_with_faces", "Patches with faces"), ("force_sum", "Force sum check"),
    ("prep_time", "Prep s"), ("mesh_time", "Mesh s"),
)


def local_row(case: dict) -> dict:
    rf = case.get("reference_fidelity") or {}
    m2r, r2m, internal = rf.get("mesh_to_reference") or {}, rf.get("reference_to_mesh") or {}, rf.get("internal") or {}
    faces = case.get("patch_faces") or {}
    row = case_row(case)
    return {
        **row,
        "m2r_rms": m2r.get("rms_mm"), "m2r_max": m2r.get("max_mm"), "m2r_far": m2r.get("far_percent"),
        "r2m_rms": r2m.get("rms_mm"), "r2m_max": r2m.get("max_mm"), "r2m_far": r2m.get("far_percent"),
        "internal_points": internal.get("points"), "internal_area": internal.get("area_m2"),
        "patches_with_faces": f"{sum(1 for v in faces.values() if v > 0)}/{len(faces)}" if faces else None,
        "force_sum": None if not case.get("force_partition") else ("ok" if case["force_partition"]["ok"] else "FAILED"),
        "prep_time": _get(case, "surface_prep", "time_s"),
    }


def _cell(v) -> str:
    if isinstance(v, float):
        return _fmt(v, ".3g") if abs(v) < 1000 else _fmt(v, ".0f")
    return _fmt(v)


def local_table(result: dict) -> str:
    """The summary table of local cases: quality, layers and the fidelity against the reference."""
    lines = ["| " + " | ".join(t for _, t in LOCAL_COLUMNS) + " |", "|" + "|".join("---" for _ in LOCAL_COLUMNS) + "|"]
    for case in result.get("cases", []):
        row = local_row(case)
        lines.append("| " + " | ".join(_cell(row.get(k)) for k, _ in LOCAL_COLUMNS) + " |")
    return "\n".join(lines)


def local_zone_table(result: dict) -> str:
    """Per case and zone: strict layer coverage and the fidelity in both directions."""
    lines = ["| Case | Zone | Strict coverage % | Mesh->ref RMS mm | Mesh->ref max mm | Mesh->ref far % | "
             "Ref->mesh RMS mm | Ref->mesh max mm | Ref->mesh far % | Internal area m2 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for case in result.get("cases", []):
        zones = _get(case, "reference_fidelity", "zones") or {}
        layer_zones = _get(case, layer_key(case), "zones") or {}
        for name, z in zones.items():
            m2r, r2m = z.get("mesh_to_reference") or {}, z.get("reference_to_mesh") or {}
            lines.append("| " + " | ".join(_cell(v) for v in (
                case.get("case"), name, (layer_zones.get(name) or {}).get("coverage_percent"), m2r.get("rms_mm"),
                m2r.get("max_mm"), m2r.get("far_percent"), r2m.get("rms_mm"), r2m.get("max_mm"), r2m.get("far_percent"),
                z.get("internal_area_m2"))) + " |")
    return "\n".join(lines)


def markdown_report(result: dict) -> str:
    meta = result.get("meta", {})
    if meta.get("local"):
        return local_report(result)
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
                       f"mean layers {_fmt(z.get('mean_layers'), '.2f')} / {z.get('target_layers')} "
                       f"({_fmt(z.get('mean_over_target_percent'), '.1f')} %), "
                       f">= 80 % of target {_fmt(z.get('near_full_percent'), '.1f')} %, "
                       f"no layer {_fmt(z.get('zero_layers_percent'), '.1f')} %, "
                       f"thickness {_fmt(z.get('thickness_percent'), '.1f')} %")
        walls = _get(case, "layers", "walls") or {}
        if walls.get("layers_area_percent"):
            out.append("- wall area by layer count: " + ", ".join(
                f"{k}: {_fmt(v, '.1f')} %" for k, v in sorted(walls["layers_area_percent"].items(), key=lambda kv: int(kv[0]))))
        log = _get(case, "layers", "log")
        if log:
            out.append(f"- layer phase (log): {log.get('layer_iterations')} iteration(s), layer faces removed by the "
                       f"quality checks {log.get('removed_by_quality')} ({_checks(log.get('layer_check_errors'))}); "
                       f"faces in error while shrinking (displacement scaled down, {log.get('shrink_scaling_steps')} "
                       f"steps): {_checks(log.get('shrink_errors'))}; feature-edge points with no layer "
                       f"{log.get('feature_edges_zero_displacement')}; isolated points stopped "
                       f"{log.get('isolated_points_stopped')}; medial-axis reductions {log.get('medial_axis_reduced_nodes')}")
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


def local_report(result: dict) -> str:
    meta = result.get("meta", {})
    out = [f"# Local benchmark cases {meta.get('stamp', '')}", "",
           f"git {meta.get('git_sha', '?')}, {meta.get('utc', '?')} UTC, wall-clock {_fmt(meta.get('wall_s'), '.0f')} s, "
           f"{meta.get('physical_cores', '?')} physical cores. Local cases (D-094): numbers only, never committed.", "",
           local_table(result), "", local_zone_table(result), ""]
    for case in result.get("cases", []):
        out += [f"## {case.get('case')}", "", f"- {case.get('description')}"]
        if case.get("failure"):
            out.append(f"- failure: {case['failure']}")
        for line in case.get("deviations", []):
            out.append(f"- deviation: {line}")
        ref = case.get("reference") or {}
        if ref:
            out.append(f"- reference {ref.get('file')}: l_ref {_fmt(ref.get('l_ref_m'), '.4g')} m ({ref.get('l_ref_method')}); "
                       "intersection curves " + ", ".join(f"{k} {_fmt(v, '.3g')} m" for k, v in (ref.get('curves_m') or {}).items()))
            for name, text in (ref.get("zones") or {}).items():
                out.append(f"- zone {name}: {text}")
        fb = _get(case, "quality", "failed_by_type") or {}
        if fb:
            out.append("- failed checks: " + ", ".join(f"{k} ({v})" for k, v in fb.items()))
        prep = case.get("surface_prep") or {}
        for label, value in prep.get("report") or []:
            out.append(f"- preparation: {label}: {value}")
        fp = case.get("force_partition") or {}
        if fp:
            out.append(f"- force sum check: {'ok' if fp.get('ok') else 'FAILED'} (parts {_fmt(fp.get('parts_area_m2'), '.4g')} m2, "
                       f"total {_fmt(fp.get('total_area_m2'), '.4g')} m2){'; ' + '; '.join(fp['problems']) if fp.get('problems') else ''}")
        if case.get("patch_faces"):
            out.append("- patch faces: " + ", ".join(f"{k} {v}" for k, v in case["patch_faces"].items()))
        r = case.get("robustness") or {}
        out.append(f"- lost parts: {', '.join(r.get('lost_parts') or []) or 'none'}")
        y = case.get("yplus") or {}
        if y:
            out.append(f"- y+ ({y.get('label')}, {y.get('iterations')} iterations on {y.get('cores')} cores): mean "
                       f"{_fmt(y.get('mean'), '.3g')}, in band {_fmt(y.get('in_band_percent'), '.1f')} %, state {y.get('state')}")
        t = case.get("time_s") or {}
        out.append(f"- time s: import {_fmt(case.get('import_time_s'), '.1f')}, preparation "
                   f"{_fmt(prep.get('time_s'), '.1f')}, mesh total {_fmt(t.get('mesh_total'), '.1f')}, case total "
                   f"{_fmt(t.get('case_total'), '.1f')}")
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
        # like for like: the mesh-based layer count only when both results have it (D-105)
        walk = has_walk(case) and name in old_cases and has_walk(old_cases[name])
        a, b = case_row(old_cases[name], walk) if name in old_cases else None, case_row(case, walk)
        if b["status"] == "FAILED" or b["lost_parts"]:
            regressions.append(f"{name}: mesh failed or a part was lost ({case.get('failure') or 'lost parts'})")
        if a is None:
            deltas.append(f"{name}: not in the reference result")
            continue
        parts = []
        if walk:
            parts.append("layers counted from the mesh")
        for key in ("cells", "max_non_ortho", "faces_gt70", "hard_failures", "coverage", "target_layers",
                    "worst_zone_coverage",
                    "yplus_mean", "total_time"):
            delta = d(a[key], b[key])
            parts.append(f"{key} {_fmt(a[key], '.4g')} -> {_fmt(b[key], '.4g')} ({_fmt(delta, '+.4g')})")
        for key in ("fidelity_rms_m", "fidelity_max_m"):  # metres, then relative with its reference (D-091)
            mm_a, mm_b = (None if v is None else 1000.0 * v for v in (a[key], b[key]))
            parts.append(f"{key[:-2]}_mm {_fmt(mm_a, '.4g')} -> {_fmt(mm_b, '.4g')} ({_fmt(d(mm_a, mm_b), '+.4f')})")
        for key in ("fidelity_rms", "fidelity_max"):
            parts.append(f"{key}/ref {_fmt(a[key], '.4g')} (ref {_fmt(a['fidelity_reference_m'], '.4g')} m) -> "
                         f"{_fmt(b[key], '.4g')} (ref {_fmt(b['fidelity_reference_m'], '.4g')} m)")
        deltas.append(f"{name}: " + "; ".join(parts))
        cov = d(a["coverage"], b["coverage"])
        if cov is not None and cov < -COVERAGE_DROP_POINTS:
            regressions.append(f"{name}: strict layer coverage dropped {-cov:.1f} points")
        if a["target_layers"] is not None and b["target_layers"] is not None and a["target_layers"] != b["target_layers"]:
            flags.append(f"{name}: target layer count {a['target_layers']} -> {b['target_layers']}: strict coverage "
                         "counts the full stack, so the coverage figures measure different stacks")
        old_zones = _get(old_cases[name], layer_key(old_cases[name], walk), "zones") or {}
        for zname, z in (_get(case, layer_key(case, walk), "zones") or {}).items():
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
        # like-for-like in metres: the relative values may use different reference lengths (D-091)
        if a["fidelity_rms_m"] and b["fidelity_rms_m"] and b["fidelity_rms_m"] > a["fidelity_rms_m"] * (1 + FIDELITY_RMS_RISE):
            regressions.append(f"{name}: surface fidelity RMS worse by "
                               f"{100 * (b['fidelity_rms_m'] / a['fidelity_rms_m'] - 1):.1f} % (in metres)")
        if a["total_time"] and b["total_time"] and b["total_time"] > a["total_time"] * (1 + TIME_RISE):
            flags.append(f"{name}: total time up {100 * (b['total_time'] / a['total_time'] - 1):.0f} % (time is noisy: flag only)")
    new_names = {c["case"] for c in new.get("cases", [])}
    requested = set(new.get("meta", {}).get("cases") or new_names)
    for name in old_cases:
        if name in requested and name not in new_names:
            regressions.append(f"{name}: missing from the new result")
    return deltas, regressions, flags
