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
