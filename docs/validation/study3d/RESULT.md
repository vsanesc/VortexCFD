# 3D mesh study check of D-127 (QUESTIONS 203)

Task w2-naca-r2, owner review of round 3, item 1 (2026-10-22). `scripts/validation/study3d_check.py`: the app's
mesh study (D-066; ratio sqrt(2), the current settings as the fine level) of the public benchmark's sphere and half
wing, mesh only, serial snappyHexMesh at nice 15; every non-current level also meshed as a single mesh, i.e. the
same MeshCaseInput with buffer_scale 1 (nCellsBetweenLevels 3, no shells); the fine level is the current settings,
a single mesh already (233,534 and 300,025 cells: the benchmark baseline's). Numbers: result.json (the 0.1 L
window) and points_nearest.json (the cell containing a point and a 0.25 L window); cases in run/validation/study3d/
(git-ignored). Machine time 6.6 min (meshing 395 s, measurements 0.5 min).

## Per level against the single mesh

"Cov." = strict layer coverage from the mesh walk (the wall area with the full count), per zone for the wing;
"first" = the walked first cell (area-weighted mean; planned 1.8013 mm on every level, the shared stack of D-066).
Every mesh: 0 hard and 0 soft checkMesh failures, 0 faces above 70 degrees.

| Case | Level (base) | Mesh | Cells | Max non-ortho | Max skew | Cov. | Zones: trailing edge / tips / root | First | Mean layers |
|---|---|---|---|---|---|---|---|---|---|
| sphere | coarse (0.537 m) | study | 93,976 | 39.41 | 0.53 | 100.00 % | - | 1.8007 mm | 6.03 |
| sphere | coarse | single | 45,945 | 50.98 | 0.74 | 100.00 % | - | 1.7989 mm | 6.00 |
| sphere | medium (0.380 m) | study | 219,071 | 39.00 | 0.52 | 100.00 % | - | 1.8010 mm | 6.03 |
| sphere | medium | single | 110,271 | 49.81 | 0.97 | 100.00 % | - | 1.8002 mm | 6.02 |
| sphere | fine (0.2685 m) | study = single | 233,534 | 46.46 | 0.85 | 99.59 % | - | 1.8007 mm | 6.02 |
| wing | coarse (0.635 m) | study | 86,384 | 63.22 | 1.48 | 86.61 % | 0.0 / 0.0 / 87.2 % | 1.9341 mm | 6.50 |
| wing | coarse | single | 107,283 | 63.23 | 1.48 | 86.63 % | 0.0 / 0.0 / 87.2 % | 1.9333 mm | 6.50 |
| wing | medium (0.449 m) | study | 193,367 | 61.69 | 2.35 | 93.23 % | 21.5 / 54.8 / 95.7 % | 1.7957 mm | 6.78 |
| wing | medium | single | 166,720 | 62.01 | 2.35 | 93.18 % | 21.5 / 54.1 / 95.2 % | 1.7978 mm | 6.78 |
| wing | fine (0.317 m) | study = single | 300,025 | 64.91 | 2.82 | 94.37 % | 38.4 / 50.0 / 97.1 % | 1.7881 mm | 6.81 |

Validity, layers and quality: every level valid; coverage within 0.1 point overall and 0.7 point per zone of the
single mesh, the same first cell (within 0.2 %), non-orthogonality equal or lower (sphere 39 against 50-51). The
1-cell transitions (nCellsBetweenLevels 1) do not hurt quality or layers. Cells: the sphere's study levels have
twice the single mesh's (93,976 against 45,945; 219,071 against 110,271); the wing's -19 % (coarse) and +16 %
(medium).

## Cell size at fixed points

Points: one reference length (L = 1 m) ahead of the parts' box, above it and two behind it (the wake), at the box's
middle; the owner's measure, the median within 0.1 L, finds no cell centre at most points (the cells there are
0.27-0.64 m), so the size of the cell containing the point (nearest centre) is given, coarse / medium / fine:

