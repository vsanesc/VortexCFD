"""D-127 check (QUESTIONS 203, 204): real 3D mesh studies, mesh only, of the public benchmark's sphere and half wing.

Every level of the app's mesh study (D-066, D-127: since QUESTIONS 204 every level, the current one included, with
the current settings' distance shells and nCellsBetweenLevels 1) is meshed; with --singles every level also as a
single mesh: the same MeshCaseInput as a single mesh (buffer_scale 1, study_level False: nCellsBetweenLevels 3, no
shells). Per mesh: cells, checkMesh hard / soft failures (D-100), max non-orthogonality and faces above 70 degrees,
the walked strict layer coverage overall and per zone, the walked first cell, the median cell size within 0.1
reference length of the fixed points, the size of the cell containing each point (``containing_cell_m``) and
(QUESTIONS 204 b) the volume-weighted mean cell size over a cube of side 2 coarse cells centred on each point
(``cube_mean``; the coarse level's containing cell sets the side for every level).

    nice -n 15 .venv/bin/python scripts/validation/study3d_check.py [--cases sphere wing] [--singles] [--out NAME]

Serial meshing (the benchmark's). Cases in run/validation/study3d/ (git-ignored); numbers to
docs/validation/study3d/result.json.
"""

import argparse
import dataclasses
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vortexcfd.core.display_guard import apply_display_guard  # noqa: E402

apply_display_guard()

import numpy as np  # noqa: E402

from vortexcfd.bench import metrics  # noqa: E402
from vortexcfd.bench.cases import CASES  # noqa: E402
from vortexcfd.bench.geometries import ensure_geometry  # noqa: E402
from vortexcfd.bench.runner import face_quality, import_geometry, new_project, walk_measurements  # noqa: E402
from vortexcfd.foam.mesh_case import build_mesh_files, prepare_case_dir  # noqa: E402
from vortexcfd.foam.mesh_report import check_class  # noqa: E402
from vortexcfd.foam.mesh_run import MeshRun  # noqa: E402
from vortexcfd.foam.mesh_study import level_dir  # noqa: E402
from vortexcfd.foam.polymesh import PolyMesh, face_geometry  # noqa: E402
from vortexcfd.workflow import mesh_study  # noqa: E402

WORK = ROOT / "run" / "validation" / "study3d"
OUT = ROOT / "docs" / "validation" / "study3d"
GEOMETRY = ROOT / "benchmarks" / "geometries"


def say(text: str) -> None:
    print(f"[study3d {time.strftime('%H:%M:%S')}] {text}", flush=True)


def cell_sizes(mesh: PolyMesh) -> tuple[np.ndarray, np.ndarray]:
    """(cell centres, cell size = volume^(1/3)): volumes by the divergence theorem over the faces."""
    centres, vectors, _ = face_geometry(mesh.points, mesh.faces)
    n = int(max(mesh.owner.max(), mesh.neighbour.max() if len(mesh.neighbour) else 0)) + 1
    flux = (centres * vectors).sum(axis=1) / 3.0
    volume = np.zeros(n)
    np.add.at(volume, mesh.owner, flux)
    np.add.at(volume, mesh.neighbour, -flux[:len(mesh.neighbour)])
    total, count = np.zeros((n, 3)), np.zeros(n)
    np.add.at(total, mesh.owner, centres)
    np.add.at(count, mesh.owner, 1.0)
    np.add.at(total, mesh.neighbour, centres[:len(mesh.neighbour)])
    np.add.at(count, mesh.neighbour, 1.0)
    return total / count[:, None], np.cbrt(np.abs(volume))


