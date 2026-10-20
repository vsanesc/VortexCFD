# 5.3 evaluation: cfMesh against snappyHexMesh

## Part A: availability

Checked by sourcing /usr/lib/openfoam/openfoam2606/etc/bashrc as the app does
(`foam/cfmesh_case.cfmesh_executables`, tests/test_cfmesh_case.py):

- Present in the v2606 platform bin/ (package openfoam2606 2606.0~rc2-1, build `_481094f-20260618`):
  cartesianMesh, tetMesh, pMesh, cartesian2DMesh, generateBoundaryLayers, improveMeshQuality,
  improveSymmetryPlanes, surfaceFeatureEdges, surfaceToFMS, FMSToSurface, checkSurfaceMesh,
  mergeSurfacePatches, preparePar and the other cfMesh utilities, with libmeshLibrary.so. Missing:
  extrudeEdgesInto2DMesh, subsetFMS (not needed).
- Version: the binaries print only the OpenFOAM banner ("(cfmesh)" in `cartesianMesh -help`); the
  sources and tutorials are not in the packages. It is ESI's "cfmesh" module, the community
  integration of cfMesh v1.1 (GPL-3): its repository (develop.openfoam.com/Community/integration-cfmesh,
  read-only clone at commit 3ff8555, 2024-12-18, outside the repository) carries the "cfMesh v1.1"
  user guide.
- Parallel options: OpenMP (libmeshLibrary.so and cartesianMesh link libgomp; a tutorial case,
  asmoOctree, ran at 1354 % CPU with the default threads) and MPI (`-parallel`, linked against
  libPstream/openmpi; the case must first be split with preparePar). `OMP_NUM_THREADS=1` does not
  limit it (591 % CPU): parts of the library size their thread pools from `omp_get_num_procs()`,
  which follows the CPU affinity, so `taskset` is what caps the threads (101 % CPU with one CPU).
  On that small case the single-CPU run was faster (4.5 s) than the default (5.3 s).

## Part C: comparison

Run on 2026-10-20 at git `803e848` (results tagged "-dirty" only because benchmarks/README.md was being
edited; no code differed): benchmarks/results/20261020T065909Z, T070636Z (snappyHexMesh),
T070738Z, T070907Z (cfMesh) and benchmarks/results/local/20261020T070929Z (snappyHexMesh),
T071302Z (cfMesh), all `_803e848-dirty`. One full comparison, wall-clock 3,891 s (65 min), 50 min
of it the two cfMesh aircraft meshes. Current defaults as in baseline.json (y+ 50 absolute layers,
surface size from l_ref, curvature levels 2); the aircraft settings of D-094. snappyHexMesh runs on
one core; cartesianMesh on 10 (one CPU per physical core, D-102). Mesh only for every case; the
indicative y+ run (400 iterations, D-082) for the half wing and the Ahmed body, which the benchmark
runs only on a valid mesh (D-100): both cfMesh meshes have hard checkMesh failures, so their y+ runs
did not run.

Columns: "walk" = layers counted from the mesh for both meshers (bench/layer_walk, D-102); target
layer count in brackets; "% of plan" = stack thickness against the planned y+ stack (first layer x
(r^n - 1) / (r - 1)); first layer = mean height of the first layer cell where there is one, against
the y+ first layer; "snappy fields" = snappyHexMesh's own layer fields (D-082). Fidelity: public
cases against the CAD (D-082); aircraft against the trimmed reference, mesh -> reference and reference
-> mesh, RMS / max (D-094). Peak memory: the largest child process (D-082).