| Case, point | Study levels | Ratios | Single meshes (coarse / medium; fine = study) |
|---|---|---|---|
| sphere, 1 L ahead | 547 / 382 / 269 mm | 1.43, 1.42 | 273 / 382 / 269 mm |
| sphere, 1 L above | 548 / 382 / 269 mm | 1.43, 1.42 | 274 / 382 / 269 mm |
| sphere, 2 L wake | 546 / 382 / 269 mm | 1.43, 1.42 | 545 / 381 / 269 mm |
| sphere, 0.5 L ahead (extra) | 137 / 96 / 135 mm | 1.43, 0.71 | 137 / 96 / 135 mm |
| sphere, 0.5 L above (extra) | 275 / 96 / 135 mm | 2.86, 0.71 | 137 / 96 / 135 mm |
| wing, 1 L ahead | 318 / 450 / 318 mm | 0.71, 1.42 | 318 / 224 / 318 mm |
| wing, 1 L above | 319 / 449 / 318 mm | 0.71, 1.41 | 318 / 224 / 318 mm |
| wing, 2 L wake | 636 / 449 / 318 mm | 1.42, 1.41 | 636 / 449 / 318 mm |

The sizes shrink by the level ratio where the points are in the background (the sphere at 1-2 L, the wing's wake),
where the single meshes were not monotonic (the sphere's coarse single mesh is finer one length ahead than the
medium). Inside the transition zone they do not (the wing at 1 L, the sphere at 0.5 L): the non-current levels'
shells (the current settings' buffer distances, D_k = the sum of 3 cells of each level from the part's maximum down
to k) do not reproduce the current level's own transitions, which snappyHexMesh makes from its 3-cell buffers
counted from the cells cut by the surface (the shells' level-max band is 3 current cells thick against about one
cut cell: the sphere's study levels have twice the cells), and a point near a shell edge falls on either side
depending on the level's cell (quantised to that level's cells).

## Verdict

Item 1 does **not pass**: every level is valid and coverage, layers and quality are within noise of the single
meshes, but the sizes do not shrink with the level ratio inside the transition zone, and the current level is not
geometrically similar to the others there. D-127 stays Proposed. The 2D part (identical staircase boxes, verified on
the NACA 0012 study, RESULT.md of the NACA, Round 3) is not affected.

Proposed fix (not applied; QUESTIONS 204): mesh every 3D study level, the current one included, with the shells
and nCellsBetweenLevels 1, so the three levels share the same transition geometry in metres and differ only in
cell size (the current level then no longer equals the single mesh: report the single mesh beside the study);
or, keeping the current level as the single mesh, shells that reproduce snappyHexMesh's buffers (no level-max band
beyond the cut cells: D_k = the sum of 3 cells from level max - 1 down to k), which needs a check of how close it
comes. Either way the check here, with the points chosen inside and outside the transition zone, is the test.

## Round 2: one mechanism for every 3D level (QUESTIONS 204)