def fixed_points(parts_bounds, length: float) -> dict[str, tuple[float, float, float]]:
    """One reference length ahead of and above the parts' box, two behind it (the wake), at the box's middle; and
    inside the transition zone half a length ahead and above, one length behind."""
    x0, x1, y0, y1, z0, z1 = parts_bounds
    yc, zc, xc = (y0 + y1) / 2, (z0 + z1) / 2, (x0 + x1) / 2
    return {"ahead": (x0 - length, yc, zc), "above": (xc, yc, z1 + length), "wake": (x1 + 2 * length, yc, zc),
            "ahead 0.5L": (x0 - 0.5 * length, yc, zc), "above 0.5L": (xc, yc, z1 + 0.5 * length),
            "wake 1L": (x1 + length, yc, zc)}


def containing_cell(mesh: PolyMesh, faces: tuple[np.ndarray, np.ndarray], centres: np.ndarray, point,
                    candidates: int = 64) -> int | None:
    """The cell containing ``point``: among the nearest cell centres, the one whose faces all have the point on
    their inner side (face centre and area vector, outward for the owner; snappyHexMesh's cells are convex up to
    the snapped wall layer, far from these points)."""
    fc, fv = faces
    p = np.asarray(point, dtype=float)
    for cell in np.argsort(((centres - p) ** 2).sum(axis=1))[:candidates]:
        own = np.nonzero(mesh.owner == cell)[0]
        nei = np.nonzero(mesh.neighbour == cell)[0]
        side = np.concatenate([((p - fc[own]) * fv[own]).sum(axis=1), -((p - fc[nei]) * fv[nei]).sum(axis=1)])
        tol = 1e-9 * np.linalg.norm(np.concatenate([fv[own], fv[nei]]), axis=1)
        if (side <= tol).all():
            return int(cell)
    return None


def measure(case, case_dir: Path, inputs, points: dict, length: float) -> dict:
    planned = inputs.fixed_layers
    t0 = time.monotonic()
    run = MeshRun(case_dir, parts=inputs.patches, first_layer=planned if planned and planned[1] else None, cores=1,
                  step_timeout_s=3600)
    run.start()
    result = run.wait()
    out: dict = {"mesh_s": round(time.monotonic() - t0, 1)}
    report = result.report if result is not None else None
    if report is None:
        out["error"] = f"meshing failed at {result.failed_step if result else 'start'}"
        return out
    soft = [line for line in report.failed_check_lines if check_class(line) == "soft"]
    quality = metrics.parse_check_mesh_quality((case_dir / "logs" / "log.checkMesh").read_text(errors="replace"))
    faces = face_quality(case_dir)
    out.update({"cells": report.cells, "valid": report.valid, "hard": list(report.hard_failures), "soft": soft,
                "max_non_ortho": quality.get("max_non_ortho"), "faces_gt70": faces.get("faces_non_ortho_gt70"),
                "max_skewness": quality.get("max_skewness")})
    target = planned[1] if planned else 0
    walk = walk_measurements(case, case_dir, inputs, target)
    walls = walk.get("walls", {})
    out["coverage_percent"] = walls.get("coverage_percent")
    out["mean_layers"] = walls.get("mean_layers")
    out["first_cell_m"] = (walls.get("first_cell") or {}).get("mean_m")
    out["planned_first_m"] = planned[0] if planned else None
    out["zones"] = {z: {"coverage_percent": d.get("coverage_percent"), "first_cell_m": (d.get("first_cell") or {}).get("mean_m")}
                    for z, d in walk.get("zones", {}).items()}
    poly = PolyMesh.read(case_dir)
    centres, size = cell_sizes(poly)
    fc, fv, _ = face_geometry(poly.points, poly.faces)
    out["point_cell_m"], out["containing_cell_m"] = {}, {}
    for name, p in points.items():
        near = ((centres - np.asarray(p)) ** 2).sum(axis=1) <= (0.1 * length) ** 2
        out["point_cell_m"][name] = {"median": float(np.median(size[near])) if near.any() else None,
                                     "cells": int(near.sum())}
        cell = containing_cell(poly, (fc, fv), centres, p)
        if cell is None:  # the point on a face or edge: the cell with the nearest centre
            cell = int(np.argmin(((centres - np.asarray(p)) ** 2).sum(axis=1)))
        out["containing_cell_m"][name] = float(size[cell])
    return out