| Case | Mesher | Valid | Cells | Hard / soft failed checks | Max non-ortho | Faces >70 | Strict cov. % (walk) | Mean / target % | Zero-layer % | Stack thickness % of plan | First layer mm (plan) | snappy fields: cov. % / mean % | Fidelity RMS / max mm | Lost parts | Mesh s (cores) | Peak MB | y+ mean / % in band |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere | snappy | yes | 276,078 | 0 / 0 | 46.6 | 0 | 99.5 (10) | 100.2 | 0.0 | 101.1 | 0.90 (0.90) | 100.0 / 100.0 | 0.089 / 0.15 | 0 | 50 (1) | 493 | - / - |
| sphere_cfmesh | cfmesh | yes | 351,572 | 0 / 0 | 25.6 | 0 | 100.0 (10) | 100.0 | 0.0 | 33.1 | 0.30 (0.90) | - / - | 0.088 / 0.16 | 0 | 9 (10) | 360 | - / - |
| wing | snappy | yes | 337,824 | 0 / 0 | 64.8 | 0 | 76.8 (11) | 87.0 | 3.3 | 90.3 | 1.29 (0.90) | 78.4 / 89.0 | 0.107 / 0.78 | 0 | 55 (1) | 582 | 43.3 / 67.6 |
| ahmed | snappy | yes | 225,842 | 0 / 0 | 64.9 | 0 | 31.1 (10) | 64.0 | 9.3 | 77.4 | 1.87 (0.90) | 31.0 / 68.6 | 0.063 / 0.36 | 0 | 37 (1) | 412 | 67.8 / 57.7 |
| wing_cfmesh | cfmesh | no | 530,334 | 3 / 2 | 117.5 | 23 | 100.0 (11) | 100.0 | 0.0 | 32.6 | 0.29 (0.90) | - / - | 0.329 / 1.50 | 0 | 24 (10) | 1144 | - / - |
| ahmed_cfmesh | cfmesh | no | 378,488 | 3 / 2 | 172.7 | 4546 | 99.9 (10) | 100.0 | 0.0 | 31.0 | 0.28 (0.90) | - / - | 0.076 / 1.43 | 0 | 22 (10) | 369 | - / - |
| aircraft_untrimmed_cad_union | snappy | no | 281,113 | 3 / 2 | 174.4 | 18 | 0.0 (24) | 2.2 | 74.8 | 8.4 | 37.29 (0.64) | 0.0 / 5.0 | m->r 3.54 / 18.4; r->m 4.43 / 61.3 | 0 | 158 (1) | 1363 | - / - |
| aircraft_untrimmed_cad_union_cfmesh | cfmesh | no | 642,689 | 3 / 2 | 179.4 | 994260 | 9.3 (24) | 24.9 | 0.8 | 4.3 | 2.26 (0.64) | - / - | m->r 6.22 / 89.0; r->m 15.10 / 109.5 | 0 | 1259 (10) | 1355 | - / - |
| aircraft_untrimmed_as_is_cfmesh | cfmesh | no | 653,421 | 3 / 2 | 179.7 | 1030347 | 9.2 (24) | 24.8 | 1.1 | 4.6 | 2.33 (0.64) | - / - | m->r 6.05 / 83.8; r->m 8.60 / 76.5 | 0 | 1652 (10) | 965 | - / - |

Per zone (half wing: trailing edge x/c >= 0.95, tip, root on the symmetry plane; Ahmed: slant and
rear-face edge bands; aircraft: junction bands, trailing edge, tips, D-094):

| Case | Mesher | Zone | Strict cov. % (walk) | Mean / target % | Zero-layer % | Thickness % of plan | snappy fields cov. % / mean % |
|---|---|---|---|---|---|---|---|
| wing | snappy | root | 87.4 | 94.6 | 0.6 | 95.0 | 90.1 / 95.1 |
| wing | snappy | tips | 0.0 | 10.9 | 44.1 | 22.0 | 0.0 / 24.6 |
| wing | snappy | trailing_edge | 0.0 | 17.3 | 15.7 | 32.8 | 0.0 / 28.1 |
| ahmed | snappy | rear_edges | 0.0 | 3.9 | 61.3 | 8.0 | 0.0 / 14.5 |
| ahmed | snappy | slant_edges | 14.5 | 25.4 | 55.0 | 29.6 | 14.5 / 35.0 |
| wing_cfmesh | cfmesh | root | 100.0 | 100.0 | 0.0 | 13.4 | - / - |
| wing_cfmesh | cfmesh | tips | 100.0 | 100.0 | 0.0 | 13.9 | - / - |
| wing_cfmesh | cfmesh | trailing_edge | 100.0 | 100.2 | 0.0 | 12.9 | - / - |
| ahmed_cfmesh | cfmesh | rear_edges | 100.0 | 100.0 | 0.0 | 9.3 | - / - |
| ahmed_cfmesh | cfmesh | slant_edges | 100.0 | 100.0 | 0.0 | 16.0 | - / - |
| aircraft_untrimmed_cad_union | snappy | htail_junction | 0.0 | 1.0 | 85.8 | 1.4 | 0.0 / 1.5 |
| aircraft_untrimmed_cad_union | snappy | tips | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 / 2.0 |
| aircraft_untrimmed_cad_union | snappy | trailing_edge | 0.0 | 0.0 | 99.7 | 0.0 | 0.0 / 4.2 |
| aircraft_untrimmed_cad_union | snappy | vtail_junction | 0.0 | 1.4 | 79.9 | 2.1 | 0.0 / 3.1 |
| aircraft_untrimmed_cad_union | snappy | wing_junction | 0.0 | 0.1 | 97.2 | 0.3 | 0.0 / 2.4 |
| aircraft_untrimmed_cad_union_cfmesh | cfmesh | htail_junction | 3.5 | 20.5 | 2.3 | 1.6 | - / - |
| aircraft_untrimmed_cad_union_cfmesh | cfmesh | tips | 23.3 | 36.6 | 1.4 | 1.8 | - / - |
| aircraft_untrimmed_cad_union_cfmesh | cfmesh | trailing_edge | 2.0 | 17.9 | 2.2 | 0.7 | - / - |
| aircraft_untrimmed_cad_union_cfmesh | cfmesh | vtail_junction | 14.0 | 32.1 | 3.3 | 2.6 | - / - |
| aircraft_untrimmed_cad_union_cfmesh | cfmesh | wing_junction | 2.2 | 14.1 | 11.6 | 1.4 | - / - |
| aircraft_untrimmed_as_is_cfmesh | cfmesh | htail_junction | 5.6 | 24.4 | 2.5 | 2.0 | - / - |
| aircraft_untrimmed_as_is_cfmesh | cfmesh | tips | 16.0 | 30.5 | 1.4 | 1.7 | - / - |
| aircraft_untrimmed_as_is_cfmesh | cfmesh | trailing_edge | 2.1 | 17.7 | 2.3 | 0.8 | - / - |
| aircraft_untrimmed_as_is_cfmesh | cfmesh | vtail_junction | 13.5 | 30.8 | 2.4 | 2.6 | - / - |
| aircraft_untrimmed_as_is_cfmesh | cfmesh | wing_junction | 0.0 | 10.2 | 16.5 | 3.4 | - / - |

