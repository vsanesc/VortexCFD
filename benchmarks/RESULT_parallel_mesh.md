# Serial vs parallel meshing (task 5.x-parallel-mesh, D-111)

Mesh only (no y+ runs), `nice -n 15 python -m vortexcfd.bench --no-solve --mesh-cores N`, one run per point,
run one after the other (never two at once) on the development machine (Ryzen 9 5900X, 12 physical cores,
31 GB). Public cases: sphere, half wing, Ahmed body (app defaults, robust y+ layers); local case: the owner's
aircraft, untrimmed export with the CAD union (benchmarks/local_cases.json, 0.1 x l_ref surface cells).
Git 780999e (Part A). Raw results in the git-ignored benchmarks/results/parallel_mesh/ and
benchmarks/results/local/parallel_mesh/.

Columns: mesh wall-clock is the whole MeshRun (blockMesh to checkMesh, including decomposePar and
reconstructParMesh); snappy s is snappyHexMesh's own total from the log; strict coverage is the layer walk's
(D-087, D-105) overall and per zone; first cell is the walked wall-adjacent cell (D-109; planned 1.80 mm on
the public cases); fidelity is mesh wall points to the reference (public: the exact shape; aircraft: the
reference CAD skin); memory is the sum of all the run's processes (sampled every 0.5 s) / the largest single
process (getrusage).

| Case | Cores | Mesh s | Speedup | snappy s | Cells | Hard | Soft | Max non-ortho | Strict cov. % | Zones strict % | First cell mean / p95 mm | Fidelity RMS / max mm | Peak memory MiB (all / largest) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere | 1 | 52 | 1.00 | 48 | 233,534 | 0 | 0 | 46.5 | 99.6 | - | 1.801 / 1.801 | 0.089 / 0.154 | 460 / 472 |
| sphere | 4 | 33 | 1.57 | 25 | 233,545 | 0 | 0 | 46.5 | 99.6 | - | 1.801 / 1.801 | 0.089 / 0.154 | 714 / 221 |
| sphere | 8 | 25 | 2.13 | 17 | 233,709 | 0 | 0 | 46.5 | 99.6 | - | 1.801 / 1.801 | 0.089 / 0.154 | 1027 / 193 |
| wing | 1 | 63 | 1.00 | 58 | 300,025 | 0 | 0 | 64.9 | 94.4 | root 97.1, tips 50.0, trailing_edge 38.4 | 1.788 / 1.801 | 0.107 / 0.777 | 580 / 592 |
| wing | 4 | 43 | 1.45 | 35 | 300,039 | 0 | 0 | 64.9 | 94.4 | root 97.1, tips 50.0, trailing_edge 38.3 | 1.788 / 1.801 | 0.107 / 0.777 | 829 / 373 |
| wing | 8 | 32 | 1.97 | 24 | 300,025 | 0 | 0 | 64.9 | 94.4 | root 97.0, tips 50.0, trailing_edge 38.2 | 1.788 / 1.801 | 0.107 / 0.777 | 1124 / 373 |
| ahmed | 1 | 46 | 1.00 | 43 | 231,606 | 0 | 0 | 64.3 | 96.5 | rear_edges 86.6, slant_edges 56.0 | 1.803 / 1.807 | 0.063 / 0.363 | 430 / 437 |
| ahmed | 4 | 29 | 1.58 | 22 | 231,613 | 0 | 0 | 64.3 | 96.5 | rear_edges 86.6, slant_edges 56.0 | 1.803 / 1.807 | 0.063 / 0.363 | 671 / 358 |
| ahmed | 8 | 25 | 1.85 | 18 | 231,599 | 0 | 0 | 64.2 | 96.5 | rear_edges 86.6, slant_edges 56.0 | 1.803 / 1.807 | 0.063 / 0.363 | 942 / 359 |
| aircraft_untrimmed_cad_union | 1 | 497 | 1.00 | 491 | 407,157 | 0 | 1 | 71.2 | 2.4 | htail_junction 0.0, tips 0.0, trailing_edge 0.0, vtail_junction 0.0, wing_junction 0.0 | 8.879 / 29.163 | 3.539 / 18.36 | 953 / 1328 |
| aircraft_untrimmed_cad_union | 4 | 189 | 2.63 | 178 | 403,413 | 0 | 1 | 71.2 | 2.5 | htail_junction 0.0, tips 0.0, trailing_edge 0.0, vtail_junction 0.0, wing_junction 0.0 | 8.563 / 29.123 | 3.538 / 18.36 | 1094 / 1362 |
| aircraft_untrimmed_cad_union | 8 | 120 | 4.13 | 110 | 403,536 | 0 | 1 | 69.7 | 2.7 | htail_junction 0.0, tips 0.0, trailing_edge 0.0, vtail_junction 0.0, wing_junction 0.0 | 8.893 / 29.378 | 3.540 / 18.36 | 1355 / 1337 |

