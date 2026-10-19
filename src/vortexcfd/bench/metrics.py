"""Benchmark metrics (D-082): mesh quality, layers, robustness, indicative y+ (numpy only, no Qt).

Every function takes plain arrays or log text, so the tests use small fixtures.
"""

import re
from collections.abc import Callable, Sequence

import numpy as np

NON_ORTHO_THRESHOLDS = (65.0, 70.0)  # degrees: faces above each are counted
SKEW_THRESHOLD = 4.0  # checkMesh's "highly skew" threshold
LOW_COVERAGE_PERCENT = 80.0  # zones and patches below this are listed
NEAR_FULL_FRACTION = 0.8  # "near full": at least this fraction of the target layer count (D-091)
YPLUS_BAND = (0.5, 2.0)  # times the target y+

_NUM = r"([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)"


# -- checkMesh ---------------------------------------------------------------------------------------

def _first(pattern: str, text: str, cast=float):
    m = re.search(pattern, text, re.MULTILINE)
    return cast(m.group(1)) if m else None


def failed_check_type(line: str) -> str:
    """A short type for a checkMesh "***" line: its words up to the first number, colon or comma,
    e.g. " ***Max skewness = 5.1, 12 highly skew faces" -> "Max skewness"."""
    text = line.strip().lstrip("*").strip()
    text = re.split(r"[:,=.(]|\s\d", text, maxsplit=1)[0]
    return " ".join(text.split()) or "unknown"


def parse_check_mesh_quality(text: str) -> dict:
    """Quality numbers of a checkMesh log: max / average non-orthogonality, the faces above 70
    degrees (checkMesh's "severely non-orthogonal" plus "non-orthogonality errors" counts; 0 when it
    prints neither), max skewness and
    the faces above 4 ("highly skew"; 0 when it prints "OK"), max aspect ratio and the failed checks by
    type (every line starting with "***"). None for numbers the log does not hold."""
    non_ortho = re.search(rf"Mesh non-orthogonality Max: {_NUM} average: {_NUM}", text)
    # checkMesh counts 70-90 degrees ("severely non-orthogonal") and above 90 ("errors") apart.
    severe = _first(r"Number of severely non-orthogonal \(> [\d.]+ degrees\) faces: (\d+)", text, int)
    errors = _first(r"Number of non-orthogonality errors: (\d+)", text, int)
    if severe is not None or errors is not None:
        severe = (severe or 0) + (errors or 0)
    skew = re.search(rf"\*\*\*Max skewness = {_NUM}, (\d+) highly skew faces", text)
    skew_count = int(skew.group(2)) if skew else None
    max_skew = _first(rf"Max skewness = {_NUM}", text)
    aspect = _first(rf"Max aspect ratio = {_NUM}", text)
    if aspect is None:
        aspect = _first(rf"High aspect ratio cells found, Max aspect ratio: {_NUM}", text)
    failed: dict[str, int] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("***"):
            kind = failed_check_type(line)
            failed[kind] = failed.get(kind, 0) + 1
    mesh_ok = re.search(r"^\s*Mesh OK\.", text, re.MULTILINE) is not None
    n_failed = 0 if mesh_ok else (_first(r"^\s*Failed (\d+) mesh checks?\.", text, int) or max(1, len(failed)))
    return {
        "max_non_ortho": float(non_ortho.group(1)) if non_ortho else None,
        "avg_non_ortho": float(non_ortho.group(2)) if non_ortho else None,
        "faces_non_ortho_gt70_checkmesh": severe if severe is not None else (0 if non_ortho else None),
        "max_skewness": max_skew,
        "faces_skew_gt4": skew_count if skew_count is not None else (0 if max_skew is not None else None),
        "max_aspect_ratio": aspect,
        "mesh_ok": mesh_ok,
        "failed_checks": n_failed,
        "failed_by_type": failed,
    }