Aircraft details (reference -> mesh / mesh -> reference RMS in mm per zone; wall left inside a
component):

| Variant | wing / htail / vtail junction ref->mesh RMS mm | trailing edge / tips ref->mesh RMS mm | Wall inside a component | Patches with faces | Per-part force partition |
|---|---|---|---|---|---|
| snappyHexMesh, CAD union | 1.33 / 2.03 / 1.68 | 0.60 / 2.98 | 58 points, 0.030 m2 | 6/6 | ok |
| cfMesh, CAD union | 3.07 / 5.75 / 3.68 | 3.57 / 9.23 | 1,229 points, 0.125 m2 | 6/6 | ok |
| cfMesh, as is | 5.19 / 4.23 / 4.23 | 3.31 / 9.93 | 3,182 points, 0.171 m2 | 6/6 | ok |

Cell counts did not match within 15 % (cfMesh +27 % sphere, +57 % wing, +68 % Ahmed, +129 %
aircraft). Splitting each mesh into layer cells (wall faces x walked mean layers, approximate) and the
rest: cfMesh's layer cells are 174,240 / 253,116 / 193,964 against snappyHexMesh's 106,619 / 158,288 /
74,015 (sphere / wing / Ahmed): it extrudes the full stack on every wall face, and it has 1.4 to 1.7
times the wall faces (its boundary cells follow the requested size on every box the surface cuts). The
other cells differ by +5 % (sphere), +22 % (Ahmed), +54 % (wing) and +96 % (aircraft). Matching the
counts would have meant coarser cfMesh surfaces than the snappyHexMesh levels the mapping reproduces,
so the gap was left and explained. Without its layers the cfMesh Ahmed mesh has 170,040 cells and
passes checkMesh (development run, Part B).

Where the cfMesh meshes fail (`checkMesh -writeSets`, development runs of the same settings):
Ahmed body: all wrongly oriented, non-orthogonal and skew faces sit at the four front corners where
the 0.1 m rounded edges meet (x 0.02-0.10 m, y +-0.15-0.19 m, z near 0 or 0.288 m); the second
"refining boundary layers" pass leaves 785 bad faces that the untangler does not repair; without
maxFirstLayerThickness it fails the same way (11 negative cells). Half wing: the bad cells are at the
trailing edge's root on the symmetry plane (x 0.995-0.997 m), where cartesianMesh left a point 3.0 mm
off the plane (flattened, `symmetry_flattened`: 55 points, max 3.0 mm, RMS 0.03 mm), and at
(0.29, 0, -0.06) m on the root. Aircraft: the 24-layer split left 213,476 inverted faces that the
untangler still had after 20 minutes; checkMesh counts about one million faces above 70 degrees.

## Observations

