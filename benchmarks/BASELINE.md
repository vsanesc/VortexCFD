# Meshing benchmark baseline (after task 5.4b)

The mesher with the app's defaults after task 5.4b (D-105 to D-109), measured on 2026-10-20 14:22:14 UTC at
git `37b1281` (clean tree) on the development PC (12 physical cores, Ryzen 9 5900X, WSL2), each case's meshing
on one core under `nice -n 15`. Full benchmark wall-clock: 585 s. Result file: `baseline.json` (D-081, D-082,
D-091, D-092, D-105); the run and its analysis are in RESULT_5.4b.md (Part F). y+ values are indicative, not
converged (a fixed 400-iteration run). The headline layer columns are counted from the mesh (Basis "mesh",
D-105); snappyHexMesh's own strict coverage is the column beside it.

Earlier baselines: `baseline_0.json` is the pre-5.1 mesher (surface size from L, seed lines as snap features,
3 relative layers, full-span wing: not comparable for the wing); `baseline_1.json` is the pre-5.4 mesher (the
5.1b run at git `8bca687`: the 5.1 layer controls, the first layer at the target distance, layer columns from
snappyHexMesh's fields only).

## Case definitions

Every case starts from a new simulation with the built-in "External flow" preset (D-081): box domain
(5 L upstream, 10 L downstream, 5 L lateral and vertical), 100,000 background cells, target surface size
0.01 l_ref with curvature refinement up to 2 levels above the surface level (D-085), absolute layer sizing
for y+ 50 with Re on l_ref (D-086, D-088) and the target at the first cell centre (first layer twice the
target distance, D-107), the robust layer controls (D-106: layer cap 12 with the expansion ratio raised up to
1.3, layer featureAngle 130, nOuterIter 2, the tet-quality check on during layer addition), 20 m/s, k-omega
SST. Deviations:

- sphere: diameter 1 m, STL (control case); l_ref = 1 m (the diameter).
- wing: half wing NACA 0012, chord 1 m, span 1.5 m from the root on a y_min symmetry plane, trailing
  edge 0.25 % of the chord, flat tip, STEP; `domain.symmetry = 'y_min'`; l_ref = 1 m (the chord). Zones:
  trailing edge (x/c >= 0.95), tip (within 5 % of the chord of y = 1.5 m), root (within 5 % of the chord
  of the symmetry plane) (D-092).
- ahmed: Ahmed-type body 1.044 x 0.389 x 0.288 m, front radius 0.1 m, 25 degree slant, no stilts, STEP;
  l_ref = 1.044 m (the length). Zones: slant edges, rear-face edges (within 0.02 m).
- The indicative y+ run of every case: solvers.iterations = 400 (fixed, stopping criteria removed),
  solvers.write_interval = 400, solvers.cores = cells / 50,000, at most 10 and two cores left free
  (D-092): sphere 4, wing 6, ahmed 4.

## Table

| Case | Status | Cells | Max non-ortho | Avg non-ortho | Faces >65 | Faces >70 | Max skew | Faces skew>4 | Max AR | Failed checks | Hard | Soft | Strict coverage % | Basis | Strict cov. % (snappy fields) | Target layers | Extruded % | Mean layers | Mean / target % | >=80 % of target % | No layer % | Layer faces removed by checks | Worst zone | Worst zone % | Thickness % of target | Fidelity RMS mm | Fidelity max mm | Fidelity RMS/ref | Fidelity max/ref | ref m | y+ mean | y+ in band % | y+ cores | Mesh s | Total s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere | ok | 233534 | 46.5 | 7.38 | 0 | 0 | 0.85 | 0 | 8.2 | 0 | 0 | 0 | 99.6 | mesh | 100.0 | 6 | 100.0 | 6.02 | 100.4 | 99.9 | 0.0 | 0 | - | - | 101.2 | 0.089 | 0.154 | 8.88e-05 | 1.54e-04 | 1 | 49.6 | 73.4 | 4 | 48 | 189 |
| wing | ok | 300025 | 64.9 | 7.24 | 0 | 0 | 2.82 | 0 | 16.8 | 0 | 0 | 0 | 94.4 | mesh | 94.4 | 7 | 98.2 | 6.81 | 97.3 | 96.4 | 1.8 | 14 | trailing_edge | 38.4 | 96.3 | 0.107 | 0.777 | 1.07e-04 | 7.77e-04 | 1 | 52.2 | 99.0 | 6 | 58 | 214 |
| ahmed | ok | 231606 | 64.3 | 7.25 | 0 | 0 | 2.38 | 0 | 11.6 | 0 | 0 | 0 | 96.5 | mesh | 96.8 | 6 | 98.5 | 5.92 | 98.7 | 97.4 | 1.5 | 12 | slant_edges | 56.0 | 99.8 | 0.063 | 0.363 | 6.07e-05 | 3.48e-04 | 1.044 | 51.2 | 95.6 | 4 | 42 | 179 |

Columns: hard / soft = checkMesh failures by the D-100 classes; strict coverage = wall area with the full
target layer count (D-087), counted from the mesh (D-105); mean / target, >= 80 % of target and no layer are
the layer diagnostics of D-091; "layer faces removed by checks" counts the faces whose extrusion
snappyHexMesh's layer-mesh check removed; fidelity = distance from the mesh wall points to the original
surface, in mm and over the reference length "ref m" (sphere diameter, wing chord, body length); y+ in band =
wall area with y+ in [25, 100] (0.5 to 2 times the target 50); times in seconds (mesh = blockMesh to
checkMesh, total = the whole case with the y+ run).

## Observations

1. All three meshes pass checkMesh with 0 failed checks and no lost part; the largest mesh has 300,025 cells.
   Max non-orthogonality 46.5 / 64.9 / 64.3 degrees (sphere / wing / Ahmed body); 0 faces above 65 degrees.
2. Strict coverage 99.6 / 94.4 / 96.5 % of 6 / 7 / 6 layers (first layer 1.80 mm); the worst zones are the
   wing's trailing edge (38.4 %) and the Ahmed body's slant edges (56.0 %).
3. y+ after 400 iterations (target 50): area-weighted mean 49.6 / 52.2 / 51.2, 73.4 / 99.0 / 95.6 % of the wall
   area in [25, 100].
4. Surface fidelity unchanged since baseline_1: RMS 0.089 / 0.107 / 0.063 mm, max 0.154 / 0.777 / 0.363 mm.
5. Cost: 231,606 to 300,025 cells, meshing 42 to 58 s, totals 179 to 214 s with the y+ runs on 4 to 6 cores.
