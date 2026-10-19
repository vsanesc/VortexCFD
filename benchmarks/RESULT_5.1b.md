# Benchmark after the 5.1 review changes (5.1b)

One full run of `nice -n 15 .venv/bin/python -m vortexcfd.bench --compare benchmarks/result_5.1.json` on
2026-10-19 (UTC 10:18), git 8bca687 (clean tree). Result: `benchmarks/baseline_candidate.json` (a copy of
`benchmarks/results/20261019T101806Z_8bca687.json`). `benchmarks/baseline.json` is unchanged: the owner
decides.

Changes since RESULT_5.1.md: the y+ first layer takes its Reynolds number from l_ref (D-088); the wing
case is a half wing, span 1.5 m, its root on a y_min symmetry plane (D-092; not comparable with the
earlier wing); the y+ runs use cells / 50,000 cores, at most 10 (D-092); fidelity in mm and the layer
diagnostics (D-091).

**Full run wall-clock: 632 s (10.5 min)**, against 1,477 s for RESULT_5.1. All meshes Mesh OK, 0 failed
checks, no lost part, every mesh under 500,000 cells.

## Table (as printed)

| Case | Status | Cells | Max non-ortho | Avg non-ortho | Faces >65 | Faces >70 | Max skew | Faces skew>4 | Max AR | Failed checks | Strict coverage % | Target layers | Extruded % | Mean layers | Mean / target % | >=80 % of target % | No layer % | Layer faces removed by checks | Worst zone | Worst zone % | Thickness % of target | Fidelity RMS mm | Fidelity max mm | Fidelity RMS/ref | Fidelity max/ref | ref m | y+ mean | y+ in band % | y+ cores | Mesh s | Total s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere | ok | 276078 | 46.6 | 7.06 | 0 | 0 | 0.85 | 0 | 14.4 | 0 | 100.0 | 10 | 100.0 | 10.00 | 100.0 | 100.0 | 0.0 | 0 | - | - | 100.0 | 0.089 | 0.154 | 8.88e-05 | 1.54e-04 | 1 | 26.8 | 60.5 | 5 | 50 | 225 |
| wing | ok | 337824 | 64.8 | 8.16 | 0 | 0 | 2.86 | 0 | 25.7 | 0 | 78.4 | 11 | 99.9 | 9.79 | 89.0 | 82.4 | 0.1 | 2 | trailing_edge | 0.0 | 97.3 | 0.107 | 0.777 | 1.07e-04 | 7.77e-04 | 1 | 43.3 | 67.6 | 6 | 50 | 231 |
| ahmed | ok | 225842 | 64.9 | 10.89 | 0 | 0 | 1.43 | 0 | 19.0 | 0 | 31.0 | 10 | 99.9 | 6.86 | 68.6 | 49.8 | 0.1 | 0 | rear_edges | 0.0 | 93.2 | 0.063 | 0.363 | 6.07e-05 | 3.48e-04 | 1.044 | 67.8 | 57.9 | 4 | 34 | 174 |

Fidelity: "ref m" is the length the relative values are divided by (the case's reference length,
D-081); the mm columns are absolute. y+ in band = wall area with y+ in [25, 100] (target 50); y+ values
are indicative (400 iterations). "Layer faces removed by checks" counts the faces whose extrusion the
layer-mesh quality check removed.

## Layer diagnostics per zone

| Case / zone | Target | Strict coverage % | Mean layers | Mean / target % | >= 80 % of target % | No layer % | Thickness % |
|---|---|---|---|---|---|---|---|
| sphere walls | 10 | 100.0 | 10.00 | 100.0 | 100.0 | 0.0 | 100.0 |
| wing walls | 11 | 78.4 | 9.79 | 89.0 | 82.4 | 0.1 | 97.3 |
| wing trailing_edge | 11 | 0.0 | 3.10 | 28.1 | 0.0 | 0.5 | 75.0 |
| wing tips | 11 | 0.0 | 2.71 | 24.6 | 0.0 | 1.8 | 72.5 |
| wing root (symmetry plane) | 11 | 90.1 | 10.47 | 95.1 | 92.1 | 0.0 | 98.8 |
| ahmed walls | 10 | 31.0 | 6.86 | 68.6 | 49.8 | 0.1 | 93.2 |
| ahmed slant_edges | 10 | 14.5 | 3.50 | 35.0 | 21.1 | 0.0 | 67.0 |
| ahmed rear_edges | 10 | 0.0 | 1.45 | 14.5 | 0.0 | 0.0 | 52.4 |

