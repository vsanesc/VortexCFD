# Benchmark after the 5.1 sizing changes

Full run of `nice -n 15 .venv/bin/python -m vortexcfd.bench --compare benchmarks/baseline.json` on
2026-10-19 (UTC 09:27), result `benchmarks/result_5.1.json` (a copy of
`benchmarks/results/20261019T092748Z_b5fc377-dirty.json`; "-dirty": the strict-coverage report labels of
this part were not yet committed). The baseline `benchmarks/baseline.json` is unchanged: the owner decides
whether this result replaces it. One full run was made (of the two allowed).

Changes measured (task 5.1): seed lines refine without acting as snap features (D-084); the surface cell
size comes from l_ref (each case sets it: sphere diameter 1 m, wing chord 1 m, Ahmed length 1.044 m) with
curvature refinement up to 2 levels above the part's surface level (D-085); absolute layer sizing for a
target y+ of 50 (D-086); strict coverage is the headline layer metric (D-087).

**Over the limits set for this task (reported, not tuned):** the wing mesh has 964,710 cells (over
500,000), and the full run took 1,477 s wall-clock (24.6 min, over 12 min).

## Summary table (this run)

| Case | Status | Cells | Max non-ortho | Avg non-ortho | Faces >65 | Faces >70 | Max skew | Faces skew>4 | Max AR | Failed checks | Strict coverage % | Target layers | Extruded % | Mean layers | Worst zone | Worst zone % | Thickness % of target | Fidelity RMS/L | Fidelity max/L | y+ mean | y+ in band % | Mesh s | Total s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere | ok | 276078 | 46.6 | 7.06 | 0 | 0 | 0.85 | 0 | 14.4 | 0 | 100.0 | 10 | 100.0 | 10.00 | - | - | 100.0 | 8.88e-05 | 1.54e-04 | 27.0 | 60.9 | 57 | 280 |
| wing | ok | 964710 | 65.0 | 8.65 | 0 | 0 | 3.03 | 0 | 14.5 | 0 | 89.7 | 8 | 100.0 | 7.59 | tips | 0.9 | 98.3 | 1.82e-04 | 1.46e-03 | 33.9 | 82.6 | 173 | 1005 |
| ahmed | ok | 225842 | 64.9 | 10.89 | 0 | 0 | 1.43 | 0 | 19.0 | 0 | 31.0 | 10 | 99.9 | 6.86 | rear_edges | 0.0 | 93.2 | 6.07e-05 | 3.48e-04 | 67.8 | 57.8 | 36 | 189 |

## Against the baseline

| Case | Cells | Max non-ortho | Faces >70 | Strict coverage % (target layers) | Worst zone % | Thickness % of target | Fidelity RMS/L | Fidelity max/L | y+ mean | y+ in band % | Total s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere, baseline | 193,151 | 40.2 | 0 | 100.0 (3) | - | 100.0 | 8.88e-05 | 1.54e-04 | 168.9 | 0.0 | 154 |
| sphere, 5.1 | 276,078 | 46.6 | 0 | 100.0 (10) | - | 100.0 | 8.88e-05 | 1.54e-04 | 27.0 | 60.9 | 280 |
| wing, baseline | 199,947 | 61.6 | 0 | 88.9 (3) | trailing_edge 0.0 | 92.9 | 1.33e-04 | 2.66e-03 | 230.5 | 0.0 | 168 |
| wing, 5.1 | 964,710 | 65.0 | 0 | 89.7 (8) | tips 0.9 | 98.3 | 1.82e-04 | 1.46e-03 | 33.9 | 82.6 | 1005 |
| ahmed, baseline | 188,140 | 56.3 | 0 | 87.5 (3) | rear_edges 0.0 | 88.2 | 5.05e-05 | 3.39e-04 | 107.7 | 0.0 | 145 |
| ahmed, 5.1 | 225,842 | 64.9 | 0 | 31.0 (10) | rear_edges 0.0 | 93.2 | 6.07e-05 | 3.48e-04 | 67.8 | 57.8 | 189 |

