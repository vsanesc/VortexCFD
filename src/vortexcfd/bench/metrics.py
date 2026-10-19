"""Benchmark metrics (D-082): mesh quality, layers, robustness, indicative y+ (numpy only, no Qt).

Every function takes plain arrays or log text, so the tests use small fixtures.
"""

import re
from collections.abc import Callable, Sequence

import numpy as np

NON_ORTHO_THRESHOLDS = (65.0, 70.0)  # degrees: faces above each are counted
SKEW_THRESHOLD = 4.0  # checkMesh's "highly skew" threshold
LOW_COVERAGE_PERCENT = 80.0  # zones and patches below this are listed
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
    with at least one layer; the thickness ratio is the area-weighted mean of thicknessFraction."""
    a = np.asarray(area, dtype=float)
    total = float(a.sum())
    if a.size == 0 or total <= 0:
        return {"faces": int(a.size), "area": total, "coverage_percent": None, "extruded_percent": None,
                "mean_layers": None,
                "target_layers": target_layers, "mean_thickness_m": None, "thickness_percent": None}
    n = np.asarray(n_layers, dtype=float)
    return {
        "faces": int(a.size),
        "area": total,
        "coverage_percent": 100.0 * float(a[n >= target_layers - 0.5].sum()) / total,
        "extruded_percent": 100.0 * float(a[n >= 0.5].sum()) / total,
        "mean_layers": float((a * n).sum() / total),
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


def zone_mask(centres: np.ndarray, boxes=(), segments=(), width: float = 0.0) -> np.ndarray:
    """Faces whose centre lies in one of ``boxes`` or within ``width`` of one of ``segments``."""
    c = np.asarray(centres, dtype=float).reshape(-1, 3)
    mask = np.zeros(len(c), dtype=bool)
    for x0, x1, y0, y1, z0, z1 in boxes:
        mask |= ((c[:, 0] >= x0) & (c[:, 0] <= x1) & (c[:, 1] >= y0) & (c[:, 1] <= y1)
                 & (c[:, 2] >= z0) & (c[:, 2] <= z1))
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
    """Max and RMS of the wall-point distances to the original surface, divided by the reference length."""
    d = np.asarray(distances, dtype=float)
    if d.size == 0:
        return {"points": 0, "max_rel": None, "rms_rel": None}
    return {"points": int(d.size), "max_rel": float(d.max() / reference_length),
            "rms_rel": float(np.sqrt(np.mean(d * d)) / reference_length)}


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
