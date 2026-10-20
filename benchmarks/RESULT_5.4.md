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