"y+ in band" is the wall area with y+ in [0.5, 2] times the target: [0.5, 2] in the baseline (target 1,
relative layers that did not aim at it), [25, 100] now (target 50). The y+ values are indicative (400
iterations, not converged). All six meshes: Mesh OK, 0 failed checks, no lost part.

### `--compare` output (as printed)

```
Compared with benchmarks/baseline.json:
  sphere: cells 193151 -> 276078 (82927); max_non_ortho 40.17 -> 46.62 (+6.451); faces_gt70 0 -> 0 (0); coverage 100 -> 100 (+0); target_layers 3 -> 10 (7); worst_zone_coverage - -> - (-); fidelity_rms 8.885e-05 -> 8.881e-05 (-3.625e-08); yplus_mean 168.9 -> 26.97 (-142); total_time 154.3 -> 280.3 (+126)
  wing: cells 199947 -> 964710 (764763); max_non_ortho 61.55 -> 64.99 (+3.435); faces_gt70 0 -> 0 (0); coverage 88.94 -> 89.66 (+0.7203); target_layers 3 -> 8 (5); worst_zone_coverage 0 -> 0.8614 (+0.8614); fidelity_rms 0.0001326 -> 0.000182 (+4.939e-05); yplus_mean 230.5 -> 33.88 (-196.7); total_time 167.8 -> 1005 (+836.9)
  ahmed: cells 188140 -> 225842 (37702); max_non_ortho 56.31 -> 64.91 (+8.598); faces_gt70 0 -> 0 (0); coverage 87.47 -> 31 (-56.47); target_layers 3 -> 10 (7); worst_zone_coverage 0 -> 0 (+0); fidelity_rms 5.046e-05 -> 6.072e-05 (+1.026e-05); yplus_mean 107.7 -> 67.82 (-39.89); total_time 144.6 -> 189.3 (+44.7)
  FLAG sphere: target layer count 3 -> 10: strict coverage counts the full stack, so the coverage figures measure different stacks
  FLAG sphere: total time up 82 % (time is noisy: flag only)
  FLAG wing: target layer count 3 -> 8: strict coverage counts the full stack, so the coverage figures measure different stacks
  FLAG wing: total time up 499 % (time is noisy: flag only)
  FLAG ahmed: target layer count 3 -> 10: strict coverage counts the full stack, so the coverage figures measure different stacks
  FLAG ahmed: total time up 31 % (time is noisy: flag only)
  REGRESSION sphere: max non-orthogonality up 6.5 degrees
  REGRESSION sphere: cells up 42.9 %
  REGRESSION wing: zone tips coverage dropped 4.4 points
  REGRESSION wing: max non-orthogonality up 3.4 degrees
  REGRESSION wing: cells up 382.5 %
  REGRESSION wing: surface fidelity RMS worse by 37.3 %
  REGRESSION ahmed: strict layer coverage dropped 56.5 points
  REGRESSION ahmed: zone slant_edges coverage dropped 14.9 points
  REGRESSION ahmed: max non-orthogonality up 8.6 degrees
  REGRESSION ahmed: cells up 20.0 %
  REGRESSION ahmed: surface fidelity RMS worse by 20.3 %
```

## Regressions and their causes

- **Cells up** (sphere +42.9 %, wing +382.5 %, ahmed +20.0 %). Expected. Sphere and Ahmed body: their
  surface size does not change (l_ref is about L for them: level 5, 8.4 mm surface cells in both runs), so
  the rise is the y+ layer stack (10 layers instead of 3). Wing: the surface size from the chord (level
  7, 6.0 mm surface cells instead of level 5, 24.1 mm). Mesh-only development runs with 3 relative layers
  split the wing's rise: 199,947 -> 666,740 cells from l_ref, +6,888 from curvature refinement (673,628);
  the 8-layer y+ stack takes it to 964,710.