Background cells: about 100,000 on every case (99,200-100,860; the aircraft 99,918).

## Observations

1. **Parallel meshing does not change validity or coverage beyond noise.** Every case is valid at 1, 4 and
   8 cores with the same hard (0) and soft (0; aircraft 1) failure counts. Cells differ by at most 0.1 % on
   the public cases and 0.9 % on the aircraft; strict coverage overall is identical on the public cases and
   the zones move by at most 0.2 points; the aircraft goes 2.4 / 2.5 / 2.7 % (its zones stay at 0 %). The
   walked first cell and the fidelity are unchanged (aircraft first cell 8.9 / 8.6 / 8.9 mm mean). The
   aircraft's max non-orthogonality is 71.2 / 71.2 / 69.7 degrees.
2. **The parallel mesh is not bit-identical.** snappyHexMesh's choices depend on the partition and its
   rebalancing, so cell counts move by tens (public) to thousands (aircraft) of cells. Single-core runs are
   deterministic (QUESTIONS 148); a parallel run of the same inputs on another core count is a different,
   equally valid sample.
3. **Speedups are modest on the small public meshes and good on the aircraft.** 4 cores: 1.45-1.58 public,
   2.63 aircraft; 8 cores: 1.85-2.13 public, 4.13 aircraft. The public cases take under a minute in serial,
   and about 7 s of each parallel run is serial work (blockMesh, decomposePar 1.5 s, reconstructParMesh
   3-4 s, checkMesh). The aircraft spends most of its time in the layer phase (132 -> 81 s from 4 to 8
   cores), which scales well.
4. **8 cores is faster than 4 on every case.** Unlike the solver (D-064: memory-bandwidth bound, efficiency
   0.28-0.37 at 8), meshing kept gaining from 4 to 8: -24 % to -36 % wall-clock. Above 8 was not measured.
5. **The background-cell estimate does not predict the speedup.** All four cases have about 100,000
   background cells, yet the aircraft's speedup at 8 is twice the public cases'. What drives it is the
   snappyHexMesh work (surface complexity, layer passes), which the app does not estimate before meshing.
6. **Memory grows with the ranks.** The summed resident memory rises from 430-580 MiB in serial to
   942-1124 MiB at 8 cores on the public cases and from 953 to 1355 MiB on the aircraft; each rank needs less
   than the serial process. Far below the 31 GB of this machine. The 0.5 s sampling misses short peaks (in
   serial the sum is below the largest single process, which getrusage records exactly).
7. **The benchmark's snappyHexMesh-field coverage is not available in parallel runs** (the layer fields stay
   in processor*/, removed after reconstruction); the headline walk is computed on the reconstructed mesh and
   is unaffected.

## Recommended cap rule for P2

Meshing cores, automatic = min(Solvers cores, physical cores, background cells / 12,500, 8), at least 1
(`foam/parallel.MESH_CELLS_PER_CORE = 12_500`, `MESH_EFFICIENT_CORES = 8`; applied in D-111). With the
default 100,000 background cells this recommends 8: every measured case was fastest at 8. The Solvers cores
still cap it (the New simulation dialog sets them to the solver's recommendation, at most 4, D-064), so a
default project meshes on up to 4 cores unless the user sets Mesh cores; whether the meshing cap should
ignore the Solvers cores is QUESTIONS 155. Machine-specific, like D-064's cap.
