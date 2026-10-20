# 5.4b y+ at the first cell centre, tet check and outer passes

Task 5.4b. Layer metrics are counted from the mesh (bench/layer_walk, D-105). Local aircraft results:
numbers only (D-094); raw results in the git-ignored benchmarks/results/5.4b/.

## Part A: where OpenFOAM v2606 evaluates y+ (D-107)

- `src/functionObjects/field/yPlus/yPlus.C` (`execute`): on a patch with a nut wall function it takes
  `nutWallFunctionFvPatchScalarField::yPlus()`; on any other wall it computes `d * sqrt(nuEff |snGrad U|) / nu`
  with `d = nearWallDist(mesh).y()`.
- `nutkWallFunctionFvPatchScalarField.C` (`yPlus()` and `calcNut()`): `yPlus = Cmu^0.25 y sqrt(k_P) / nu` with
  `y = turbModel.y()[patchi]`, and `turbulenceModel::y_` is a `nearWallDist` (turbulenceModel.H).
- `src/finiteVolume/fvMesh/wallDist/nearWallDist/nearWallDist.C` (`calculate()`, both branches): the
  distance is `smallestDist(cellCentres[faceCells[i]], ...)`, from the **centre** of the wall-adjacent cell
  to the nearest wall face. For a prism layer of height h that is h / 2.
- Our estimator (foam/yplus.first_layer_thickness, D-024) returned y = y+ nu / u* and the app used it as
  snappyHexMesh's `firstLayerThickness` (the cell height), as its docstring said: the reported y+ was
  about half the target, as in RESULT_5.4 (25.9-27.1 for 50).
- Change: `Mesh.yplus_at` "cell_centre" (default, schema v14) sizes the first layer 2 y; projects saved
  before keep "cell_height". Hand check (V 20 m/s, nu 1.5e-5, L 1 m, y+ 50): Re 1,333,333, Cf 0.0034672,
  u* 0.83273 m/s, y 0.90065 mm, first layer 1.8013 mm (tests/test_yplus_convention.py).

## Part B: tet check and outer passes (D-106 updated)

Frozen copy of src/ at `add53eb` plus the walk's first-cell measure (the committed bench change of this part);
every job `nice -n 15` on one core, at most 10 at a time, mesh only. The new y+ convention applies to every
variant (first layer 1.80 mm on the public cases, 1.27 mm on the aircraft at 30 m/s). Variants: base = D-106
(featureAngle 130, nOuterIter 3, cap 12, tet check off in `relaxed`); tet = `relaxed` minTetQuality 1e-15;
outer2 = nOuterIter 2; outer2tet = both. Cases: half wing, Ahmed body, sphere, aircraft (CAD union, surface
0.1 l_ref, as RESULT_5.4). Wall-clock 881 s.

Columns as RESULT_5.4, plus the walked first cell: the wall-adjacent cell height over every wall face
(layered or not; on a face without a prism, twice its centre distance), area-weighted mean, and the maximum
over faces with at least one layer. Zones: strict % / mean-over-target %.

