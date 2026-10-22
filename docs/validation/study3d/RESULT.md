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
