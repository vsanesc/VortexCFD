# 5.4 prism-layer robustness

Task 5.4: make the prism layers robust (owner decisions D1 to D5 of the task). The headline layer metric
is the strict coverage counted from the mesh (bench/layer_walk, D-105): the wall area whose column of
thin prism cells has the full target count. Local aircraft results: numbers only (D-094).

## Starting point (Part A)

Current defaults (as baseline.json: y+ 50 absolute layers, expansion 1.2, surface size from l_ref,
curvature levels 2; the aircraft with the D-094 settings: 30 m/s, surface size 0.1 l_ref, CAD union),
mesh only, at git `d52b99e` plus the D-105 report change (tagged "-dirty"). The four cases ran
concurrently, each on one core under `nice -n 15`; wall-clock 262 s. Public cases:
benchmarks/baseline_5.4_start.json; aircraft: benchmarks/results/5.4/baseline_5.4_start_local.json
(git-ignored).

Columns: hard / soft = checkMesh failures by the D-100 classes; strict coverage, mean layers / target,
zero-layer area and thickness are counted from the mesh; thickness is the stack against the planned y+
stack (first layer x (r^n - 1) / (r - 1)); zones as strict % / mean-over-target %; fidelity RMS in mm
(aircraft: mesh -> reference / reference -> mesh).

| Case | Hard / soft | Cells | Strict cov. % | Mean / target % | Zero-layer % | Thickness % of plan | Zones (strict % / mean %) | Max non-ortho | Fidelity RMS mm | Mesh s | Target layers |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere | 0 / 0 | 276,078 | 99.5 | 100.2 | 0.0 | 101.1 | - | 46.6 | 0.089 | 59 | 10 |
| wing | 0 / 0 | 337,824 | 76.8 | 87.0 | 3.3 | 90.3 | root 87.4 / 95, tips 0.0 / 11, trailing edge 0.0 / 17 | 64.8 | 0.107 | 62 | 11 |
| ahmed | 0 / 0 | 225,842 | 31.1 | 64.0 | 9.3 | 77.4 | rear edges 0.0 / 4, slant edges 14.5 / 25 | 64.9 | 0.063 | 44 | 10 |
| aircraft (CAD union) | 3 / 2 | 281,113 | 0.0 | 2.2 | 74.8 | 8.4 | wing junction 0.0 / 0, htail junction 0.0 / 1, vtail junction 0.0 / 1, trailing edge 0.0 / 0, tips 0.0 / 0 | 174.4 | 3.54 / 4.43 | 168 | 24 |

The public cases repeat RESULT_5.3 exactly (cells, quality, both layer measures); snappyHexMesh's own
fields give 100.0 / 78.4 / 31.0 / 0.0 % strict coverage. The aircraft's hard failures are the same three
as in 5.2: 4 negative-volume cells, 15 faces above 90 degrees, 40 incorrectly oriented face pyramids; soft: aspect ratio (4 cells) and skewness 25.6 (2 faces).

## Diagnosis (Part B)

### 1. meshQualityControls against the v2606 defaults