def cube_means(case_dir: Path, points: dict, sides: dict) -> dict:
    """QUESTIONS 204 (b): per point, the volume-weighted mean cell size (sum V h / sum V, h = V^(1/3)) of the cells
    whose centres lie in the axis-aligned cube of side ``sides[point]`` (2 coarse cells) centred on it, and their
    count."""
    centres, size = cell_sizes(PolyMesh.read(case_dir))
    volume = size ** 3
    out = {}
    for name, p in points.items():
        inside = (np.abs(centres - np.asarray(p)) <= sides[name] / 2).all(axis=1)
        out[name] = {"mean_m": float((volume[inside] * size[inside]).sum() / volume[inside].sum()) if inside.any()
                     else None, "cells": int(inside.sum()), "side_m": sides[name]}
    return out


def run_case(name: str, singles: bool) -> dict:
    case = CASES[name]
    work = WORK / name
    project = new_project(case, work)
    import_geometry(project, ensure_geometry(case.geometry, GEOMETRY), case.units, case.import_mode)
    captured = []
    original = mesh_study.build_mesh_files

    def capture(inputs):  # the level inputs prepare_study writes (one per level, in order)
        captured.append(inputs)
        return original(inputs)

    mesh_study.build_mesh_files = capture
    try:
        plan = mesh_study.plan_study(project)
        study_dir, record, _ = mesh_study.prepare_study(project)
    finally:
        mesh_study.build_mesh_files = original
    length = case.reference_length
    points = fixed_points(captured[0].parts_bounds, length)
    out = {"case": name, "ratio": record.ratio, "current_as": record.current_as, "points": points,
           "reference_length": length, "levels": []}
    sides = None
    for lp, inputs in zip(plan.levels, captured):
        study_case = level_dir(study_dir, lp.level.index)
        row = {"level": lp.level.name, "factor": lp.level.factor, "base_m": lp.estimate.base_size,
               "surface_m": lp.estimate.surface_size, "buffer_scale": inputs.buffer_scale}
        single_case = None
        if singles:  # the same settings as a single mesh (nCellsBetweenLevels 3, no shells)
            single_case = work / f"single_{lp.level.name}"
            if single_case.exists():
                shutil.rmtree(single_case)
            shutil.copytree(study_case, single_case)
            single_inputs = dataclasses.replace(inputs, buffer_scale=1.0, study_level=False)
            prepare_case_dir(single_case, build_mesh_files(single_inputs))
        say(f"{name} {lp.level.name}: study level (buffer scale {inputs.buffer_scale:.4g})")
        row["study"] = measure(case, study_case, inputs, points, length)
        if sides is None:  # the coarse level (the first): 2 of its cells around each point
            sides = {n: 2.0 * v for n, v in row["study"]["containing_cell_m"].items()}
        row["study"]["cube_mean"] = cube_means(study_case, points, sides)
        say(f"  {json.dumps({k: row['study'].get(k) for k in ('cells', 'valid', 'max_non_ortho', 'faces_gt70', 'coverage_percent')})}")
        if single_case is not None:
            say(f"{name} {lp.level.name}: single mesh")
            row["single"] = measure(case, single_case, single_inputs, points, length)
            say(f"  {json.dumps({k: row['single'].get(k) for k in ('cells', 'valid', 'max_non_ortho', 'faces_gt70', 'coverage_percent')})}")
        else:
            row["single"] = "not meshed (--singles; previous check: docs/validation/study3d/result_q203.json)"
        out["levels"].append(row)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", nargs="+", default=["sphere", "wing"])
    parser.add_argument("--singles", action="store_true", help="also mesh every level as a single mesh")
    parser.add_argument("--out", default="result.json")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for name in args.cases:
        results.append(run_case(name, args.singles))
        (OUT / args.out).write_text(json.dumps({"cases": results}, indent=2, default=float) + "\n")
    say(f"wrote {OUT / args.out}")


if __name__ == "__main__":
    main()