1. Layer coverage where snappyHexMesh collapses: on the public cases cfMesh has the full stack on
   every face, the zones included: strict coverage 100.0 % at the half wing's trailing edge and tip
   and at the Ahmed body's slant and rear edges, against 0.0 / 0.0 / 14.5 / 0.0 % with snappyHexMesh
   (walk; snappyHexMesh's own fields agree: 0.0 / 0.0 / 14.5 / 0.0 %).
2. But the stack is about one boundary cell thick, not the y+ stack: 31-33 % of the planned thickness
   on the sphere, wing and Ahmed body, and the first layer is 0.28-0.30 mm against the 0.90 mm the y+
   50 estimate asks for (snappyHexMesh: 0.90 mm on the sphere). cfMesh splits the boundary cell
   geometrically and maxFirstLayerThickness only caps the first layer (refineBoundaryLayers.C), so
   y+ would come out near a third of the target: estimated about 16 for a target of 50, from the
   first-layer ratio; not measured, because no layered cfMesh mesh except the sphere was valid.
3. Validity: cfMesh's layered meshes fail checkMesh with hard failures on 4 of 5 geometries (half
   wing, Ahmed, both aircraft: negative volumes, face pyramids, non-orthogonality above 90 degrees;
   max non-orthogonality 117-180 degrees). snappyHexMesh passes on the three public cases and fails
   only on the aircraft's 24-layer stack (the known 5.2 / 5.4 issue, QUESTIONS 111). The app would
   block the solver on every failing mesh (D-100), so cfMesh's coverage does not reach a solution.
4. Where cfMesh works it is good: sphere valid, max non-orthogonality 25.6 against 46.6 degrees,
   9 s on 10 cores against 50 s on one core, peak 360 MB against 493 MB, the same surface fidelity
   (0.088 / 0.16 mm against 0.089 / 0.15 mm RMS / max).
5. Surface fidelity on sharp, thin geometry is worse with cfMesh: half wing RMS 0.329 mm, max 1.50 mm
   against 0.107 / 0.78 mm; on the aircraft (CAD union) reference -> mesh RMS 15.10 mm against 4.43,
   junctions 3.1-5.8 mm against 1.3-2.0 mm, and 0.125 m2 of wall left inside a component against
   0.030 m2. cfMesh has no counterpart for snappyHexMesh's curvature refinement (QUESTIONS 127).
6. The CAD union output helps cfMesh too, a little: against the as-is surface the wall inside a
   component drops from 0.171 to 0.125 m2 and the wing junction RMS from 5.19 to 3.07 mm; the as-is
   surface (interpenetrating parts) meshes without an error, since cfMesh keeps whatever the combined
   surface encloses, and is worse at the junctions.
7. Cost on the large case: the aircraft took 1,259 s (CAD union) and 1,652 s (as is) on 10 cores
   against 158 s on one core for snappyHexMesh, almost all of it untangling the inverted layer cells;
   642,689 / 653,421 cells against 281,113.
8. Robustness features carry over: no lost part in any case, every component patch has faces (6/6),
   the per-part force partition holds, and the patch names match the snappyHexMesh case. The symmetry
   plane needed a workaround (QUESTIONS 128).
9. The aircraft is a failure for both meshers at these settings; snappyHexMesh extrudes almost
   nothing there (walk: 2.2 % of the target layers on average, 74.8 % of the area with none; its
   fields: 5.0 % mean), cfMesh extrudes more (24.9 % mean, 0.8 % none, 9.3 % strict) but invalid.

## Recommendation

**(b) keep snappyHexMesh and move to 5.4.** cfMesh's one clear advantage, full layer coverage at sharp
edges, thin trailing edges and junctions (observation 1), comes with a stack only a third as thick as
the y+ estimate asks (2), hard checkMesh failures on four of its five meshes (3), worse surface fidelity
on the wing and the aircraft (5) and an order of magnitude more time on the aircraft (7). The app's
solver would be blocked on those meshes. Integrating it as an alternative mesher (a) would add a
second pipeline to maintain without a case that it meshes validly and snappyHexMesh does not. What 5.4
can take from it: extruding everywhere and then repairing is what fails (cfMesh's untangler leaves
inverted cells at doubly-curved corners and junctions); snappyHexMesh's remove-and-shrink keeps the
mesh valid but collapses the stacks, so the 5.4 work should target the collapse (QUESTIONS 87, 106,
111, 122, 124). The evaluation code stays as a benchmark-only switch (`--mesher cfmesh`) for a later
re-check.

Main risks if it were integrated anyway:
- Licence: GPL-3, compatible with the app's GPL-3 (D-007); no change.
- Maintenance: ESI ships the binaries but not the sources or tutorials; the community repository's
  last change is from 2024-12 (cfMesh v1.1); the version is not reported by the binaries; threads
  follow the CPU affinity, not OMP_NUM_THREADS.
- Features lost or needing work: curvature refinement (no working counterpart, QUESTIONS 127); the
  y+ stack thickness (cfMesh cannot grow beyond one boundary cell without a larger boundary cell or a
  separate extrusion); exactly planar symmetry planes (flattening workaround, QUESTIONS 128);
  snappyHexMesh's layer fields (the benchmark's layer metrics needed the mesh walk); bullet and C-type
  domains were not measured (the combined surface supports them; no benchmark case uses them).
- Kept: per-part patches and regions, the lost-part and domain guards, per-part forces, CAD union
  input; no seed lines are needed.