Task w3-internal, Part 0 (2026-10-22). Owner decision on QUESTIONS 204: every level of a 3D study, the current one
included, is meshed with the distance shells and nCellsBetweenLevels 1 (`MeshCaseInput.study_level`); the study's
current level is then no longer the user's single mesh. Same script (`--out result.json`; round 1's numbers moved to
result_q203.json), the same points plus the transition-zone points of round 1 (0.5 L ahead and above, 1 L behind),
each measured by the size of the cell that contains it (`containing_cell`: the cell whose faces all have the point on
their inner side, among the 64 nearest centres). Single meshes not meshed again (round 1 has them; meshing is
deterministic: the coarse and medium study levels reproduce round 1's to the cell). Machine time 5.9 min.

| Case | Level | Cells (round 1) | Valid | Strict cov. (round 1) | Zones TE / tips / root (round 1) | Max non-ortho (round 1) | Max skew | First cell |
|---|---|---|---|---|---|---|---|---|
| sphere | coarse | 93,976 (93,976) | yes, 0 hard / 0 soft | 100.00 % (100.00) | - | 39.4 (39.4) | 0.53 | 1.8007 mm |
| sphere | medium | 219,071 (219,071) | yes, 0 / 0 | 100.00 % (100.00) | - | 39.0 (39.0) | 0.52 | 1.8010 mm |
| sphere | fine | 530,395 (233,534 single) | yes, 0 / 0 | 92.30 % (99.59) | - | 40.3 (46.5) | 0.54 | 1.8011 mm |
| wing | coarse | 86,384 (86,384) | yes, 0 / 0 | 86.61 % (86.61) | 0.0 / 0.0 / 87.2 (same) | 63.2 (63.2) | 1.48 | 1.9341 mm |
| wing | medium | 193,367 (193,367) | yes, 0 / 0 | 93.23 % (93.23) | 21.5 / 54.8 / 95.7 (same) | 61.7 (61.7) | 2.35 | 1.7957 mm |
| wing | fine | 459,674 (300,025 single) | yes, 0 / 0 | 94.50 % (94.37) | 38.4 / 51.6 / 97.1 (38.4 / 50.0 / 97.1) | 65.0 (64.9) | 2.81 | 1.7885 mm |

Every level valid, no face above 70 degrees. The sphere's fine level walks at 92.30 % against 99.59 %: an artefact
of the walk's aspect limit (`layer_walk.MAX_ASPECT` 0.6): snappyHexMesh's table gives 6 of 6 layers at 100 %
thickness on every face, and the same walk with the limit at 0.8 counts 6 layers or more on 100.00 % of the area
(5,020 faces stop at 5 with 0.6: the sixth layer, about 4.5 mm, is just over 0.6 of the level-5 faces next to the
1-cell buffer). Layers and quality are otherwise within noise of round 1. Cost: the fine level has 2.27 x (sphere)
and 1.53 x (wing) the single mesh's cells (the shells' level-5 band; the study plan's estimate does not include it).

Size of the cell containing each point, coarse / medium / fine (ratio r = 1.414; pass: each ratio within 15 %, i.e.
1.20 to 1.63):

| Case, point (distance to the surface) | Cells (mm) | Ratios c/m, m/f | Pass |
|---|---|---|---|
| sphere, 1 L ahead (1.000 m) | 547.1 / 382.0 / 269.3 | 1.43, 1.42 | yes |
| sphere, 1 L above (1.000 m) | 547.6 / 382.1 / 268.8 | 1.43, 1.42 | yes |
| sphere, 2 L wake (2.000 m) | 545.8 / 381.7 / 268.3 | 1.43, 1.42 | yes |
| sphere, 0.5 L ahead (0.500 m) | 274.3 / 191.7 / 135.1 | 1.43, 1.42 | yes |
| sphere, 0.5 L above (0.500 m) | 275.0 / 191.8 / 135.3 | 1.43, 1.42 | yes |
| sphere, 1 L wake (1.000 m) | 546.8 / 382.3 / 269.1 | 1.43, 1.42 | yes |
| wing, 1 L ahead (1.001 m) | 317.9 / 449.8 / 317.8 | 0.71, 1.42 | **no** |
| wing, 1 L above (1.005 m) | 318.7 / 449.0 / 317.7 | 0.71, 1.41 | **no** |
| wing, 2 L wake (2.006 m) | 635.7 / 448.8 / 318.0 | 1.42, 1.41 | yes |
| wing, 0.5 L ahead (0.501 m) | 160.7 / 113.4 / 79.6 | 1.42, 1.42 | yes |
| wing, 0.5 L above (0.506 m) | 158.9 / 224.2 / 158.8 | 0.71, 1.41 | **no** |
| wing, 1 L wake (1.006 m) | 317.6 / 448.7 / 159.0 | 0.71, 2.82 | **no** |

Diagnosis: the shells are now the same in metres on every level (wing: D_1 = 0.922 m, D_2 = 0.446 m, D_3 = 0.208 m;
sphere: D_1 = 0.780 m, D_2 = 0.378 m), and the failing wing points lie 0.06-0.08 m outside a shell edge (1.001-1.006 m
against D_1, 0.506 m against D_2), within half a coarse cell (0.32 m) of it. snappyHexMesh tests a shell at
the cell centres of the level being refined (v2606 meshRefinementRefine.C, markInternalRefinement), so a coarse
cell whose centre is inside the edge is refined and its children
contain the point, while the smaller medium cell is outside; at the wake point 1 L behind the fine level is refined
one level further for the same reason (159 against 318 mm). The sphere's points are 0.22 m or more from every edge
and all pass. The transitions are now one mechanism on every level (round 1's cause, the current level's own
buffers, is gone: the current level's sizes are geometrically similar to the others wherever a point is not within
about half a coarse cell of a shell edge), but a fixed point near a shell edge still sees a level jump.

### Verdict (round 2)

**Not passed.** Every level valid; layers (with the walk artefact explained) and quality within noise of round 1; the
cell size shrinks by the level ratio at all 6 sphere points but at only 2 of 6 wing points (4 fail by a whole level
at a shell edge). D-127 stays Proposed and QUESTIONS 204 stays open with these numbers. As instructed, the pipe mesh
study of task w3-internal Part B is not run (a single level instead).

## Round 3: shell distances in coarse cells, a cube-averaged size (QUESTIONS 204, owner review)

Task w3-internal, owner review of W3 (2026-10-22), item 1. Two changes: (a) every shell distance rounded up to a whole
number of the coarse level's cells of the level the shell refines from (coarse base / 2^(k-1) for the shell of level k,
the cells whose centres snappyHexMesh tests), so the edges are the same in metres AND in coarse cells on every level;
(b) the measure: the volume-weighted mean cell size (sum V h / sum V, h = V^(1/3)) of the cells whose centres lie in an
axis-aligned cube of side 2 coarse cells (the coarse level's containing cell) centred on each point
(`study3d_check.cube_means`; result_q204b.json). Machine time 12.8 min (meshed beside a 2D run).

| Case | Level | Cells (round 2) | Valid | Strict cov. (round 2) | Zones TE / tips / root | Max non-ortho | First cell |
|---|---|---|---|---|---|---|---|
| sphere | coarse | 105,036 (93,976) | yes, 0 / 0 | 100.00 % (100.00) | - | 37.7 | 1.8007 mm |
| sphere | medium | 260,133 (219,071) | yes, 0 / 0 | 100.00 % (100.00) | - | 39.0 | 1.8010 mm |
| sphere | fine | 646,056 (530,395) | yes, 0 / 0 | 92.30 % (92.30) | - | 40.2 | 1.8011 mm |
| wing | coarse | 91,431 (86,384) | yes, 0 / 0 | 86.61 % (86.61) | 0.0 / 0.0 / 87.2 | 63.2 | 1.9342 mm |
| wing | medium | 226,391 (193,367) | yes, 0 / 0 | 93.18 % (93.23) | 21.5 / 54.0 / 95.7 | 61.9 | 1.7978 mm |
| wing | fine | 545,984 (459,674) | yes, 0 / 0 | 94.50 % (94.50) | 38.4 / 51.6 / 97.1 | 65.0 | 1.7884 mm |

Mean cell size in the cube, coarse / medium / fine (cells counted), ratios (pass: 1.20 to 1.63 each):

| Case, point | Cube side | Mean size (mm) | Cells | Ratios c/m, m/f | Pass |
|---|---|---|---|---|---|
| sphere, 1 L ahead | 548 mm | 273.6 / 190.8 / 227.5 | 8 / 8 / 41 | 1.43, 0.84 | no |
| sphere, 1 L above | 548 mm | 273.6 / 190.7 / 215.1 | 4 / 18 / 38 | 1.43, 0.89 | no |
| sphere, 2 L wake | 1092 mm | 545.6 / 381.0 / 268.5 | 8 / 18 / 100 | 1.43, 1.42 | yes |
| sphere, 0.5 L ahead | 275 mm | 137.5 / 95.9 / 101.3 | 4 / 12 / 36 | 1.43, 0.95 | no |
| sphere, 0.5 L above | 275 mm | 137.6 / 176.4 / 91.0 | 8 / 10 / 64 | 0.78, 1.94 | no |
| sphere, 1 L wake | 1094 mm | 410.0 / 310.7 / 216.9 | 36 / 97 / 369 | 1.32, 1.43 | yes |
| wing, 1 L ahead | 636 mm | 317.7 / 221.9 / 222.4 | 4 / 14 / 52 | 1.43, 1.00 | no |
| wing, 1 L above | 636 mm | 317.9 / 224.2 / 222.5 | 4 / 27 / 52 | 1.42, 1.01 | no |
| wing, 2 L wake | 1272 mm | 635.8 / 448.9 / 318.0 | 8 / 18 / 64 | 1.42, 1.41 | yes |
| wing, 0.5 L ahead | 322 mm | 265.6 / 112.5 / 79.6 | 5 / 12 / 64 | 2.36, 1.41 | no |
| wing, 0.5 L above | 318 mm | 158.9 / 111.9 / 111.1 | 4 / 18 / 52 | 1.42, 1.01 | no |
| wing, 1 L wake | 635 mm | 572.1 / 224.4 / 159.0 | 6 / 12 / 64 | 2.55, 1.41 | no |

### Verdict (round 3)

**Not passed**: every level valid, coverage, layers and quality as in round 2 (the rounded shells add 12-22 % cells),
but the mean size shrinks by the ratio at 2 of 6 sphere points and 1 of 6 wing points. The rounding moved the shell
edges outwards by up to a coarse cell, so other points now straddle them; each level still decides the refinement at
its own cell centres, whose positions relative to an edge differ between levels whatever the distance (a cube of 2
coarse cells holds 4 to 8 coarse cells, so its mean still flips with one cell). Change (a) is reverted in the app (it
costs cells and does not pass); the measure (b) stays in the check script. D-127 stays Proposed, QUESTIONS 204 open;
the pipe's mesh study is not run (owner's instruction).