| Variant | Case | Hard / soft | Cells | Layers @ ratio | Strict cov. % | Zones strict % / mean % | Mean / target % | Zero-layer % | Thickness % of plan | Max non-ortho | Fidelity RMS mm | Planned first mm | Walked first cell mm: mean / max extruded | Mesh s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | wing | 0 / 0 | 302,782 | 7 @ 1.200 | 98.1 | root 98/99, tip 91/94, TE 68/82 | 98.9 | 0.9 | 97.4 | 64.9 | 0.107 | 1.801 | 1.777 / 2.11 | 101 |
| tet | wing | 0 / 0 | 301,707 | 7 @ 1.200 | 96.0 | root 98/99, tip 56/73, TE 68/82 | 97.7 | 1.9 | 96.3 | 64.9 | 0.107 | 1.801 | 1.758 / 3.73 | 112 |
| outer2 | wing | 0 / 0 | 301,781 | 7 @ 1.200 | 96.8 | root 97/99, tip 90/94, TE 38/75 | 98.6 | 0.9 | 97.6 | 64.5 | 0.107 | 1.801 | 1.790 / 2.15 | 85 |
| outer2tet | wing | 0 / 0 | 300,025 | 7 @ 1.200 | 94.4 | root 97/99, tip 50/71, TE 38/75 | 97.3 | 1.8 | 96.3 | 64.9 | 0.107 | 1.801 | 1.788 / 6.14 | 96 |
| base | ahmed | 0 / 0 | 233,310 | 6 @ 1.200 | 99.7 | rear 100/100, slant 100/100 | 100.7 | 0.1 | 101.5 | 64.3 | 0.063 | 1.807 | 1.789 / 1.81 | 67 |
| tet | ahmed | 0 / 0 | 232,832 | 6 @ 1.200 | 98.8 | rear 95/95, slant 95/95 | 99.8 | 1.0 | 100.6 | 64.1 | 0.063 | 1.807 | 1.780 / 2.82 | 79 |
| outer2 | ahmed | 0 / 0 | 233,182 | 6 @ 1.200 | 99.4 | rear 100/100, slant 100/100 | 100.6 | 0.1 | 101.6 | 64.0 | 0.063 | 1.807 | 1.792 / 1.86 | 65 |
| outer2tet | ahmed | 0 / 0 | 231,606 | 6 @ 1.200 | 96.5 | rear 87/91, slant 56/71 | 98.7 | 1.5 | 99.8 | 64.3 | 0.063 | 1.807 | 1.803 / 3.12 | 70 |
| base | sphere | 0 / 0 | 233,534 | 6 @ 1.200 | 99.6 |  | 100.4 | 0.0 | 101.2 | 46.5 | 0.089 | 1.801 | 1.801 / 1.80 | 79 |
| tet | sphere | 0 / 0 | 233,534 | 6 @ 1.200 | 99.6 |  | 100.4 | 0.0 | 101.2 | 46.5 | 0.089 | 1.801 | 1.801 / 1.80 | 76 |
| outer2 | sphere | 0 / 0 | 233,534 | 6 @ 1.200 | 99.6 |  | 100.4 | 0.0 | 101.2 | 46.5 | 0.089 | 1.801 | 1.801 / 1.80 | 71 |
| outer2tet | sphere | 0 / 0 | 233,534 | 6 @ 1.200 | 99.6 |  | 100.4 | 0.0 | 101.2 | 46.5 | 0.089 | 1.801 | 1.801 / 1.80 | 72 |
| base | aircraft | 3 / 2 | 500,142 | 12 @ 1.300 | 0.1 | hj 0/16, tip 0/1, TE 0/0, vj 0/29, wj 0/2 | 53.6 | 13.7 | 23.2 | 176.7 | 3.54/4.55 | 1.272 | 4.491 / 28.32 | 641 |
| tet | aircraft | 2 / 1 | 445,812 | 12 @ 1.300 | 0.0 | hj 0/9, tip 0/1, TE 0/0, vj 0/22, wj 0/1 | 38.8 | 25.9 | 18.4 | 160.0 | 3.54/4.55 | 1.272 | 6.874 / 28.32 | 776 |
| outer2 | aircraft | 3 / 2 | 504,660 | 12 @ 1.300 | 40.5 | hj 0/11, tip 0/1, TE 0/0, vj 0/30, wj 0/1 | 66.6 | 14.9 | 23.9 | 169.1 | 3.54/4.55 | 1.272 | 3.289 / 54.49 | 282 |
| outer2tet | aircraft | 0 / 1 | 407,157 | 12 @ 1.300 | 2.4 | hj 0/8, tip 0/0, TE 0/0, vj 0/20, wj 0/1 | 30.1 | 32.4 | 15.4 | 71.2 | 3.54/4.55 | 1.272 | 8.879 / 54.49 | 579 |

Findings:

1. **Only outer2tet is valid on all four cases.** The aircraft has hard checkMesh failures with the D-106
   defaults (3: 14 negative-volume cells, 55 faces above 90 degrees, 127 wrong pyramids), with the tet check
   alone (2) and with nOuterIter 2 alone (3); with both it has none (one soft: skewness 4.33). The public cases
   are valid in every variant. With the thicker first layer of Part A the D-106 defaults are no longer valid on
   the aircraft: its validity is trajectory-sensitive (RESULT_5.4, Diagnosis 3), one run per variant.
2. **Coverage on the public cases holds in every variant** (half wing 94.4-98.1 %, Ahmed body 96.5-99.7 %,
   sphere 99.6 %). The tet check costs edge zones: wing tip 91 -> 56 % (base -> tet), Ahmed slant 100 -> 56 %
   (outer2 -> outer2tet); nOuterIter 2 costs the wing trailing edge 68 -> 38 %.