Reference: /usr/lib/openfoam/openfoam2606/etc/caseDicts/meshQualityDict (the install's file) and the
checks in src/dynamicMesh/motionSmoother/motionSmootherAlgoCheck.C.

| Control | v2606 meshQualityDict | App main controls (`MESH_QUALITY`) | App `relaxed` (absolute y+ sizing, D-044 / D-045) |
|---|---|---|---|
| maxNonOrtho | 65 | 65 | - |
| maxBoundarySkewness / maxInternalSkewness | 20 / 4 | 20 / 4 | - |
| maxConcave | 80 | 80 | - |
| minVol | 1e-13 | 1e-13 | - |
| **minTetQuality** | **1e-15** | **1e-15** | **-1e30 (check disabled)** |
| minArea | -1 (off) | -1 | - |
| minTwist | 0.02 | 0.02 | - |
| minDeterminant | 0.001 | 0.001 | - |
| minFaceWeight / minVolRatio | 0.05 / 0.01 | 0.05 / 0.01 | - |
| minTriangleTwist / minEdgeLength | -1 / -1 (off) | -1 / -1 | - |
| nSmoothScale / errorReduction | not in the file (snappyHexMesh tutorial values) | 4 / 0.75 | - |

Findings:

- The main controls are the install's values exactly; snapping uses them. The only difference is the
  `relaxed` sub-dictionary, which sets **minTetQuality -1e30, i.e. the face-decomposition tet check is
  disabled**, and with `nRelaxedIter 0` (D-045) snappyHexMesh uses it from the first layer iteration:
  snappyLayerDriver.C (`iteration < nRelaxedIter ? motionDict : motionDict.subDict("relaxed")`) merges it
  over the main controls for both the shrinking of the mesh (the mesh mover's scaling checks) and the
  layer-mesh check. So **the whole layer phase runs without the tet-quality check**.
- minVol and minDeterminant stay active in the layer phase: the layer driver and the mesh mover call
  the `polyMesh` overload of `motionSmootherAlgo::checkMesh`, which tests face pyramids against minVol
  (1e-13 m3, far below the aircraft's smallest layer pyramids, about 5e-8 m3) and cell determinants
  against 0.001. (The other overload, the `polyMeshGeometry` one, passes minTetQuality as the pyramid
  threshold, so there a -1e30 tet setting would also disable the pyramid test; snappyHexMesh's layer
  phase does not call it.)
- minTetQuality -1e30 is therefore a real relaxation (it can let a cell whose decomposition tets are
  inverted pass), but it is not what leaves the aircraft's inverted cells (section 3): those faces fail
  checks that stay on (non-orthogonality, pyramids, concavity, twist), and snappyHexMesh keeps them for a
  different reason.

### 2. Layer controls in the v2606 sources

Read from src/mesh/snappyHexMesh/snappyHexMeshDriver/layerParameters/layerParameters.C,
snappyLayerDriver.C and externalDisplacementMeshMover/ (medialAxisMeshMover.C,
displacementMotionSolverMeshMover.C). "required" = read with `get` (no default).

| Keyword | Default in v2606 | App value | What it does |
|---|---|---|---|
| relativeSizes, minThickness, featureAngle, nGrow, maxFaceThicknessRatio, nBufferCellsNoExtrude, nLayerIter | required | see dictionary | |
| thicknessModel | inferred from the two of firstLayerThickness / finalLayerThickness / thickness / expansionRatio given (firstAndExpansion here) | not written | firstAndOverall, firstAndExpansion, finalAndOverall, finalAndExpansion, overallAndExpansion, firstAndRelativeFinal |
| nRelaxedIter | labelMax (never relaxed) | 0 (absolute sizing) | layer iterations before the `relaxed` controls replace the main ones |
| nOuterIter | 1 | not written | splits the layers into passes of ceil(n / nOuterIter) layers each (-1: the old single-pass algorithm) |
| meshShrinker | displacementMedialAxis | not written | or displacementMotionSolver (needs `solver`, its coeffs and fvSolution entries) |
| mergePatchFacesAngle | featureAngle | not written | |
| concaveAngle | 90 | not written | |
| additionalReporting | false | not written | |
| featureAngle (layer) | required | 60 | patch edges whose faces differ by more than this get no extrusion ("Set displacement to zero for points on N feature edges") |
| slipFeatureAngle | 0.5 featureAngle | 30 | where the shrink displacement slides along the wall |
| layerTerminationAngle | 0.5 featureAngle | not written | stops layer growth where the mesh wraps a sharp edge (isolated-region pass) |
| nSmoothSurfaceNormals, nSmoothNormals, nSmoothThickness, maxThicknessToMedialRatio, minMedialAxisAngle | required (medial axis) | 1, 3, 10, 0.3, 90 | |
| nRelaxIter (addLayersControls) | required | 3 | the shrink makes at most **2 x nRelaxIter** scaling attempts (the last nRelaxIter with errorReduction 0) |
| nMedialAxisIter | number of mesh points | not written | |
| nSmoothDisplacement | 0 | not written | |
| detectExtrusionIsland, disableWallEdges | false | not written | |

Nothing else is read for the layers in v2606; the study uses only these keywords.

### 3. Where the stacks collapse and where the hard failures come from

From log.snappyHexMesh of the Part A meshes (bench/metrics.layer_log_diagnostics), checkMesh
`-writeSets` and one-factor diagnostic runs of the study (section "Study"; the variant that isolates each
mechanism is named). Wall faces: Ahmed 11,560, half wing 16,531, aircraft 29,666.

**Ahmed body (valid; strict coverage 31.1 %, rear edges 0 %, slant edges 15 %).** snappyHexMesh marks
11,540 of the 11,560 faces as extruded, yet by the mesh count 9.3 % of the area has no layer and 37 %
has 1 to 7 layers: the stacks are not removed, they are squashed.
- *Feature-angle termination (dominant).* 668 points on edges sharper than the layer featureAngle 60
  (every 90-degree rear-face edge, the slant edges) get zero displacement ("Set displacement to zero for
  points on 668 feature edges"); the thickness smoothing (nSmoothThickness 10) then tapers the stack
  over the neighbouring faces, which is the 1-to-7-layer population around the edges. Raising the layer
  featureAngle to 130 (variant fa130) leaves 0 such points, every face gets 10 of 10 layers (strict 98.0 %,
  both edge zones 100 %), the shrink needs 1 scaling step instead of 4 and nothing is removed.
- *Shrink-phase displacement scaling (not limiting).* 441 faces above maxNonOrtho 65 (plus 56
  interpolation-weight, 44 pyramid, 9 twist, 5 determinant, 4 concavity) in 4 scaling steps; relaxing
  maxNonOrtho to 70 for the layer phase (rlx70) changes nothing on this body (31.1 %).
- *Quality removal and medial axis (absent).* 0 faces removed by the layer-mesh check; 0 medial-axis
  thickness reductions; maxThicknessToMedialRatio 0.5 or 1.0 and minMedialAxisAngle 60 or 130 give the
  same mesh.
- *The disabled tet check helps here:* with minTetQuality 1e-15 in `relaxed` (tetOn) 16 faces are
  removed over 3 iterations and the strict coverage drops to 23.5 %.

**Half wing (valid; 76.8 %, tip 0 %, trailing edge 0 %).** 371 feature-edge points (the tip's and the
trailing edge's edges) with no layer, 2 faces removed (face twist); no medial-axis reduction. featureAngle
130 / 180 brings the tip to 51 / 73 %; the trailing edge stays at 0 % (with featureAngle 180 its faces
are removed by the quality checks instead: 235 faces), and a layer-by-layer addition (nOuterIter 3) is
what reaches it (38 %).

**Aircraft, CAD union (invalid: 4 negative-volume cells, 15 faces above 90 degrees, 40 wrongly oriented
pyramids).** 24 planned layers at ratio 1.2 from a 0.64 mm first layer are a 251 mm stack on 84 mm
surface cells (21 mm at the curvature-refined leading edges and junctions): 3 to 12 cells deep.
- *Every mechanism acts:* 1,184 feature-edge points with no layer, 2,062 isolated points stopped, 5,538
  medial-axis thickness reductions, 3,550 faces removed by the layer-mesh check over 5 iterations, and a
  shrink with 30 scaling steps and up to 32,955 faces above 65 degrees. Only 5,386 of 29,666 faces keep
  an extrusion (18 %); by the mesh count 74.8 % of the area has no layer and the mean is 2.2 % of the
  target.
- *The hard failures come from the shrink, not from the layer cells.* All 4 negative-volume cells, the
  25 wrongly oriented faces and the 18 non-orthogonal faces of `checkMesh -writeSets` lie in one cluster
  on the wing's upper surface (x 5.77-5.81 m, y -2.75 to -2.85 m), 36-62 mm from the wall: core cells two
  21 mm cells off the wall, none of them touching it. In the last layer iteration the medial-axis mesh
  mover had 2 faces in error at its 4th scaling attempt and 43 after its 6th and last (the mover gives
  up after 2 x nRelaxIter = 6 attempts and keeps the mesh: "Finished moving mesh" without "Successfully
  moved mesh"); the layer-mesh check then found 43 illegal faces, but none of them on an extruded face, so
  "Removed extrusion at 0 faces" and the iterations ended with them in the mesh.
- *The disabled tet check lets it get there:* the faces left in error fail checks that stay on, but
  with the tet check back on in `relaxed` (tetOn, and relIter20, which never reaches the relaxed set) the
  same 24-layer mesh has 0 hard failures. So do several other single changes that alter the trajectory
  of the shrink: featureAngle 90 / 130 / 180, minMedialAxisAngle 60 or 130, nSmoothSurfaceNormals 5,
  and any layer cap of 12 to 15 layers with ratio 1.3. The failure is fragile, not systematic; coverage,
  on the other hand, stays near zero in every one-factor variant at 24 layers (mean layers 1.3 to 3.2 %
  of the target) and only the layer cap moves it (12 layers: mean 32.7 %, zero-layer area 20.6 %).

## Study (Part C)

Cases: half wing, Ahmed body, aircraft (CAD union) and the sphere (regression guard, for the combined
candidates). Each variant changes the current defaults (the pre-5.4 controls, `layer_controls
"legacy"`) only as named; mesh only; every job on one physical core under `nice -n 15`, at most 10 at a
time. Driver: the benchmark runner with the generated snappyHexMeshDict content changed in memory before
it is written (a session script, not part of the app; raw results in the git-ignored
benchmarks/results/5.4/study/<variant>/<case>.json). Columns as in Part A, plus: core cells = cells
minus the prism cells snappyHexMesh reports as added (the last "Added N out of M cells" of each outer
iteration); layers @ ratio = the count and the expansion ratio written; thickness % of plan = the
mesh-counted stack against the planned total (with a cap: the uncapped plan at 1.2). Zones: wing TE
(trailing edge), tip, root; Ahmed rear and slant edges; aircraft wj / hj / vj (wing / horizontal / vertical
tail junction), TE, tip. A variant with a hard failure is rejected whatever its coverage (D1).

Variants (one factor at a time from the defaults): capN = layer cap N with the ratio raised up to 1.3
(aircraft only: the public cases plan 10 and 11 layers, under every cap); faN = layer featureAngle N
(60); slipN = slipFeatureAngle N (30); tetOn = `relaxed` with minTetQuality 1e-15 (the tet check on);
relIter20 = nRelaxedIter 20 (0); rlx70 = `relaxed` maxNonOrtho 70 (tet check off); rlx70tet = the same with
the tet check on; rlx75tw = tet on, maxNonOrtho 75, minTwist -1; medialR = maxThicknessToMedialRatio R
(0.3); mmaN = minMedialAxisAngle N (90); sSurfN5 / sNorm10 / sThick30 = nSmoothSurfaceNormals 5 (1),
nSmoothNormals 10 (3), nSmoothThickness 30 (10); layIter100 = nLayerIter 100 (50); outerN = nOuterIter N
(1); grow1 = nGrow 1 (0); buffer1 = nBufferCellsNoExtrude 1 (0); relax10 = nRelaxIter 10 (3);
motionSolver = meshShrinker displacementMotionSolver (displacementLaplacian, quadratic inverse-distance
diffusivity from the walls); twoPass = castellate and snap, then a layer-only snappyHexMesh pass.
Combined: C1 = featureAngle 130 + nOuterIter 3; C2 = featureAngle 180 + nOuterIter 3; C3 = featureAngle 180
+ nOuterIter 2; C4 = C1 + nSmoothThickness 30 + nSmoothSurfaceNormals 5; `_capN` = the aircraft at cap N;
fa130_cap12 = featureAngle 130 alone at cap 12 on the aircraft.

| Variant | Case | Hard / soft | Cells | Core cells | Layers @ ratio | Strict cov. % | Zones strict % / mean % | Mean / target % | Zero-layer % | Thickness % of plan | Max non-ortho | Fidelity RMS mm | Mesh s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/17 | 87.0 | 3.3 | 90.3 | 64.8 | 0.107 | 67 |
| base | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 64.9 | 0.063 | 54 |
| base | aircraft | 3 / 2 | 281113 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 2.2 | 74.8 | 8.4 | 174.4 | 3.54/4.43 | 225 |
| base | sphere | 0 / 0 | 276078 | 169718 | 10 @ 1.200 | 99.5 |  | 100.2 | 0.0 | 101.1 | 46.6 | 0.089 | 68 |
| cap12 | aircraft | 0 / 1 | 427628 | 269649 | 12 @ 1.300 | 2.7 | hj 0/8, tip 0/1, TE 0/0, vj 0/8, wj 0/2 | 32.7 | 20.6 | 13.4 | 64.9 | 3.54/4.43 | 237 |
| cap13 | aircraft | 0 / 1 | 427524 | 269649 | 13 @ 1.300 | 0.7 | hj 0/6, tip 0/1, TE 0/0, vj 0/6, wj 0/1 | 29.9 | 20.1 | 16.6 | 65.0 | 3.54/4.43 | 236 |
| cap14 | aircraft | 0 / 1 | 399342 | 269649 | 14 @ 1.300 | 0.3 | hj 0/5, tip 0/0, TE 0/0, vj 0/5, wj 0/1 | 24.3 | 24.2 | 18.9 | 67.8 | 3.54/4.43 | 236 |
| cap15 | aircraft | 0 / 1 | 349943 | 269649 | 15 @ 1.300 | 0.1 | hj 0/4, tip 0/0, TE 0/0, vj 0/3, wj 0/0 | 18.8 | 30.8 | 20.8 | 65.0 | 3.54/4.43 | 245 |
| fa90 | wing | 0 / 0 | 348155 | 189315 | 11 @ 1.200 | 83.9 | root 87/95, tip 51/65, TE 0/17 | 91.8 | 1.5 | 93.4 | 64.3 | 0.107 | 70 |
| fa90 | ahmed | 3 / 2 | 276694 | 164046 | 10 @ 1.200 | 92.4 | rear 100/100, slant 62/78 | 98.1 | 0.3 | 99.8 | 167.1 | 0.063 | 55 |
| fa90 | aircraft | 0 / 0 | 281800 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 2.2 | 74.8 | 8.3 | 64.9 | 3.54/4.55 | 219 |
| fa130 | wing | 0 / 0 | 347948 | 189315 | 11 @ 1.200 | 83.8 | root 87/95, tip 51/65, TE 0/17 | 91.8 | 1.6 | 93.3 | 64.8 | 0.107 | 76 |
| fa130 | ahmed | 0 / 0 | 279646 | 164046 | 10 @ 1.200 | 98.0 | rear 100/100, slant 100/100 | 100.3 | 0.0 | 100.9 | 63.8 | 0.063 | 54 |
| fa130 | aircraft | 0 / 0 | 281645 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 2.3 | 74.5 | 8.6 | 64.6 | 3.54/4.55 | 219 |
| fa180 | wing | 0 / 0 | 348468 | 189315 | 11 @ 1.200 | 85.2 | root 86/94, tip 73/83, TE 0/7 | 92.2 | 2.1 | 93.2 | 64.8 | 0.107 | 73 |
| fa180 | ahmed | 0 / 0 | 279646 | 164046 | 10 @ 1.200 | 98.0 | rear 100/100, slant 100/100 | 100.3 | 0.0 | 100.9 | 63.8 | 0.063 | 55 |
| fa180 | aircraft | 0 / 1 | 279773 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/1, TE 0/0, vj 0/1, wj 0/0 | 1.7 | 79.2 | 6.4 | 64.7 | 3.54/4.55 | 219 |
| slip10 | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/17 | 87.0 | 3.3 | 90.3 | 64.8 | 0.107 | 73 |
| slip10 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 64.9 | 0.063 | 52 |
| slip10 | aircraft | 3 / 2 | 281113 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 2.2 | 74.8 | 8.4 | 174.4 | 3.54/4.43 | 216 |
| slip45 | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/17 | 87.0 | 3.3 | 90.3 | 64.8 | 0.107 | 72 |
| slip45 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 64.9 | 0.063 | 51 |
| slip45 | aircraft | 3 / 2 | 281113 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 2.2 | 74.8 | 8.4 | 174.4 | 3.54/4.43 | 218 |
| tetOn | wing | 0 / 0 | 336987 | 189315 | 11 @ 1.200 | 76.2 | root 87/95, tip 0/9, TE 0/17 | 86.5 | 3.5 | 90.0 | 65.0 | 0.107 | 74 |
| tetOn | ahmed | 0 / 0 | 218958 | 164046 | 10 @ 1.200 | 23.5 | rear 0/4, slant 0/10 | 55.4 | 12.7 | 71.8 | 64.8 | 0.063 | 60 |
| tetOn | aircraft | 0 / 1 | 279240 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 1.7 | 78.5 | 6.6 | 65.0 | 3.54/4.43 | 212 |
| relIter20 | wing | 0 / 0 | 336987 | 189315 | 11 @ 1.200 | 76.2 | root 87/95, tip 0/9, TE 0/17 | 86.5 | 3.5 | 90.0 | 65.0 | 0.107 | 72 |
| relIter20 | ahmed | 0 / 0 | 218958 | 164046 | 10 @ 1.200 | 23.5 | rear 0/4, slant 0/10 | 55.4 | 12.7 | 71.8 | 64.8 | 0.063 | 61 |
| relIter20 | aircraft | 0 / 1 | 279240 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 1.7 | 78.5 | 6.6 | 65.0 | 3.54/4.43 | 210 |
| rlx70 | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/17 | 87.0 | 3.3 | 90.3 | 69.4 | 0.107 | 72 |
| rlx70 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 69.8 | 0.063 | 56 |
| rlx70 | aircraft | 0 / 0 | 283752 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/2, wj 0/0 | 2.5 | 72.0 | 9.5 | 75.3 | 3.54/4.43 | 211 |
| rlx70tet | wing | 0 / 0 | 336982 | 189315 | 11 @ 1.200 | 76.2 | root 87/95, tip 0/9, TE 0/17 | 86.5 | 3.5 | 90.0 | 69.8 | 0.107 | 74 |
| rlx70tet | ahmed | 0 / 0 | 218938 | 164046 | 10 @ 1.200 | 23.5 | rear 0/4, slant 0/10 | 55.4 | 12.8 | 71.8 | 69.8 | 0.063 | 63 |
| rlx70tet | aircraft | 0 / 1 | 279802 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 1.8 | 78.3 | 7.1 | 69.8 | 3.54/4.43 | 225 |
| rlx75tw | wing | 0 / 0 | 337017 | 189315 | 11 @ 1.200 | 76.2 | root 87/95, tip 0/9, TE 0/17 | 86.5 | 3.5 | 90.0 | 74.2 | 0.107 | 70 |
| rlx75tw | ahmed | 0 / 0 | 218938 | 164046 | 10 @ 1.200 | 23.5 | rear 0/4, slant 0/10 | 55.4 | 12.8 | 71.8 | 74.8 | 0.063 | 65 |
| rlx75tw | aircraft | 2 / 1 | 280575 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 1.8 | 78.4 | 6.8 | 159.3 | 3.54/4.43 | 224 |
| medial05 | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/17 | 87.0 | 3.3 | 90.3 | 64.8 | 0.107 | 70 |
| medial05 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 64.9 | 0.063 | 57 |
| medial05 | aircraft | 3 / 2 | 280518 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 2.1 | 76.1 | 8.0 | 174.4 | 3.58/4.43 | 207 |
| medial1 | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/17 | 87.0 | 3.3 | 90.3 | 64.8 | 0.107 | 70 |
| medial1 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 64.9 | 0.063 | 56 |
| medial1 | aircraft | 3 / 2 | 279968 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 2.0 | 76.6 | 7.9 | 174.4 | 3.58/4.43 | 203 |
| mma60 | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/25 | 87.5 | 3.2 | 90.3 | 64.9 | 0.107 | 71 |
| mma60 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 65.0 | 0.063 | 55 |
| mma60 | aircraft | 0 / 1 | 284144 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/2, wj 0/0 | 3.2 | 67.8 | 11.2 | 64.9 | 3.54/4.43 | 209 |
| mma130 | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/17 | 87.0 | 3.2 | 90.4 | 64.6 | 0.107 | 72 |
| mma130 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 64.9 | 0.063 | 54 |
| mma130 | aircraft | 0 / 1 | 277701 | 269649 | 24 @ 1.200 | 0.0 | hj 0/0, tip 0/0, TE 0/0, vj 0/0, wj 0/0 | 1.3 | 82.9 | 5.0 | 65.0 | 3.54/4.43 | 210 |
| sSurfN5 | wing | 0 / 0 | 338107 | 189315 | 11 @ 1.200 | 77.1 | root 88/95, tip 0/12, TE 0/17 | 87.3 | 2.9 | 90.5 | 64.8 | 0.107 | 70 |
| sSurfN5 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.0 | rear 0/4, slant 15/26 | 64.4 | 7.5 | 78.2 | 64.7 | 0.063 | 54 |
| sSurfN5 | aircraft | 0 / 1 | 280853 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 2.4 | 73.6 | 8.8 | 65.0 | 3.54/4.43 | 208 |
| sNorm10 | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/17 | 87.0 | 3.2 | 90.3 | 64.9 | 0.107 | 72 |
| sNorm10 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 64.4 | 0.063 | 52 |
| sNorm10 | aircraft | 0 / 1 | 281696 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/2, wj 0/0 | 2.5 | 72.9 | 9.3 | 65.0 | 3.55/4.43 | 218 |
| sThick30 | wing | 0 / 0 | 336830 | 189315 | 11 @ 1.200 | 76.2 | root 87/95, tip 0/17, TE 0/19 | 87.2 | 2.2 | 90.0 | 64.5 | 0.107 | 78 |
| sThick30 | ahmed | 0 / 0 | 226278 | 164046 | 10 @ 1.200 | 31.9 | rear 0/5, slant 15/28 | 65.7 | 6.5 | 77.4 | 63.2 | 0.063 | 54 |
| sThick30 | aircraft | 0 / 1 | 286387 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 4.3 | 57.9 | 14.2 | 64.9 | 3.54/4.43 | 226 |
| layIter100 | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/17 | 87.0 | 3.3 | 90.3 | 64.8 | 0.107 | 71 |
| layIter100 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 64.9 | 0.063 | 53 |
| layIter100 | aircraft | 3 / 2 | 281113 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 2.2 | 74.8 | 8.4 | 174.4 | 3.54/4.43 | 216 |
| outer2 | wing | 0 / 0 | 353709 | 189315 | 11 @ 1.200 | 88.5 | root 93/98, tip 2/39, TE 0/46 | 93.9 | 2.1 | 93.3 | 65.0 | 0.107 | 79 |
| outer2 | ahmed | 0 / 0 | 253346 | 164046 | 10 @ 1.200 | 73.2 | rear 0/14, slant 27/38 | 84.8 | 6.3 | 86.5 | 65.0 | 0.063 | 57 |
| outer3 | wing | 0 / 0 | 360099 | 189315 | 11 @ 1.200 | 93.1 | root 96/99, tip 32/58, TE 38/73 | 96.3 | 2.1 | 94.9 | 65.3 | 0.107 | 88 |
| outer3 | ahmed | 0 / 0 | 262352 | 164046 | 10 @ 1.200 | 79.3 | rear 0/23, slant 28/46 | 89.0 | 6.5 | 88.8 | 65.0 | 0.063 | 62 |
| outer3 | aircraft | 2 / 1 | 313832 | 269649 | 24 @ 1.200 | 0.0 | hj 0/2, tip 0/0, TE 0/0, vj 0/4, wj 0/0 | 11.3 | 53.8 | 21.5 | 97.3 | 3.54/4.43 | 504 |
| grow1 | wing | 0 / 0 | 332508 | 189315 | 11 @ 1.200 | 74.9 | root 86/94, tip 0/6, TE 0/7 | 85.2 | 5.4 | 88.4 | 64.9 | 0.107 | 70 |
| grow1 | ahmed | 0 / 0 | 217786 | 164046 | 10 @ 1.200 | 24.7 | rear 0/0, slant 12/22 | 58.5 | 13.1 | 74.4 | 64.9 | 0.063 | 51 |
| grow1 | aircraft | 0 / 1 | 271307 | 269649 | 24 @ 1.200 | 0.0 | hj 0/0, tip 0/0, TE 0/0, vj 0/0, wj 0/0 | 0.3 | 94.1 | 1.2 | 64.6 | 3.56/4.43 | 208 |
| buffer1 | wing | 0 / 0 | 313858 | 189315 | 11 @ 1.200 | 58.4 | root 79/89, tip 0/1, TE 0/0 | 75.0 | 11.2 | 82.8 | 64.8 | 0.107 | 73 |
| buffer1 | ahmed | 0 / 0 | 199812 | 164046 | 10 @ 1.200 | 0.0 | rear 0/0, slant 0/13 | 32.9 | 32.0 | 65.3 | 64.9 | 0.063 | 52 |
| buffer1 | aircraft | 0 / 1 | 277103 | 269649 | 24 @ 1.200 | 0.0 | hj 0/0, tip 0/0, TE 0/0, vj 0/0, wj 0/0 | 0.2 | 96.3 | 0.7 | 65.0 | 3.55/4.43 | 207 |
| relax10 | wing | 0 / 0 | 338018 | 189315 | 11 @ 1.200 | 77.2 | root 87/95, tip 0/11, TE 0/17 | 87.3 | 3.2 | 90.4 | 64.8 | 0.107 | 75 |
| relax10 | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.2 | 77.4 | 64.9 | 0.063 | 51 |
| relax10 | aircraft | 0 / 0 | 285548 | 269649 | 24 @ 1.200 | 0.0 | hj 0/3, tip 0/0, TE 0/0, vj 0/2, wj 0/0 | 2.6 | 75.4 | 8.6 | 65.0 | 3.54/4.43 | 231 |
| motionSolver | wing | 0 / 1 | 325547 | 189315 | 11 @ 1.200 | 60.4 | root 11/42, tip 0/10, TE 0/17 | 78.3 | 5.0 | 85.4 | 64.2 | 0.107 | 64 |
| motionSolver | ahmed | 0 / 0 | 228186 | 164046 | 10 @ 1.200 | 34.0 | rear 0/3, slant 15/25 | 65.4 | 10.6 | 77.8 | 63.7 | 0.063 | 36 |
| motionSolver | aircraft | FAIL - / - | - | - | 24 @ 1.200 | - |  | - | - | - | - | - | 174 |
| twoPass | wing | 0 / 0 | 337824 | 189315 | 11 @ 1.200 | 76.8 | root 87/95, tip 0/11, TE 0/17 | 87.0 | 3.3 | 90.3 | 64.8 | 0.107 | 78 |
| twoPass | ahmed | 0 / 0 | 225842 | 164046 | 10 @ 1.200 | 31.1 | rear 0/4, slant 15/25 | 64.0 | 9.3 | 77.4 | 64.9 | 0.063 | 50 |
| twoPass | aircraft | 3 / 2 | 281113 | 269649 | 24 @ 1.200 | 0.0 | hj 0/1, tip 0/0, TE 0/0, vj 0/1, wj 0/0 | 2.2 | 74.8 | 8.4 | 174.4 | 3.54/4.43 | 218 |
| fa130_cap12 | aircraft | 0 / 1 | 428998 | 269649 | 12 @ 1.300 | 2.6 | hj 0/10, tip 0/1, TE 0/0, vj 0/24, wj 0/1 | 31.9 | 21.2 | 13.2 | 65.0 | 3.54/4.55 | 184 |
| C1 | wing | 0 / 0 | 364942 | 189315 | 11 @ 1.200 | 95.9 | root 96/99, tip 75/87, TE 38/73 | 98.1 | 1.2 | 96.9 | 64.8 | 0.107 | 89 |
| C1 | ahmed | 0 / 0 | 279054 | 164046 | 10 @ 1.200 | 97.4 | rear 100/100, slant 100/100 | 100.0 | 0.1 | 100.5 | 64.8 | 0.063 | 46 |
| C1 | sphere | 0 / 0 | 276078 | 169718 | 10 @ 1.200 | 99.5 |  | 100.2 | 0.0 | 100.9 | 46.7 | 0.089 | 66 |
| C1_cap12 | aircraft | 0 / 1 | 444586 | 269649 | 12 @ 1.300 | 0.0 | hj 0/21, tip 0/2, TE 0/0, vj 0/43, wj 0/3 | 31.8 | 28.8 | 10.2 | 80.3 | 3.54/4.55 | 927 |
| C1_cap15 | aircraft | 2 / 1 | 488484 | 269649 | 15 @ 1.300 | 0.0 | hj 0/9, tip 0/1, TE 0/0, vj 0/23, wj 0/1 | 47.5 | 15.3 | 29.1 | 97.2 | 3.54/4.55 | 755 |
| C2 | wing | 0 / 0 | 365839 | 189315 | 11 @ 1.200 | 95.9 | root 95/98, tip 89/96, TE 20/63 | 98.2 | 0.9 | 97.2 | 64.7 | 0.107 | 92 |
| C2 | ahmed | 0 / 0 | 279054 | 164046 | 10 @ 1.200 | 97.4 | rear 100/100, slant 100/100 | 100.0 | 0.1 | 100.5 | 64.8 | 0.063 | 46 |
| C2 | sphere | 0 / 0 | 276078 | 169718 | 10 @ 1.200 | 99.5 |  | 100.2 | 0.0 | 100.9 | 46.7 | 0.089 | 64 |
| C2_cap12 | aircraft | 0 / 1 | 453518 | 269649 | 12 @ 1.300 | 0.0 | hj 0/23, tip 0/4, TE 0/0, vj 0/35, wj 0/19 | 37.2 | 21.0 | 11.6 | 79.5 | 3.54/4.55 | 864 |
| C2_cap15 | aircraft | 3 / 2 | 487307 | 269649 | 15 @ 1.300 | 0.0 | hj 0/10, tip 0/5, TE 0/0, vj 0/20, wj 0/22 | 46.9 | 16.3 | 28.8 | 179.5 | 3.58/4.56 | 801 |
| C3 | wing | 0 / 0 | 365774 | 189315 | 11 @ 1.200 | 94.3 | root 93/98, tip 85/94, TE 0/62 | 98.0 | 0.9 | 97.7 | 64.6 | 0.107 | 84 |
| C3 | ahmed | 0 / 0 | 278518 | 164046 | 10 @ 1.200 | 96.6 | rear 100/100, slant 100/100 | 99.7 | 0.1 | 100.3 | 64.9 | 0.063 | 40 |
| C3 | sphere | 0 / 0 | 276078 | 169718 | 10 @ 1.200 | 99.5 |  | 100.2 | 0.0 | 101.0 | 46.6 | 0.089 | 57 |
| C3_cap12 | aircraft | 3 / 2 | 458857 | 269649 | 12 @ 1.300 | 2.5 | hj 0/15, tip 0/4, TE 0/0, vj 4/38, wj 0/22 | 38.8 | 15.4 | 12.9 | 177.0 | 3.54/4.55 | 612 |
| C3_cap15 | aircraft | 0 / 1 | 423329 | 269649 | 15 @ 1.300 | 1.4 | hj 0/6, tip 0/3, TE 0/0, vj 0/16, wj 0/8 | 32.2 | 24.2 | 22.4 | 68.2 | 3.54/4.55 | 674 |
| C4 | wing | 0 / 0 | 358628 | 189315 | 11 @ 1.200 | 92.0 | root 96/99, tip 33/59, TE 32/67 | 95.9 | 2.5 | 93.4 | 76.0 | 0.107 | 251 |
| C4 | ahmed | 0 / 0 | 278266 | 164046 | 10 @ 1.200 | 95.8 | rear 100/101, slant 100/100 | 99.3 | 0.6 | 99.4 | 64.9 | 0.063 | 46 |
| C4 | sphere | 0 / 0 | 276078 | 169718 | 10 @ 1.200 | 99.5 |  | 100.2 | 0.0 | 100.9 | 46.7 | 0.089 | 55 |
| C4_cap12 | aircraft | FAIL - / - | - | - | 12 @ 1.300 | - |  | - | - | - | - | - | - |
| C4_cap15 | aircraft | 3 / 2 | 490962 | 269649 | 15 @ 1.300 | 0.1 | hj 0/12, tip 0/0, TE 0/0, vj 0/26, wj 0/1 | 43.9 | 15.9 | 26.4 | 176.1 | 3.54/4.55 | 919 |

Notes on the runs:

- Not in the table: C5 (featureAngle 130 + nOuterIter 5) on the aircraft was stopped after 13 minutes
  (each outer pass ran its 50 layer iterations; too slow for a default) and its public cases were not run;
  C1tet (C1 with the tet check on) was not run for lack of machine time. The aircraft row of outer2 is not
  in the table: it ran with source edited during the run (see below).
- Ten aircraft jobs of the first screen started after the app's source had been edited for Part D (the
  layer cap already active, so they ran at 17 layers @ 1.3 instead of 24 @ 1.2); they were moved to
  benchmarks/results/5.4/study/_contaminated/ and rerun from a frozen copy of the source with the
  pre-5.4 controls pinned. Every row above has the uncapped plan (24 @ 1.2) unless it names a cap.
- motionSolver: the aircraft run failed to start the motion solver (the app's placeholder fvSchemes is
  written as lists, `laplacianSchemes { default (Gauss linear corrected); }`, which snappyHexMesh never
  reads but the displacement solver does); fixed in the driver for the wing and the Ahmed body, where it
  is worse (60.4 / 34.0 %) and not rerun on the aircraft.
- C4_cap12: the mesh is valid (soft skewness, max non-orthogonality 76.3) but the mesh walk failed on it
  (IndexError in bench/layer_walk); the runner now records such an error instead of losing the case.

### Findings

1. **Feature-angle termination is the main lever at sharp edges (D4).** featureAngle 130 (or 180) lets
   the stacks wrap the Ahmed body's 90-degree rear-face and slant edges: strict coverage 31.1 -> 98.0 %,
   both edge zones 0 / 15 -> 100 %, zero-layer area 9.3 -> 0.0 %, no hard failure; the wing tip 0 -> 51 %
   (73 % at 180). At 90 the Ahmed mesh gets 3 hard failures (rejected; not analysed further: the
   limit sits at the body's own 90-degree edge angle).
2. **Layer-by-layer addition is the lever at the thin trailing edge.** nOuterIter 3 brings the wing to
   93.1 % (trailing edge 0 -> 38 %) and the Ahmed body to 79.3 %; combined with featureAngle 130 (C1):
   wing 95.9 % (tip 75 %, trailing edge 38 %), Ahmed 97.4 % (edges 100 %), sphere 99.5 % (unchanged). It
   also brings the first layer back to the plan where stacks used to be squashed (wing walk mean 1.29 ->
   0.89 mm against 0.90 mm planned).
3. **The relaxed tet check, the medial axis, smoothing and iteration counts do not move coverage** on the
   public cases (within 1 point), except the tet check on (Ahmed 31 -> 23.5 %), nGrow 1 and
   nBufferCellsNoExtrude 1 (worse: Ahmed 24.7 % / 0 %). The layer-only second pass gives the identical
   mesh (twoPass = base on all three cases), so it is not adopted.
4. **The aircraft is limited by its stack, not by a control.** At 24 layers every one-factor variant
   stays at 0.0 % strict coverage and 1.3 to 4.3 % mean (11 % with outer3); the cap is what moves it (12
   layers: mean 32.7 %, zero-layer 20.6 %). Combined with C1 or C2 at cap 12 the mean is 31.8 / 37.2 %, but
   no face has the full 12 layers by either count (stacks stop at 4 or 8 layers, one or two of the three
   outer passes). Validity is fragile: valid at cap 12 (cap only, C1, C2, fa130), invalid at cap 15 with
   C1, C2 and C4, and C3 is invalid at 12 but valid at 15. Cap 12 is the cap valid in every combination
   tried at that count except C3.
5. **Cells and time.** Every candidate's core mesh is identical to the baseline's (core cells equal):
   the growth is the prism cells of the planned stack, +8 % on the half wing (C1), +24 % on the Ahmed body,
   +58 % on the aircraft (C1 at cap 12), 0 % on the sphere. nOuterIter 3 costs mesh time: wing 67 -> 89 s,
   Ahmed 54 -> 57 s (contended runs), aircraft 237 s (cap 12) -> 927 s (C1 at cap 12); on the aircraft it
   adds no coverage over featureAngle 130 alone at cap 12 (mean 31.9 %, 184 s).

## Verification (Part E)

The full benchmark with the new defaults (D-106) at git `512f72b` (tagged "-dirty" only because
ARCHITECTURE.md and docs/ were being edited while it ran; no code differed): `nice -n 15 .venv/bin/python
-m vortexcfd.bench --compare benchmarks/baseline_5.4_start.json` (public cases with their indicative y+
runs, wall-clock 648 s; benchmarks/baseline_candidate.json, a copy of
benchmarks/results/20261020T130328Z_512f72b-dirty.json) and, at the same time, the local aircraft CAD union
through the same runner with its y+ run (mesh valid; benchmarks/results/local/20261020T130328Z_512f72b-dirty.json,
git-ignored; the local config does not enable the aircraft's y+ run, so the session script set it).
Part E wall-clock: 1,257 s. baseline.json is unchanged: the owner decides.

| Case | Hard / soft | Cells (vs start) | Strict cov. % (start) | Zones strict % (start) / mean % | Mean / target % | Thickness % of plan | Max non-ortho | Fidelity RMS mm | y+ mean | y+ in band % | Mesh s / total s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere | 0 / 0 | 276,078 (0 %) | 99.5 (99.5) | - | 100.2 | 100.9 | 46.7 | 0.089 | 26.8 | 60.9 | 51 / 209 |
| half wing | 0 / 0 | 364,942 (+8.0 %) | 95.9 (76.8) | trailing edge 38.3 (0.0) / 73, tip 75.2 (0.0) / 87, root 96.0 (87.4) / 99 | 98.1 | 96.9 | 64.8 | 0.107 | 27.1 | 64.6 | 60 / 239 |
| Ahmed body | 0 / 0 | 279,054 (+23.6 %) | 97.4 (31.1) | rear edges 100.0 (0.0) / 100, slant edges 99.7 (14.5) / 100 | 100.0 | 100.5 | 64.8 | 0.063 | 25.9 | 46.2 | 42 / 198 |
| aircraft (CAD union) | 0 / 1 (3 / 2) | 444,586 (+58.2 %) | 0.0 (0.0) | wing junction 0.0 / 3, htail junction 0.0 / 21, vtail junction 0.0 / 43, trailing edge 0.0 / 0, tips 0.0 / 2 (start: all 0.0 / 0-1) | 31.8 (2.2) | 10.2 (8.4) | 80.3 (174.4) | 3.54 / 4.55 | 618.6 | 30.5 | 793 / 1,185 |

Layer counts and thickness from the mesh (D-105); snappyHexMesh's own strict coverage: 100.0 / 96.0 /
99.3 / 0.0 %. Target layers 10 / 11 / 10 as before; the aircraft 12 (capped from 24, ratio 1.3; the
achievable stack is 47 mm of the planned 250 mm, 19 %, shown in its Mesh properties). Core cells (cells
minus prism cells) are unchanged on every case: the cell growth is the planned stack's own prism cells.
The aircraft's one soft failure is skewness 4.33 (2 faces); 42 faces are between 70 and 90 degrees (soft
"*" warnings). y+ in band = area with y+ in [25, 100] (0.5 to 2 x the target 50); y+ values are indicative
(400 iterations).

`--compare` against benchmarks/baseline_5.4_start.json: coverage up 19.1 points (wing) and 66.3 points
(Ahmed), worst zones 0 -> 38.3 / 99.7 %, max non-orthogonality and fidelity unchanged; REGRESSION Ahmed
cells up 23.6 % (the 10 % rule of D-082; all prism cells); time flags (the start file was mesh only).
The aircraft against its start result: hard failures 3 -> 0, max non-orthogonality 174.4 -> 80.3; REGRESSION
24 more faces above 70 degrees and cells up 58.2 %; FLAG target layers 24 -> 12.

Observations:

1. y+ on the public cases is now close to what the y+ estimator delivers by its convention (the
   first-layer height is used as the cell height, so the cell-centre y+ that OpenFOAM reports is about half
   the target, foam/yplus.py): 26.8 / 27.1 / 25.9 against 26.8 / 43.3 / 67.8 in baseline.json. The wing and
   the Ahmed body used to be higher because their squashed stacks put thicker cells at the wall (walk mean
   first layer 1.29 / 1.87 mm, now 0.89 / 0.90 mm against 0.90 mm planned). Sitting at the lower edge of the
   [25, 100] band, the Ahmed body's in-band share drops from 57.9 to 46.2 %.
2. The aircraft's y+ is far off: mean 618.6, 30.5 % in band. The planned first layer is unchanged (0.64 mm),
   but 28.8 % of the wall has no layer on 84 mm surface cells and where stacks are partial the outer passes
   are the ones that stayed (walk mean first layer 3.7 mm). The y+ the plan asks for is not reached there.
3. Mesh time: +18 % / +0 % / -22 % (sphere unchanged, wing 51 -> 60 s, Ahmed 54 -> 42 s, single runs, noisy);
   the aircraft 168 -> 793 s (nOuterIter 3 with each pass running its 50 layer iterations).

### D1 verdict

- **Zero hard checkMesh failures on every case, the aircraft included: met** (0 / 0 / 0 / 0; the aircraft
  had 3).
- **Strict coverage of at least 85 %: met on the half wing (95.9 %) and the Ahmed body (97.4 %); not met on
  the aircraft (0.0 %, 85 points short).** Why: its planned stack (24 layers, 250 mm on 21-84 mm cells) is
  3 to 12 cells deep; capped at 12 layers with ratio 1.3 it is 47 mm, but on this surface no face keeps all
  12 layers: the layer additions stop after one or two of the three outer passes (4 or 8 layers; mean 31.8 %
  of the target), with quality removal, medial-axis reductions and the shrink scaling acting on the
  21-84 mm cells around the junctions and the thin wing (Diagnosis 3). No combination of the allowed
  controls in the study reached a full stack anywhere on it while staying valid; reaching it would need
  finer surface cells (not allowed: no new surface refinement levels) or a higher target y+.
- **Hard zones improve from 0 %: met on the public cases** (wing trailing edge 0 -> 38.3 %, tip 0 -> 75.2 %,
  Ahmed rear edges 0 -> 100 %, slant edges 14.5 -> 99.7 %); **not met on the aircraft by the strict measure**
  (every zone still 0.0 %), where only the mean layers rise (junctions 0-1 % -> 3-43 % of the target).
- Cell growth (D3, 20 %): the half wing +8 %, the Ahmed body +24 %, the aircraft +58 %; in every case the
  core mesh is unchanged and the extra cells are the prism layers the y+ plan asks for (read as allowed,
  docs/QUESTIONS.md item 138).

Total machine time of the session's runs: 4,549 s (75.8 min) wall-clock (Part A 262 s, study 1,485 + 1,545 s,
Part E 1,257 s; benchmarks/results/5.4/machine_time.log).
