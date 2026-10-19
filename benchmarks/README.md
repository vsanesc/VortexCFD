# Meshing benchmark (Phase 5.0)

Measures the app's mesher with its default settings on three generated geometries (D-081, D-082):
sphere (STL, control), NACA 0012 half wing with a 0.25 % trailing edge, its root on a y_min symmetry
plane (STEP; D-092) and an Ahmed-type body with sharp rear edges (STEP). Each case runs through the app's own pipeline: project with the "External
flow" preset, geometry import, box domain, meshing case, blockMesh / snappyHexMesh / checkMesh, the
MeshReport guards, then a short indicative y+ run. Each case sets its l_ref (sphere diameter, wing
chord, body length), from which the surface cell size follows (D-085).

## Run

```bash
nice -n 15 .venv/bin/python -m vortexcfd.bench
```

About 10 minutes on the development PC (Ryzen 9 5900X). Options:

- `--cases sphere wing`: only these cases.
- `--no-solve`: mesh only (no y+ run).
- `--compare benchmarks/baseline.json`: print the deltas and the regressions against another result
  (exit code 1 on a regression; a slower run is only flagged).
- `--result <file> --compare <file>`: compare two existing results without running.
- `--generate`: regenerate the geometries only (also `benchmarks/geometries/generate.py`).

Results go to `benchmarks/results/<UTC date and time>_<git sha>.json` and `.md` (git-ignored); the
case projects to `run/bench/<case>/`. The geometry files in `benchmarks/geometries/` are generated
when missing and are git-ignored.

## Local cases (D-094)

Optional cases on geometry that must not enter the repository (the owner's models). Copy
`local_cases.example.json` to `benchmarks/local_cases.json` (git-ignored), point it at the files and
run:

```bash
nice -n 15 .venv/bin/python -m vortexcfd.bench --local
```

`--cases <name> ...` picks some of them. A missing config or geometry file skips the cases with a
message. Each case: a geometry file, the import's answer for several bodies (`import_mode`, "parts"
by default in the example), an optional surface preparation (`surface_prep`: null,
"intersection_features" or "cad_union", D-093), whether the y+ run follows (`solve`), and mesh /
inflow / domain deviations. The shared `reference` block names the clean reference CAD file, its
components (body indices), l_ref (`{"mean_chord": "<component>"}`) and the zones (junction bands
around a component's intersection curves, the trailing edge, the tips; half-width `band` x l_ref).
Metrics on top of the usual ones: fidelity against the reference's outer skin in both directions
(mesh -> reference and reference -> mesh: max and RMS in mm, share further than half the local cell
size), overall and per zone; wall surface left inside a component; faces per component patch; the
per-part force partition check. Projects and a reference cache go to
~/.cache/vortexcfd/bench_local/ (outside the repository); results to benchmarks/results/local/
(git-ignored); local results are never part of baseline.json.

## Files

- `baseline.json`, `BASELINE.md`: the committed baseline of the current mesher (the 5.1b run).
- `baseline_0.json`: the previous baseline, the pre-5.1 mesher (full-span wing: not comparable for the wing).
- `geometries/generate.py`: regenerates the geometries (generators in `src/vortexcfd/bench/geometries.py`).
- Case definitions: `src/vortexcfd/bench/cases.py`; metrics: `src/vortexcfd/bench/metrics.py`.
- `RESULT_5.1.md`, `result_5.1.json`: the benchmark after the 5.1 sizing changes (l_ref surface size,
  curvature refinement, absolute y+ 50 layers, seed lines out of snapping) against `baseline_0.json`.
- `RESULT_5.1b.md`: the run after the 5.1 review (half wing, y+ cores, layer diagnostics) that became
  `baseline.json`.
- `local_cases.example.json`: the format of the git-ignored local cases (D-094).
- `RESULT_5.2_before.md`, `RESULT_5.2.md`: the owner's aircraft (local, numbers only) before surface
  preparation and with each strategy (D-093), and the public re-run against `baseline.json`.

## Metrics (D-082)

- Quality (checkMesh): max and average non-orthogonality, faces above 65 and 70 degrees, max skewness
  and faces above 4, max aspect ratio, failed checks by type.
- Layers (snappyHexMesh layer fields, area-weighted, per wall patch and per zone): strict coverage = area
  with the full target layer count (the headline, D-087; the target count is shown next to it),
  extruded = area with at least one layer, mean layers, achieved thickness against the wanted one. Zones: the wing's trailing-edge band and tips, the Ahmed body's
  slant and rear edges; zones and patches under 80 % are listed.
- Cost: cells, snappyHexMesh stage times, step and total times, peak memory of the largest child process.
- Robustness: mesh valid, lost parts, domain guard; surface fidelity (wall points to the original
  surface, max and RMS over the reference length).
- y+ (indicative, not converged): a fixed 400-iteration run with the default physics on cells / 50,000
  cores (at most 10, two cores left free; recorded, D-092); min, mean, max and the wall area with y+ in
  [0.5, 2] times the target.
- Layer diagnostics (D-091): mean layers / target, area with at least 80 % of the target count, area with
  no layer, area per layer count; from the snappyHexMesh log, layer faces removed by the quality checks
  and the checks that failed while the mesh was shrunk for the layers.
- Fidelity in mm and relative to the case's reference length (stated).

Tests: `tests/test_bench_metrics.py` and `tests/test_bench_geometries.py` (fast);
`tests/test_bench_run.py` runs the sphere case for real (marker `bench`, `pytest -m bench`).