## Round 4: level-scaled buffers (QUESTIONS 204, task w3-close)

Task w3-close, item 1 (2026-10-22). Owner decisions: the point-wise criterion is withdrawn (an octree cell is
base / 2^L, so a point that changes level jumps by a factor of 2); the defect to fix is the fixed 3-cell buffers.
Mechanism (D-127, rewritten): no distance shells; level k's nCellsBetweenLevels is max(1, round(3 r^(k - k_current)))
(rounded half up): 2 / 2 / 3 here (current settings as the fine level), so the current level is the user's single mesh.
Same script (`--out result_w3close.json`; the summary is `study3d_check.summary`), the same six points, the cube mean
over 2 coarse cells (round 3's measure). Pass: every level valid with quality and coverage within noise; per level
pair the geometric mean of the six points' ratios within 10 % of r = 1.414 (1.273 to 1.556); no ratio off r by more
than a factor of 2. Machine time 4.6 min (277 s).

Dictionaries: the study's current (fine) level against prepare_job's single mesh, `system/` and `constant/triSurface`
(6 + 2 files per case), `diff -r`: identical on the sphere, the half wing and the Ahmed body. The public benchmark's
meshing and solver dictionaries (`public_dicts.py`, 51 files) identical to main.

| Case | Level | nCellsBetweenLevels | Cells | Valid | Strict cov. | Zones TE / tips / root | Max non-ortho | Max skew | First cell |
|---|---|---|---|---|---|---|---|---|---|
| sphere | coarse | 2 | 40,024 | yes, 0 / 0 | 100.00 % | - | 51.1 | 0.69 | 1.7989 mm |
| sphere | medium | 2 | 95,175 | yes, 0 / 0 | 97.55 % | - | 57.8 | 1.21 | 1.8466 mm |
| sphere | fine | 3 | 233,534 (= single) | yes, 0 / 0 | 99.59 % | - | 46.5 | 0.85 | 1.8007 mm |
| wing | coarse | 2 | 90,063 | yes, 0 / 0 | 86.63 % | 0.0 / 0.0 / 87.2 | 63.2 | 1.48 | 1.9330 mm |
| wing | medium | 2 | 142,551 | yes, 0 / 0 | 93.00 % | 21.5 / 51.0 / 95.1 | 62.8 | 2.35 | 1.7957 mm |
| wing | fine | 3 | 300,025 (= single) | yes, 0 / 0 | 94.37 % | 38.4 / 50.0 / 97.1 | 64.9 | 2.82 | 1.7881 mm |

Against the single meshes at the same settings (round 1): the wing within noise (coverage 86.63 / 93.00 against
86.63 / 93.18 %); the sphere's coarse level within noise (100 %), its medium level not quite (97.55 % strict coverage
and 57.8 degrees against 100 % and 49.8, the first cell 1.8466 against 1.8002 mm: the two-cell buffers).

