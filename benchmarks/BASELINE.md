# Meshing benchmark baseline (after task 5.1)

The mesher with the app's defaults after task 5.1 (D-084 to D-092), measured on 2026-10-19 10:18:06 UTC
at git `8bca687` (clean tree) on the development PC (12 physical cores, Ryzen 9 5900X, WSL2). Full
benchmark wall-clock: 632 s. Result file: `baseline.json` (D-081, D-082, D-091, D-092); the run and its
analysis are in RESULT_5.1b.md. y+ values are indicative, not converged (a fixed 400-iteration run).

`baseline_0.json` is the previous baseline: the pre-5.1 mesher (surface size from L, seed lines as snap
features, 3 relative layers, full-span wing). It is not comparable for the wing (a different geometry:
the full 3 m span then, the 1.5 m half wing now).

## Case definitions

Every case starts from a new simulation with the built-in "External flow" preset (D-081): box domain
(5 L upstream, 10 L downstream, 5 L lateral and vertical), 100,000 background cells, target surface size
0.01 l_ref with curvature refinement up to 2 levels above the surface level (D-085), absolute layer
sizing for y+ 50 with Re on l_ref (D-086, D-088), 20 m/s, k-omega SST. Deviations:

- sphere: diameter 1 m, STL (control case); l_ref = 1 m (the diameter).
- wing: half wing NACA 0012, chord 1 m, span 1.5 m from the root on a y_min symmetry plane, trailing
  edge 0.25 % of the chord, flat tip, STEP; `domain.symmetry = 'y_min'`; l_ref = 1 m (the chord). Zones:
  trailing edge (x/c >= 0.95), tip (within 5 % of the chord of y = 1.5 m), root (within 5 % of the chord
  of the symmetry plane) (D-092).
- ahmed: Ahmed-type body 1.044 x 0.389 x 0.288 m, front radius 0.1 m, 25 degree slant, no stilts, STEP;
  l_ref = 1.044 m (the length). Zones: slant edges, rear-face edges (within 0.02 m).
- The indicative y+ run of every case: solvers.iterations = 400 (fixed, stopping criteria removed),
  solvers.write_interval = 400, solvers.cores = cells / 50,000, at most 10 and two cores left free
  (D-092): sphere 5, wing 6, ahmed 4.

## Table

| Case | Status | Cells | Max non-ortho | Avg non-ortho | Faces >65 | Faces >70 | Max skew | Faces skew>4 | Max AR | Failed checks | Strict coverage % | Target layers | Extruded % | Mean layers | Mean / target % | >=80 % of target % | No layer % | Layer faces removed by checks | Worst zone | Worst zone % | Thickness % of target | Fidelity RMS mm | Fidelity max mm | Fidelity RMS/ref | Fidelity max/ref | ref m | y+ mean | y+ in band % | y+ cores | Mesh s | Total s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere | ok | 276078 | 46.6 | 7.06 | 0 | 0 | 0.85 | 0 | 14.4 | 0 | 100.0 | 10 | 100.0 | 10.00 | 100.0 | 100.0 | 0.0 | 0 | - | - | 100.0 | 0.089 | 0.154 | 8.88e-05 | 1.54e-04 | 1 | 26.8 | 60.5 | 5 | 50 | 225 |
| wing | ok | 337824 | 64.8 | 8.16 | 0 | 0 | 2.86 | 0 | 25.7 | 0 | 78.4 | 11 | 99.9 | 9.79 | 89.0 | 82.4 | 0.1 | 2 | trailing_edge | 0.0 | 97.3 | 0.107 | 0.777 | 1.07e-04 | 7.77e-04 | 1 | 43.3 | 67.6 | 6 | 50 | 231 |
| ahmed | ok | 225842 | 64.9 | 10.89 | 0 | 0 | 1.43 | 0 | 19.0 | 0 | 31.0 | 10 | 99.9 | 6.86 | 68.6 | 49.8 | 0.1 | 0 | rear_edges | 0.0 | 93.2 | 0.063 | 0.363 | 6.07e-05 | 3.48e-04 | 1.044 | 67.8 | 57.9 | 4 | 34 | 174 |

Columns: strict coverage = wall area with the full target layer count (D-087); mean / target, >= 80 %
of target and no layer are the layer diagnostics of D-091; "layer faces removed by checks" counts the
faces whose extrusion snappyHexMesh's layer-mesh check removed; fidelity = distance from the mesh wall
points to the original surface, in mm and over the reference length "ref m" (sphere diameter, wing
chord, body length); y+ in band = wall area with y+ in [25, 100] (0.5 to 2 times the target 50); times
in seconds (mesh = blockMesh to checkMesh, total = the whole case with the y+ run).

## Observations

1. All three meshes pass checkMesh with 0 failed checks and no lost part; every mesh is under 340,000
   cells. Max non-orthogonality 46.6 / 64.8 / 64.9 degrees (sphere / wing / Ahmed body), at the
   maxNonOrtho 65 limit for the wing and the body; 0 faces above 65 degrees.
2. Sphere: 10 of 10 layers on 100 % of the wall, fidelity unchanged from baseline_0 (RMS 0.089 mm).
3. Half wing: 78.4 % strict coverage of 11 layers, 82.4 % of the area with at least 9 layers. The root on
   the symmetry plane keeps its layers (90.1 %, 10.47 of 11); the trailing edge (3.10 of 11) and the tip
   (2.71 of 11) collapse (0.0 % strict coverage).
4. Ahmed body: 31.0 % strict coverage of 10 layers, but 49.8 % of the area has at least 8 layers; 31.4 %
   has 1 to 5 layers, at the sharp edges (rear edges 1.45 of 10, slant edges 3.50 of 10). The layer-mesh
   check removed no faces; while the mesh was shrunk for the layers, 441 faces exceeded non-orthogonality
   65 and the displacement was scaled down, and 668 feature-edge points sharper than 60 degrees got no
   layer (docs/QUESTIONS.md item 106, input for 5.4).
5. y+ after 400 iterations (target 50): area-weighted mean 26.8 / 43.3 / 67.8, 60.5 / 67.6 / 57.9 % of
   the wall area in [25, 100].
6. Surface fidelity: RMS 0.089 / 0.107 / 0.063 mm, max 0.154 / 0.777 / 0.363 mm.
7. Cost: 225,842 to 337,824 cells, meshing 34 to 50 s; y+ runs 136 to 172 s on 4 to 6 cores; peak memory
   of the largest child process 412 to 583 MiB while meshing and 903 MiB in the wing's solver stage.