3. **The first cell follows the plan where stacks exist:** mean 1.76-1.80 mm against 1.80 mm planned on the
   public cases. On the aircraft the mean is 3.3-8.9 mm against 1.27 mm (2.6-7 times; the walk's maximum on
   extruded faces, 28-54 mm, is core cells thin enough to pass the walk's aspect limit next to the 84 mm surface
   cells, not prism layers).
4. **Time:** outer2tet meshes the aircraft in 579 s against 641 s (base); the public cases within the noise.

**Choice (criteria of the task):** (1) validity leaves outer2tet only; (2) it keeps the half wing (94.4 %) and the
Ahmed body (96.5 %) above 85 %; (3) the tet check is on; (4) nOuterIter 2; (5) not needed. D-106 now writes
nOuterIter 2 and `relaxed` minTetQuality 1e-15 for the robust controls. A robust project meshed before is
out of date (the mesh hash carries the controls' revision); legacy projects are unchanged.

## Part E: the aircraft at a realistic resolution (one-off, local)

The local aircraft (CAD union, 30 m/s, as RESULT_5.4) with the defaults chosen in Part B (D-106 as updated,
D-107), target surface size 0.05 x l_ref instead of the benchmark's 0.1 (l_ref 1.50 m, the wing's mean chord):
surface cells 42 mm (level 6; curvature up to level 8) instead of 84 mm. Frozen copy of src/ at `0f027bb`;
mesh on one core, then the indicative y+ run (400 iterations) on 10 cores. The committed benchmark definitions
are unchanged; raw result in the git-ignored benchmarks/results/5.4b/partE/. For comparison, the same case at
0.1 x l_ref with the same controls (Part B, outer2tet).

| Aircraft | 0.05 x l_ref | 0.1 x l_ref (Part B) |
|---|---|---|
| Hard / soft checkMesh failures | 0 / 0 | 0 / 1 |
| Cells (snapped, before layers) | 688,556 (459,304) | 407,157 |
| Layers planned / written | 17 at 1.2 -> 12 at 1.3 (70 % of the planned 135 mm) | 21 at 1.2 -> 12 at 1.3 (33 % of 286 mm) |
| Strict coverage % (snappyHexMesh fields) | 20.2 (21.5) | 2.4 |
| Zones strict % / mean % | wing junction 0 / 10, htail junction 0 / 5, vtail junction 0 / 8, trailing edge 0 / 10, tips 0 / 6 | wj 0 / 1, hj 0 / 8, vj 0 / 20, TE 0 / 0, tip 0 / 0 |
| Mean layers / target % | 43.9 | 30.1 |
| Zero-layer area % | 32.3 | 32.4 |
| Walked first cell, planned 1.27 mm: mean / 95th percentile | 5.38 mm / 20.0 mm (4.2 x the plan) | 8.88 mm / 29.2 mm |
| Max non-orthogonality | 81.1 (1 face above 70) | 71.2 |
| Fidelity RMS mm (mesh -> reference / reference -> mesh) | 3.36 / 3.12 | 3.54 / 4.55 |
| y+ mean / % in [25, 100] | 232.2 / 38.6 % (min 11.3, max 4,170) | not run |
| Mesh s / y+ run s | 798 (layers 483) / 619 on 10 cores | 579 / - |

**Answer: full stacks become reachable on part of the aircraft, not in the hard zones.** Halving the surface
cells makes the plan fit better (17 planned layers instead of 21; the 12-layer cap reaches 70 % of the planned
stack instead of 33 %) and lifts the full-stack area from 2.4 to 20.2 % and the mean layers from 30 to 44 % of
the target, with a valid mesh. A third of the wall still has no layer, every zone (junctions, trailing edge,
tips) stays at 0 % strict coverage, and the wall cell is 4.2 times the planned first layer on average, so the
indicative y+ mean is 232 for a target of 50 (4.6 times; the Part C warning would show "about 4.2 times"). By area,
32.3 % of the wall has no layer, 47.5 % has 1 to 11 layers (spread over every count, not one outer pass's 6)
and 20.2 % has all 12. Reaching the target in the zones needs more than resolution with these controls
(QUESTIONS 147).

Machine time: Part E 1,574 s wall-clock (16:21-16:47), with Part F's 619 s inside it (Part F's y+ runs used at
most 6 cores while Part E meshed on one; Part E's y+ run started after Part F ended).