Cube mean, coarse / medium / fine (cells counted), ratios c/m, m/f:

| Case, point | Cube side | Mean size (mm) | Cells | Ratios c/m, m/f |
|---|---|---|---|---|
| sphere, 1 L ahead | 548 mm | 273.7 / 317.7 / 269.0 | 8 / 5 / 18 | 0.86, 1.18 |
| sphere, 1 L above | 548 mm | 273.7 / 300.0 / 269.1 | 4 / 7 / 12 | 0.91, 1.11 |
| sphere, 2 L wake | 1092 mm | 545.8 / 380.8 / 268.4 | 8 / 18 / 100 | 1.43, 1.42 |
| sphere, 0.5 L ahead | 549 mm | 205.6 / 153.2 / 118.1 | 36 / 76 / 176 | 1.34, 1.30 |
| sphere, 0.5 L above | 275 mm | 137.3 / 176.5 / 135.2 | 8 / 10 / 4 | 0.78, 1.31 |
| sphere, 1 L wake | 548 mm | 274.0 / 318.3 / 269.3 | 8 / 5 / 18 | 0.86, 1.18 |
| wing, 1 L ahead | 636 mm | 264.6 / 313.9 / 264.6 | 20 / 13 / 20 | 0.84, 1.19 |
| wing, 1 L above | 637 mm | 318.2 / 329.7 / 264.8 | 6 / 10 / 20 | 0.96, 1.25 |
| wing, 2 L wake | 1272 mm | 572.3 / 448.8 / 318.0 | 24 / 18 / 64 | 1.28, 1.41 |
| wing, 0.5 L ahead | 322 mm | 159.6 / 194.1 / 159.1 | 8 / 8 / 8 | 0.82, 1.22 |
| wing, 0.5 L above | 318 mm | 158.9 / 164.7 / 142.9 | 4 / 10 / 24 | 0.96, 1.15 |
| wing, 1 L wake | 635 mm | 317.7 / 387.5 / 318.0 | 8 / 8 / 8 | 0.82, 1.22 |