- **Max non-orthogonality up** (sphere +6.5, wing +3.4, ahmed +8.6 degrees). Most likely the thinner,
  more numerous y+ layers: absolute sizing uses the relaxed controls during layer addition (D-045), and the
  wing and Ahmed meshes now reach 65.0 and 64.9 degrees, at the maxNonOrtho 65 of meshQualityControls.
  No face above 65 or 70 degrees in any case. Not confirmed by a run with relative layers.
- **Ahmed strict coverage down 56.5 points; slant-edge zone down 14.9 points; wing tips zone down 4.4
  points.** Strict coverage now counts a 10-layer (Ahmed) or 8-layer (wing) stack instead of 3, so the
  figures measure different stacks (the comparison flags it). The layers are still there: extruded is
  99.9 % and 100 %; mean layers 6.86 of 10 (Ahmed) and 3.89 of 8 at the wing tips (1.42 of 3 before);
  thickness reaches 93.2 % (Ahmed) and 83.7 % at the wing tips (41.5 % before). The collapse at sharp
  edges is item 87 (Phase 5.4).
- **Surface fidelity RMS worse** (wing +37.3 %, ahmed +20.3 %). Wing: cause not confirmed. Likely, the
  measure changes with the mesh: 69,942 wall points instead of 10,998 sample the snapped surface between
  the vertices of the app's import tessellation (deflection 1e-3 of the diagonal, D-070), where it departs
  from the fine reference tessellation. The wing's max deviation improves from 2.66 mm to 1.46 mm (the
  seed-line spikes are gone, D-084). Ahmed body: same surface level, 11,966 wall points instead of 11,128.
  Cause not known; the layer stack is the only change that affects this case.
- **Total time up** (flag only): sphere +82 %, wing +499 %, ahmed +31 %. The y+ runs dominate: the wing's
  took 813 s on 4 cores (965k cells; the baseline's 123 s on 3 cores), the sphere's 219 s (126 s before).
  Wing meshing took 173 s (castellation-only run 72 s, snap and layers run 93 s).

## Observations

1. y+ moves towards the target of 50: the area-weighted mean is 27.0 (sphere), 33.9 (wing) and 67.8
   (Ahmed), against 169, 231 and 108 in the baseline; 60.9 %, 82.6 % and 57.8 % of the wall area are in
   [25, 100] (0.0 % of the baseline's band in every case). The first layer comes from the flat-plate
   estimate with Re on L (3 m for the wing, not its chord), so the targets are not met exactly.
2. The wing has 4.8 times the baseline's cells (964,710). l_ref accounts for 466,793 of the mesh-only
   rise and curvature refinement for 6,888 (development runs); the y+ layer stack adds about 290,000.
3. Curvature refinement acts only on the wing in this set: on the leading edge (radius 0.0159 m) 4 cells
   per radius need level 8 against the surface level 7. The sphere (radius 0.5 m) and the Ahmed front
   (radius 0.1 m) would need levels at or below their surface level 5, so they get none.
4. The seed lines are out of the snapping run: the wing's largest deviation is 1.46 mm (1.46e-03 of the
   chord) instead of 2.66 mm; with the finer surface the RMS is 0.18 mm (0.13 mm before; see above).
5. Layer stacks hold on smooth walls (sphere: 10 of 10 layers on 100 % of the area, thickness 100 %)
   and collapse at sharp edges as before: the wing's trailing edge has 4.24 of 8 layers (10.5 % full
   stack), the tips 3.89 of 8 (0.9 %), the Ahmed rear edges 1.45 of 10 (0.0 %).
6. Mesh quality stays within the checks: 0 failed checks, no face above 65 degrees, max skewness 3.03
   (wing), 1.43 (Ahmed), 0.85 (sphere); max aspect ratio 14.4 to 19.0 (3.7 to 8.8 in the baseline; most likely
   the thin y+ layers).
7. Peak memory of the largest process: 1,586 MiB for the wing (snappyHexMesh and solver rank), 493 MiB
   sphere, 438 MiB Ahmed.
8. Cost: the full benchmark now takes 24.6 min (469 s for the baseline); 813 s of it is the wing's y+
   run. The 400-iteration y+ run was sized for the baseline's meshes (D-082).
