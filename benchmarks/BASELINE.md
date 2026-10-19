# Meshing benchmark baseline (Phase 5.0)

The current mesher (snappyHexMesh through the app's default settings), measured on 2026-10-19 06:28:57 UTC at git
`a47f09c` on the development PC (12 physical cores, Ryzen 9 5900X, WSL2). Full
benchmark wall-clock: 469 s. Result file: `baseline.json` (D-081, D-082). y+ values are indicative,
not converged (a fixed 400-iteration run).

| Case | Status | Cells | Max non-ortho | Avg non-ortho | Faces >65 | Faces >70 | Max skew | Faces skew>4 | Max AR | Failed checks | Wall coverage % | Extruded % | Mean layers | Worst zone | Worst zone % | Thickness % of target | Fidelity RMS/L | Fidelity max/L | y+ mean | y+ in band % | Mesh s | Total s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere | ok | 193151 | 40.2 | 7.22 | 0 | 0 | 0.51 | 0 | 3.7 | 0 | 100.0 | 100.0 | 3.00 | - | - | 100.0 | 8.88e-05 | 1.54e-04 | 168.9 | 0.0 | 26 | 154 |
| wing | ok | 199947 | 61.5 | 6.70 | 0 | 0 | 1.98 | 0 | 8.8 | 0 | 88.9 | 99.1 | 2.82 | trailing_edge | 0.0 | 92.9 | 1.33e-04 | 2.66e-03 | 230.5 | 0.0 | 36 | 168 |
| ahmed | ok | 188140 | 56.3 | 7.98 | 0 | 0 | 1.43 | 0 | 8.2 | 0 | 87.5 | 99.9 | 2.81 | rear_edges | 0.0 | 88.2 | 5.05e-05 | 3.39e-04 | 107.7 | 0.0 | 32 | 145 |

Columns: coverage = wall area with the full target layer count (3); extruded = area with at least one
layer; worst zone = the zone with the lowest coverage; fidelity = distance from the mesh wall points to
the original surface over the reference length (sphere diameter, wing chord, body length); y+ in band =
wall area with y+ in [0.5, 2] times the target y+ (1); times in seconds (mesh = blockMesh to checkMesh,
total = the whole case with the y+ run).

## Case deviations from the app's defaults

No case changes a meshing, domain or flow default (box domain, 100,000 background cells, target surface
size 0.01 L, 3 relative layers, 20 m/s, k-omega SST). The indicative y+ run of every case uses:

- solvers.iterations = 400, fixed (stopping criteria removed);
- solvers.write_interval = 400;
- solvers.cores = 3, the recommended count for meshes of 188k to 200k cells (D-064; default 1).

## Observations

1. All three meshes pass checkMesh with 0 failed checks and no lost part; max non-orthogonality 40.2 /
   61.5 / 56.3 degrees (sphere / wing / Ahmed body), 0 faces above 65 degrees, max skewness 0.51 / 1.98 / 1.43.
2. Wing trailing edge (x/c >= 0.95): 0.0 % of the area has the 3 layers, mean 1.49 layers, 51.5 % of the
   wanted thickness, while 99.5 % of it has at least one layer. Wing tips: 5.3 % coverage, 1.42 layers, 41.5 %.
3. Ahmed body rear-face edges: 0.0 % coverage, 1.45 layers, 52.8 % thickness; slant edges: 29.4 %, 1.92
   layers, 66.2 %. The sphere has 100 % coverage (3.00 / 3 layers).
4. The wing's surface cells are 24.1 mm (2.4 % of the chord), against 8.4 mm on the sphere and the body:
   the target surface size is 0.01 L and the app's L is the wing's largest extent, the 3 m span. The
   2.5 mm trailing edge is about 1/10 of a surface cell.
5. Wing surface fidelity: max 2.66e-3 L against an RMS of 1.33e-4 L. The two largest distances (2.66 mm
   and 2.58 mm) are wall points at y = 1.5 m, z = 0 near the trailing and leading edges, on the seed line
   that the automatic seeding (D-052) adds through the wing's centre; the wing is seeded because its chord
   (1 m) is under 1.41 background cells (0.77 m each). By band: x/c < 0.05 RMS 0.50 mm, 0.05-0.95 RMS
   0.038 mm, x/c >= 0.95 RMS 0.108 mm.
6. y+ after 400 iterations: area-weighted mean 169 / 231 / 108, min 7.4 / 53.4 / 10, 0.0 % of the wall
   area in [0.5, 2] in every case. The default layer sizing is relative (layer thickness from the local
   cell size), so the target y+ of 1 does not size the first layer.
7. Cost: 188,140 to 199,947 cells, meshing 25.5 to 36.0 s (snappyHexMesh layers stage 2.8 / 8.2 / 4.5 s),
   peak memory of the largest child process 368 to 433 MiB while meshing and 983 MiB in the wing's
   solver stage.