Wall area by layer count (%):

| Case | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| wing | 0.1 | 2.0 | 2.1 | 2.6 | 2.1 | 2.3 | 2.3 | 2.1 | 2.0 | 2.0 | 1.9 | 78.4 |
| ahmed | 0.1 | 6.3 | 6.1 | 6.4 | 6.2 | 6.4 | 9.1 | 9.6 | 9.4 | 9.4 | 31.0 | - |

From log.snappyHexMesh (the layer phase):

| Case | Layer iterations | Layer faces removed by checks (check) | Faces in error while shrinking (scaling steps) | Feature-edge points with no layer | Isolated points stopped |
|---|---|---|---|---|---|
| sphere | 1 | 0 | none (0) | 0 | 0 |
| wing | 2 | 2 (face twist < 0.02) | non-orthogonality > 65: 124, face twist < 0.02: 12 (7) | 371 | 39 |
| ahmed | 1 | 0 | non-orthogonality > 65: 441, interpolation weights < 0.05: 56, face pyramid volume < 1e-13: 44, face twist < 0.02: 9, concavity > 80: 4, determinant < 0.001: 5 (4) | 668 | 8 |

## Ahmed body: near-miss or collapse?

Both, in two populations. The 31.0 % strict coverage is not a uniform near-miss:

- **Near-miss on about half of the wall:** 49.8 % of the area has at least 8 of 10 layers (31.0 % has
  all 10, 18.8 % has 8 or 9). One or two more layers there would raise the strict coverage to about 50 %.
- **Real collapse on about a third:** 31.4 % of the area has 1 to 5 layers (6.1-6.4 % for each count) and
  0.1 % has none. It sits at the sharp edges: the rear-face edges keep 1.45 of 10 layers (14.5 %), the
  slant edges 3.50 of 10. Mean over the wall: 6.86 of 10 layers, while the achieved thickness is still 93.2 %
  of the target on average.
- **The quality checks do not remove layers after extrusion:** the layer-mesh check removed 0 faces
  (wing: 2, face twist). **The 65-degree limit acts earlier, while the mesh is shrunk for the layers:** 441
  faces were above maxNonOrtho 65 (plus 56 interpolation-weight, 44 pyramid-volume, 9 twist, 5 determinant
  and 4 concavity errors) and snappyHexMesh scaled the displacement down locally in 4 steps, to zero at
  worst; where the displacement shrinks, the stack is thinner and fewer layers fit. Separately, 668
  points on feature edges sharper than the layer featureAngle (60 degrees) get no displacement at all,
  which is the edge collapse. The log does not say how much area each mechanism costs; both act at the
  same edges.

Not tuned (item 87 / Phase 5.4).

## Other observations

1. The half wing has 337,824 cells (the full-span wing had 964,710 in RESULT_5.1). Its smaller domain
   gives a 0.317 m base cell and surface level 5 (9.9 mm cells, target 10 mm from the 1 m chord).
2. The root on the symmetry plane keeps its layers: 90.1 % strict coverage, 10.47 of 11 layers. The tip and
   the trailing edge collapse (2.71 and 3.10 of 11 layers, 0.0 % strict coverage).
3. y+ with Re on l_ref: wing mean 43.3 (33.9 for the full-span wing with Re on 3 m in RESULT_5.1), 67.6 % of
   the wall in [25, 100]; sphere 26.8 (60.5 %), Ahmed 67.8 (57.9 %): l_ref equals L for those two, so their
   layers did not change.
4. y+ runs: sphere 5 cores, 171 s; wing 6 cores, 172 s; Ahmed 4 cores, 136 s. The full run takes 632 s.
5. Wing fidelity: RMS 0.107 mm, max 0.777 mm (a different, half-span mesh: not comparable with RESULT_5.1).
6. Max non-orthogonality stays at 64.8-64.9 degrees on the wing and the Ahmed body, the maxNonOrtho 65 limit
   of meshQualityControls; no face above 65 in the final meshes.
7. Sphere and Ahmed results repeat RESULT_5.1 exactly (cells, quality, layers, fidelity); only their y+ run
   times change (more cores for the sphere).
