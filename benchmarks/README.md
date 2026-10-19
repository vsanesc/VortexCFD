# Meshing benchmark (Phase 5.0)

Measures the app's mesher with its default settings on three generated geometries (D-081, D-082):
sphere (STL, control), NACA 0012 wing with a 0.25 % trailing edge (STEP) and an Ahmed-type body with
sharp rear edges (STEP). Each case runs through the app's own pipeline: project with the "External
flow" preset, geometry import, box domain, meshing case, blockMesh / snappyHexMesh / checkMesh, the
MeshReport guards, then a short indicative y+ run.

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

## Files

- `baseline.json`, `BASELINE.md`: the committed baseline of the current mesher.
- `geometries/generate.py`: regenerates the geometries (generators in `src/vortexcfd/bench/geometries.py`).
- Case definitions: `src/vortexcfd/bench/cases.py`; metrics: `src/vortexcfd/bench/metrics.py`.

## Metrics (D-082)

- Quality (checkMesh): max and average non-orthogonality, faces above 65 and 70 degrees, max skewness
  and faces above 4, max aspect ratio, failed checks by type.
- Layers (snappyHexMesh layer fields, area-weighted, per wall patch and per zone): coverage = area with
  the full target layer count, extruded = area with at least one layer, mean layers, achieved
  thickness against the wanted one. Zones: the wing's trailing-edge band and tips, the Ahmed body's
  slant and rear edges; zones and patches under 80 % are listed.
- Cost: cells, snappyHexMesh stage times, step and total times, peak memory of the largest child process.
- Robustness: mesh valid, lost parts, domain guard; surface fidelity (wall points to the original
  surface, max and RMS over the reference length).
- y+ (indicative, not converged): a fixed 400-iteration run with the default physics on the
  recommended cores; min, mean, max and the wall area with y+ in [0.5, 2] times the target.

Tests: `tests/test_bench_metrics.py` and `tests/test_bench_geometries.py` (fast);
`tests/test_bench_run.py` runs the sphere case for real (marker `bench`, `pytest -m bench`).