def read_scalar_list_field(text: str) -> np.ndarray:
    """The internalField values of an ASCII OpenFOAM scalar field file (uniform fields give one
    value). Only what the benchmark reads: checkMesh's face_nonOrthoAngle surface field."""
    m = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*(\d+)\s*\(", text)
    if m:
        n = int(m.group(1))
        end = text.index(")", m.end())
        values = np.array(text[m.end():end].split(), dtype=float)
        if values.size != n:
            raise ValueError(f"expected {n} values, read {values.size}")
        return values
    m = re.search(rf"internalField\s+uniform\s+{_NUM}", text)
    if m:
        return np.array([float(m.group(1))])
    m = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*0\s*\(\s*\)", text)
    if m:
        return np.array([])
    raise ValueError("no scalar internalField")


def count_above(values: np.ndarray, thresholds: Sequence[float]) -> dict[str, int]:
    v = np.asarray(values, dtype=float)
    return {f"{t:g}": int(np.count_nonzero(v > t)) for t in thresholds}


# -- snappyHexMesh log -------------------------------------------------------------------------------

def snappy_stage_times(text: str) -> dict[str, float | None]:
    """Wall-clock seconds of the snappyHexMesh stages: castellation ("Mesh refined in"), snap
    ("Mesh snapped in"), layers ("Layers added in") and the whole run ("Finished meshing in").
    snappyHexMesh prints the stage time since its start of that stage."""
    return {
        "castellation": _first(rf"^Mesh refined in = {_NUM} s", text),
        "snap": _first(rf"^Mesh snapped in = {_NUM} s", text),
        "layers": _first(rf"^Layers added in = {_NUM} s", text),
        "snappy_total": _first(rf"^Finished meshing in = {_NUM} s", text),
    }


# -- layers ------------------------------------------------------------------------------------------

def layer_stats(area: np.ndarray, n_layers: np.ndarray, thickness: np.ndarray,
                fraction: np.ndarray, target_layers: int) -> dict:
    """Area-weighted layer numbers of a set of wall faces.

    ``n_layers``, ``thickness`` (m) and ``fraction`` (achieved / wanted thickness) are
    snappyHexMesh's layer fields (nSurfaceLayers, thickness, thicknessFraction). Coverage is the
    share of the area whose faces have the full target layer count; ``extruded_percent`` the share
    with at least one layer; the thickness ratio is the area-weighted mean of thicknessFraction.
    Diagnostics (D-091): mean layers as a percentage of the target, the share with at least
    NEAR_FULL_FRACTION of the target count, the share with no layer, and the area share per layer
    count (``layers_area_percent``, keys are counts as text)."""
    a = np.asarray(area, dtype=float)
    total = float(a.sum())
    if a.size == 0 or total <= 0:
        return {"faces": int(a.size), "area": total, "coverage_percent": None, "extruded_percent": None,
                "mean_layers": None,
                "target_layers": target_layers, "mean_thickness_m": None, "thickness_percent": None,
                "mean_over_target_percent": None, "near_full_percent": None, "zero_layers_percent": None,
                "layers_area_percent": {}}
    n = np.asarray(n_layers, dtype=float)
    counts = np.rint(n).astype(int)
    mean = float((a * n).sum() / total)
    return {
        "mean_over_target_percent": 100.0 * mean / target_layers if target_layers else None,
        "near_full_percent": 100.0 * float(a[n >= NEAR_FULL_FRACTION * target_layers - 1e-9].sum()) / total,
        "zero_layers_percent": 100.0 * float(a[n < 0.5].sum()) / total,
        "layers_area_percent": {str(k): 100.0 * float(a[counts == k].sum()) / total for k in np.unique(counts)},
        "faces": int(a.size),
        "area": total,
        "coverage_percent": 100.0 * float(a[n >= target_layers - 0.5].sum()) / total,
        "extruded_percent": 100.0 * float(a[n >= 0.5].sum()) / total,
        "mean_layers": mean,
        "target_layers": target_layers,
        "mean_thickness_m": float((a * np.asarray(thickness, dtype=float)).sum() / total),
        "thickness_percent": 100.0 * float((a * np.asarray(fraction, dtype=float)).sum() / total),
    }


def point_segment_distance(points: np.ndarray, a: Sequence[float], b: Sequence[float]) -> np.ndarray:
    p = np.asarray(points, dtype=float)
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ab = b - a
    denom = float(ab @ ab)
    t = np.zeros(len(p)) if denom == 0 else np.clip((p - a) @ ab / denom, 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


# Above this many segments a zone's distance test uses a VTK cell locator instead of a loop.
LOCATOR_SEGMENTS = 64


def segments_distance(points: np.ndarray, segments) -> np.ndarray:
    """Distance from each point to the nearest of many segments (VTK static cell locator)."""
    import pyvista as pv

    seg = np.asarray(segments, dtype=float).reshape(-1, 2, 3)
    lines = np.hstack([np.full((len(seg), 1), 2), np.arange(2 * len(seg)).reshape(-1, 2)]).ravel()
    poly = pv.PolyData(seg.reshape(-1, 3), lines=lines)
    _cells, closest = poly.find_closest_cell(np.asarray(points, dtype=float), return_closest_point=True)
    return np.linalg.norm(np.asarray(points, dtype=float) - closest, axis=1)


def zone_mask(centres: np.ndarray, boxes=(), segments=(), width: float = 0.0) -> np.ndarray:
    """Faces whose centre lies in one of ``boxes`` or within ``width`` of one of ``segments``."""
    c = np.asarray(centres, dtype=float).reshape(-1, 3)
    mask = np.zeros(len(c), dtype=bool)
    for x0, x1, y0, y1, z0, z1 in boxes:
        mask |= ((c[:, 0] >= x0) & (c[:, 0] <= x1) & (c[:, 1] >= y0) & (c[:, 1] <= y1)
                 & (c[:, 2] >= z0) & (c[:, 2] <= z1))
    if len(segments) > LOCATOR_SEGMENTS and len(c):
        mask |= segments_distance(c, segments) <= width
        return mask
    for a, b in segments:
        mask |= point_segment_distance(c, a, b) <= width
    return mask


def low_coverage(rows: dict[str, dict], threshold: float = LOW_COVERAGE_PERCENT) -> list[str]:
    """Names of the rows (patches or zones) whose coverage is below ``threshold``."""
    return [name for name, row in rows.items()
            if row.get("coverage_percent") is not None and row["coverage_percent"] < threshold]


# -- surface fidelity --------------------------------------------------------------------------------

def sphere_distance(centre: Sequence[float], radius: float) -> Callable[[np.ndarray], np.ndarray]:
    """Distance from points to a sphere surface (the exact reference of the sphere case)."""
    c = np.asarray(centre, dtype=float)
    return lambda p: np.abs(np.linalg.norm(np.asarray(p, dtype=float) - c, axis=1) - radius)


def fidelity(distances: np.ndarray, reference_length: float) -> dict:
    """Max and RMS of the wall-point distances to the original surface in metres, and divided by the
    reference length (stated as ``reference_m``, D-091)."""
    d = np.asarray(distances, dtype=float)
    if d.size == 0:
        return {"points": 0, "max_rel": None, "rms_rel": None, "max_m": None, "rms_m": None,
                "reference_m": reference_length}
    rms = float(np.sqrt(np.mean(d * d)))
    return {"points": int(d.size), "max_rel": float(d.max() / reference_length), "rms_rel": rms / reference_length,
            "max_m": float(d.max()), "rms_m": rms, "reference_m": reference_length}


# -- fidelity against a reference surface (local cases, D-094) ------------------------------------------

# A point is "far" when its distance exceeds this fraction of the local surface cell size.
FAR_FRACTION = 0.5


def reference_fidelity(distances: np.ndarray, local_size: np.ndarray, far_fraction: float = FAR_FRACTION) -> dict:
    """Distances (m) of points to a surface: max and RMS in mm, and the share of the points further
    than ``far_fraction`` times the local surface cell size (m, one per point)."""
    d = np.asarray(distances, dtype=float)
    size = np.asarray(local_size, dtype=float)
    if d.size == 0:
        return {"points": 0, "max_mm": None, "rms_mm": None, "far_percent": None}
    return {"points": int(d.size), "max_mm": 1000.0 * float(d.max()), "rms_mm": 1000.0 * float(np.sqrt(np.mean(d * d))),
            "far_percent": 100.0 * float(np.mean(d > far_fraction * size))}


def point_sizes(points: np.ndarray, faces: np.ndarray, face_area: np.ndarray) -> np.ndarray:
    """Local surface cell size at each point: the mean of sqrt(area) of the faces that use it.
    ``faces``: (m, k) point ids (k vertices per face, -1 padded)."""
    size = np.sqrt(np.asarray(face_area, dtype=float))
    total = np.zeros(len(points))
    count = np.zeros(len(points))
    for column in np.asarray(faces).T:
        ok = column >= 0
        np.add.at(total, column[ok], size[ok])
        np.add.at(count, column[ok], 1.0)
    return np.where(count > 0, total / np.maximum(count, 1.0), 0.0)


def force_partition(part_patches: dict[str, tuple[str, ...]], total_patches: tuple[str, ...],
                    face_counts: dict[str, int], patch_areas: dict[str, float]) -> dict:
    """The geometric check that per-part forces sum to the total (D-073, D-094): the per-part force
    objects' patch sets must be disjoint and together cover exactly the patches of the all-walls
    object, every one of them with faces; the parts' wall areas then sum to the total. Forces are
    integrals over the patches, so a partition makes the per-part forces add up to the total."""
    seen: dict[str, str] = {}
    problems = []
    for part, patches in part_patches.items():
        for p in patches:
            if p in seen:
                problems.append(f"patch {p} is in both {seen[p]} and {part}")
            seen[p] = part
            if face_counts.get(p, 0) <= 0:
                problems.append(f"patch {p} of {part} has no faces")
    missing = sorted(set(total_patches) - set(seen))
    extra = sorted(set(seen) - set(total_patches))
    problems += [f"patch {p} is in the total but in no part" for p in missing]
    problems += [f"patch {p} is in a part but not in the total" for p in extra]
    parts_area = sum(patch_areas.get(p, 0.0) for patches in part_patches.values() for p in patches)
    total_area = sum(patch_areas.get(p, 0.0) for p in total_patches)
    return {"ok": not problems, "problems": problems, "parts_area_m2": parts_area, "total_area_m2": total_area,
            "parts": {part: {"patches": list(patches), "faces": int(sum(face_counts.get(p, 0) for p in patches)),
                             "area_m2": float(sum(patch_areas.get(p, 0.0) for p in patches))}
                      for part, patches in part_patches.items()}}


# -- snappyHexMesh layer log -----------------------------------------------------------------------------

_CHECK_LINE = re.compile(r"^\s+(.*?)\s*:\s*(\d+)\s*$")


def _check_counts(lines: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in lines:
        m = _CHECK_LINE.match(line)
        if m and int(m.group(2)) > 0:
            key = re.sub(r"\s+", " ", m.group(1))
            out[key] = out.get(key, 0) + int(m.group(2))
    return out


def layer_log_diagnostics(text: str) -> dict:
    """What snappyHexMesh's layer phase did to the stacks, from its log (D-091).

    - ``removed_by_quality``: faces whose extrusion the layer mesh check removed, summed over the
      layer iterations ("Removed extrusion at N faces"), and ``layer_check_errors``: the checks that
      failed in those "Checking mesh with layer" blocks (faces in error, summed);
    - ``shrink_errors``: checks that failed while the mesh was moved (shrunk) for the layers, where
      snappyHexMesh scales the displacement down locally instead of removing layers, and
      ``shrink_scaling_steps``: how many such scaling steps it took;
    - ``feature_edges_zero_displacement``: points on feature edges sharper than the layer featureAngle
      that get no layer ("Set displacement to zero for points on N feature edges");
    - ``isolated_points_stopped`` and ``medial_axis_reduced_nodes``: other local stops;
    - ``extruded_faces`` / ``total_faces`` of the last iteration and the iteration count.
    """
    lines = text.splitlines()
    removed, iterations = 0, 0
    layer_errors: dict[str, int] = {}
    shrink_errors: dict[str, int] = {}
    shrink_steps = 0
    out = {"extruded_faces": None, "total_faces": None}
    feature = isolated = medial = 0
    in_layers = False  # after "Shrinking and layer addition phase"
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("Shrinking and layer addition phase"):
            in_layers = True
        if not in_layers:
            i += 1
            continue
        if line.startswith("Layer addition iteration"):
            iterations += 1
        m = re.search(r"Set displacement to zero for points on (\d+) feature edges", line)
        if m:
            feature += int(m.group(1))
        m = re.search(r"Number of isolated points extrusion stopped : (\d+)", line)
        if m:
            isolated += int(m.group(1))
        m = re.search(r"Reducing layer thickness at (\d+) nodes", line)
        if m:
            medial += int(m.group(1))
        if line.startswith("Moving mesh using displacement scaling"):
            block = []
            j = i + 1
            if j < len(lines) and lines[j].startswith("Checking faces in error"):
                j += 1
            while j < len(lines) and _CHECK_LINE.match(lines[j]):
                block.append(lines[j])
                j += 1
            errors = _check_counts(block)
            if errors:
                shrink_steps += 1
                for k, v in errors.items():
                    shrink_errors[k] = max(shrink_errors.get(k, 0), v)
        if line.startswith("Checking mesh with layer"):
            block = []
            j = i + 1
            while j < len(lines) and not lines[j].startswith("Detected "):
                block.append(lines[j])
                j += 1
            for k, v in _check_counts(block).items():
                layer_errors[k] = layer_errors.get(k, 0) + v
        m = re.search(r"Extruding (\d+) out of (\d+) faces .*Removed extrusion at (\d+) faces", line)
        if m:
            out["extruded_faces"], out["total_faces"] = int(m.group(1)), int(m.group(2))
            removed += int(m.group(3))
        i += 1
    out.update(layer_iterations=iterations, removed_by_quality=removed, layer_check_errors=layer_errors,
               shrink_errors=shrink_errors, shrink_scaling_steps=shrink_steps,
               feature_edges_zero_displacement=feature, isolated_points_stopped=isolated,
               medial_axis_reduced_nodes=medial)
    return out


# -- y+ ----------------------------------------------------------------------------------------------

def yplus_stats(values: np.ndarray, area: np.ndarray, target: float, band=YPLUS_BAND) -> dict:
    """min, area-weighted mean and max of the wall y+, and the share of the wall area with y+ in
    [band[0] * target, band[1] * target]."""
    v, a = np.asarray(values, dtype=float), np.asarray(area, dtype=float)
    if v.size == 0 or a.sum() <= 0:
        return {"min": None, "mean": None, "max": None, "in_band_percent": None, "target": target}
    lo, hi = band[0] * target, band[1] * target
    inside = (v >= lo) & (v <= hi)
    return {"min": float(v.min()), "mean": float((a * v).sum() / a.sum()), "max": float(v.max()),
            "in_band_percent": 100.0 * float(a[inside].sum() / a.sum()), "target": target,
            "band": [lo, hi]}