| Case | Geometric mean c/m | Geometric mean m/f | All 12 ratios | Worst factor off r | Pass |
|---|---|---|---|---|---|
| sphere | 1.002 | 1.246 | 1.117 | 1.82 | **no** |
| wing | 0.937 | 1.236 | 1.076 | 1.73 | **no** |

Diagnosis: the integer count cannot follow r over two levels: 3 / r^2 = 1.5 and 3 / r = 2.12 both round to 2, so the
coarse level's buffers are r times the medium's in metres (2 x 0.537 m against 2 x 0.380 m per level step) and its
near field is no coarser than the medium's (the medium level is the coarsest of the three at four of six points on
each case); 2 against 3 at the medium / fine step leaves that ratio 12-13 % short of r. The background points (2 L
wake) scale by r on both cases.

### Verdict (round 4)

**Not passed** (the geometric means; every level valid, no point off by a factor of 2). By the owner's closure rule
W3 closes with this limitation, accepted for v1: a 3D mesh study does not refine the near field by the level ratio,
so its GCI describes the wall cells and the background, not the transition zone. D-127 stays Proposed, rewritten to
this mechanism (kept over the shells: it fails by less, and the current level is the user's mesh at its own cost);
QUESTIONS 204 closed; the pipe's three-level study is not run.
