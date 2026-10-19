# 5.2 comparison of surface preparation strategies

Local cases (D-094), numbers only: the owner's aircraft (fuselage, wing, horizontal and vertical tail;
about 10 m), the untrimmed export (six compounds of loose faces that interpenetrate) prepared three
ways, against the trimmed export as the reference surface (four closed, still overlapping solids;
RESULT_5.2_before.md). Settings of D-094: one Part per body, 30 m/s, l_ref = 1.500 m (mean wing
chord), target surface size 0.1 x l_ref (84 mm cells, level 5, curvature up to level 7), 24 y+ 50
layers. Runs on 2026-10-19: trimmed, as is and CAD union at git `0f58073`
(benchmarks/results/local/20261019T182140Z_0f58073.json, wall-clock 531 s); intersection features
at `9c60ff0` (20261019T183121Z_9c60ff0.json) after the junction file's header was fixed (the first
run stopped at castellation: OpenFOAM refused the header's object name; that is the only change
between the two commits). Mesh only, as the task asks; the trimmed export's y+ run was skipped (its
mesh is not valid).

## Table

| Variant | Mesh valid | Cells | Failed checks | Max non-ortho | Faces >70 | Strict coverage % (24 layers) | Extruded % | Mesh->ref RMS / max mm | Mesh->ref far % | Ref->mesh RMS / max mm | Ref->mesh far % | Wall inside a component | Component patches with faces | Per-part force sum | Prep s | Mesh s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| trimmed (reference) | no | 257,752 | 5 | 174.5 | 22 | 0.0 | 65.2 | 3.96 / 55.5 | 0.32 | 6.52 / 60.5 | 0.16 | 79 points, 0.047 m2 | 4/4 | ok | - | 126 |
| untrimmed, as is | no | 270,758 | 1 (skewness 4.23) | 64.9 | 0 | 0.0 | 58.4 | 3.80 / 28.7 | 0.59 | 4.47 / 60.5 | 0.14 | 170 points, 0.079 m2 | 6/6 | ok | - | 132 |
| untrimmed, intersection features | no | 270,507 | 1 (skewness 4.23) | 64.9 | 0 | 0.0 | 57.9 | 3.81 / 40.5 | 0.58 | 4.43 / 60.5 | 0.11 | 168 points, 0.080 m2 | 6/6 | ok | 1.2 | 134 |
| untrimmed, CAD union | no | 281,113 | 5 | 174.4 | 18 | 0.0 | 50.8 | 3.54 / 18.4 | 0.18 | 4.43 / 61.3 | 0.39 | 58 points, 0.030 m2 | 6/6 | ok | 4.5 | 142 |

Per junction zone (and the other zones of D-094; half-width 0.075 m):

| Zone | Variant | Extruded % (mean layers) | Mesh->ref RMS / max mm | Mesh->ref far % | Ref->mesh RMS / max mm | Ref->mesh far % | Wall inside m2 |
|---|---|---|---|---|---|---|---|
| wing junction | trimmed | 63.7 (0.64) | 3.03 / 8.78 | 0 | 5.08 / 27.2 | 0 | 0 |
| wing junction | as is | 59.4 (0.59) | 4.80 / 11.9 | 0 | 4.87 / 27.7 | 0.007 | 0.0013 |
| wing junction | intersection features | 59.1 (0.59) | 4.99 / 11.2 | 0 | 5.17 / 20.9 | 0.007 | 0.0004 |
| wing junction | CAD union | 57.3 (0.57) | 3.14 / 11.2 | 0 | 1.33 / 12.4 | 0 | 0 |
| horizontal tail junction | trimmed | 21.8 (0.28) | 3.56 / 26.1 | 0.34 | 4.55 / 21.7 | 0.61 | 0.0003 |
| horizontal tail junction | as is | 16.0 (0.19) | 3.20 / 28.7 | 0.33 | 5.10 / 22.0 | 0.38 | 0 |
| horizontal tail junction | intersection features | 8.4 (0.10) | 2.89 / 18.5 | 0.11 | 3.06 / 16.7 | 0.12 | 0.0001 |
| horizontal tail junction | CAD union | 26.8 (0.37) | 2.52 / 7.45 | 0 | 2.03 / 11.1 | 0 | 0 |
| vertical tail junction | trimmed | 19.9 (0.26) | 9.97 / 45.6 | 10.4 | 3.54 / 21.5 | 0.21 | 0.037 |
| vertical tail junction | as is | 20.0 (0.25) | 2.51 / 17.9 | 0.17 | 2.60 / 10.7 | 0.016 | 0 |
| vertical tail junction | intersection features | 14.6 (0.19) | 3.12 / 40.5 | 0.17 | 2.19 / 11.2 | 0 | 0.0016 |
| vertical tail junction | CAD union | 52.9 (0.74) | 2.48 / 6.38 | 0 | 1.68 / 8.52 | 0 | 0 |
| wing trailing edge | trimmed / as is / int. features / CAD union | 97.9 / 97.9 / 97.5 / 97.9 | 4.15-4.17 / 18.2-18.4 | 0 | 3.22 / 2.36 / 7.14 / 0.60 (max 31.1) | 0 | 0 |
| wing tips | trimmed / as is / int. features / CAD union | 51.1 / 47.7 / 47.7 / 48.5 | 1.53 / 1.61 / 1.61 / 2.77 (max 4.7-10.4) | 0 | 2.46 / 2.26 / 2.26 / 2.98 (max 15.6-27.1) | 0-0.03 | 0 |

Strict coverage is 0.0 % in every zone of every variant (24 layers on 84 mm cells; 5.4).

Columns: as in RESULT_5.2_before.md. "Far" = further than half the local surface cell size. Wall
inside a component = wall points and faces more than half a cell inside a reference solid.
Per-part force sum: the per-part force objects partition the all-walls object's patches, every patch
with faces (geometry only, no solve); wall areas 59.06-59.14 m2 in every variant.

## Where the failed checks are

The CAD union mesh and the trimmed reference fail the same five checks (negative volumes, non-
orthogonality errors, face pyramids, aspect ratio, skewness): `checkMesh -writeSets` puts them all
on the wing's upper surface away from any junction (CAD union: x 5.8 m, y -2.8 m, z 0.11 m; trimmed:
x 5.3 m, y 1.2 m, z 0.13 m). The same CAD union case meshed again without the layer phase (a
diagnostic copy, not a benchmark variant) has 269,649 cells and fails only skewness (4.33, 2 faces),
like the as-is mesh: the invalid cells come from the 24-layer addition (relaxed tet-quality control
of D-045), not from the prepared surface. Both untrimmed meshes that keep the separate components
fail only skewness (4.23, one face).

## Observations

1. Every variant meshes, keeps every component patch (4/4 and 6/6, no lost part) and passes the
   per-part force partition: the CAD union keeps one patch and one force object per component
   through the boolean history.
2. The CAD union leaves the least wall surface inside a component: 0.030 m2 (58 points) against
   0.079-0.080 m2 for as is and intersection features and 0.047 m2 for the trimmed export itself; it
   is 0 in all three junction zones (the vertical tail junction of the trimmed export holds
   0.037 m2).
3. At the junctions the CAD union is the closest to the reference in both directions: reference ->
   mesh RMS 1.33 / 2.03 / 1.68 mm (wing / horizontal / vertical tail junction) against 4.87 / 5.10 /
   2.60 mm as is and 5.17 / 3.06 / 2.19 mm with intersection features; its largest junction miss is
   12.4 mm against 27.7 mm as is.
4. Overall the CAD union has the smallest largest deviation from the mesh to the reference (18.4 mm
   against 28.7 as is and 40.5 with intersection features) and the fewest far points (0.18 % against
   0.58-0.59 %); its RMS is 3.54 mm against 3.80-3.81 mm. The reference -> mesh maximum is about the same in
   every variant (60.5-61.3 mm) and lies outside the junction zones (their maxima are at most
   27.7 mm), so it does not separate the strategies.
5. Intersection features changed little: 262 curve segments (13.3 m) at level 5 moved the junction
   RMS by -0.3 to +0.6 mm, cut the horizontal-tail-junction misses (max 28.7 -> 18.5 mm) but raised
   the vertical-tail-junction maximum to 40.5 mm, and lowered the extruded share at the tail
   junctions (16.0 -> 8.4 %, 20.0 -> 14.6 %).
6. Layers at the junctions: the CAD union extrudes more at the tail junctions (26.8 % and 52.9 %
   against 16.0 % and 20.0 % as is) and about the same at the wing junction (57.3 % against
   59.4 %); overall it extrudes less (50.8 % against 58.4 %). No variant reaches the 24-layer target
   anywhere (strict coverage 0 %).
7. Validity: none of the four meshes passes checkMesh at these settings. The CAD union and the
   trimmed reference carry negative-volume cells from the layer phase on the wing surface (see
   above); without layers the CAD union mesh fails only skewness, like the as-is mesh.
8. Cost: preparation 1.2 s (intersection features) and 4.5 s (CAD union: sewing 0.2 s, fuse about
   3.3 s); meshing 132-142 s, cells 270,507-281,113 (+3.8 % for the CAD union, all under 500,000).

## Intersection features, investigated (owner review, item 2)

The first comparison showed no benefit from intersection features. Checked on its meshing case:

- Read: yes. log.snappyHexMesh.castellate and log.snappyHexMesh: "Read edgeMesh
  surface_prep_junctions.eMesh, points 262, edges 262", "level 5 for all cells within 0 metre".
- Snapped to: yes. "Feature analysis": 1,534 boundary points attracted to feature edges, against
  1,131 without the junction file (as imported) and 1,404 for the CAD union.
- Curves: complete. 13.32 m in 262 segments, the same lengths as the reference's own intersection
  curves (wing 7.71 m, horizontal tail 3.69 m, vertical tail 1.92 m). The rule that drops segments
  inside a third part removes only the tails' mutual curves (4.16 m), which lie entirely inside the
  fuselage.
- Refinement: none. Within 0.05 m of the curves the cells were already at level 7 (6 cells at 5, 124
  at 6, 1,200 at 7) from curvature refinement, so a level-5 feature entry added nothing.
- Normals: not the cause. snappyHexMesh reads a plain .eMesh as "external" edges without normals.
  The curves rebuilt with OpenFOAM's surfaceBooleanFeatures (concave "internal" edges with normals,
  trimmed by the other parts) at level 7 gave the same numbers as plain curves at level 7 to 0.02 mm.

Cause: the junction level (the parts' maximum surface level, 5) was below the level the surfaces
already reach at the junctions. Fix (D-097): the junction level is the maximum surface level plus the
curvature levels (7). Re-run of aircraft_untrimmed_intersection_features, mesh only, at git `e762e69`
(benchmarks/results/local/20261019T202225Z_e762e69-dirty.json; "dirty" because the item 3 name
changes to geometry/cad.py were edited while it ran, after the run had imported it: the part names in
this run are still COMPOUND, ...):

| Junction | Metric | As imported | Intersection features, level 5 | Intersection features, level 7 (fixed) | CAD union |
|---|---|---|---|---|---|
| wing | ref->mesh RMS / max mm | 4.87 / 27.7 | 5.17 / 20.9 | 2.13 / 11.2 | 1.33 / 12.4 |
| wing | mesh->ref RMS / max mm | 4.80 / 11.9 | 4.99 / 11.2 | 3.61 / 11.2 | 3.14 / 11.2 |
| wing | extruded % | 59.4 | 59.1 | 0.4 | 57.3 |
| horizontal tail | ref->mesh RMS / max mm | 5.10 / 22.0 | 3.06 / 16.7 | 2.07 / 7.7 | 2.03 / 11.1 |
| horizontal tail | mesh->ref RMS / max mm | 3.20 / 28.7 | 2.89 / 18.5 | 2.92 / 7.9 | 2.52 / 7.45 |
| horizontal tail | extruded % | 16.0 | 8.4 | 7.0 | 26.8 |
| vertical tail | ref->mesh RMS / max mm | 2.60 / 10.7 | 2.19 / 11.2 | 2.32 / 8.5 | 1.68 / 8.52 |
| vertical tail | mesh->ref RMS / max mm | 2.51 / 17.9 | 3.12 / 40.5 | 2.59 / 8.7 | 2.48 / 6.38 |
| vertical tail | extruded % | 20.0 | 14.6 | 19.6 | 52.9 |

Overall with the fix: 281,235 cells, checkMesh fails only skewness (4.23), as imported; mesh -> reference
RMS / max 3.74 / 21.0 mm (as imported 3.80 / 28.7), reference -> mesh RMS 3.81 mm (4.47), wall left inside
a component 0.081 m2 (0.079), extruded 52.4 % (58.4 %); preparation 1.3 s, meshing 149 s.

Intersection features now improve every junction against no preparation (reference -> mesh RMS about
halved, worst junction miss 27.7 -> 11.2 mm), close to the CAD union except at the wing junction (2.13
against 1.33 mm), and at the cost of the wing junction's layers (0.4 % extruded). It stays the
fallback of the CAD union. The CAD union was not re-run: its junctions are its parts' open edges,
refined at the parts' surface level (5), so it might gain from the same rule (docs/QUESTIONS.md).

## CAD union junction edges at the junction level (owner review, QUESTIONS 121)

Rejected by the owner (D-101): the small junction gain does not justify losing the junction layers;
the code was reverted, the CAD union keeps its junctions at the parts' surface level. The numbers
below stay as the evidence.

The CAD union's junctions (the open edges of the parts' shares of the union, 13.32 m in 130 edges)
now go to the junction feature file at the junction level (D-101: level 7 instead of the parts'
level 5). Re-run of aircraft_untrimmed_cad_union, mesh only, at git `1b96112`, clean tree
(benchmarks/results/local/20261019T204540Z_1b96112.json; the part names now come from the file,
D-098: Fuselage_0, Ala_0, ...). Junction numbers against the item 2 table:

| Junction | Metric | As imported | Intersection features (level 7) | CAD union, level 5 (before) | CAD union, level 7 (now) |
|---|---|---|---|---|---|
| wing | ref->mesh RMS / max mm | 4.87 / 27.7 | 2.13 / 11.2 | 1.33 / 12.4 | 1.29 / 12.2 |
| wing | mesh->ref RMS / max mm | 4.80 / 11.9 | 3.61 / 11.2 | 3.14 / 11.2 | 3.82 / 10.6 |
| wing | extruded % | 59.4 | 0.4 | 57.3 | 3.5 |
| horizontal tail | ref->mesh RMS / max mm | 5.10 / 22.0 | 2.07 / 7.7 | 2.03 / 11.1 | 1.69 / 7.42 |
| horizontal tail | mesh->ref RMS / max mm | 3.20 / 28.7 | 2.92 / 7.9 | 2.52 / 7.45 | 2.56 / 7.45 |
| horizontal tail | extruded % | 16.0 | 7.0 | 26.8 | 6.8 |
| vertical tail | ref->mesh RMS / max mm | 2.60 / 10.7 | 2.32 / 8.5 | 1.68 / 8.52 | 1.41 / 6.40 |
| vertical tail | mesh->ref RMS / max mm | 2.51 / 17.9 | 2.59 / 8.7 | 2.48 / 6.38 | 2.23 / 6.38 |
| vertical tail | extruded % | 20.0 | 19.6 | 52.9 | 19.6 |

Overall, CAD union now (before): 290,885 cells (281,113); checkMesh fails only the skewness check,
4.22, a soft warning (D-100) (before: five checks with negative-volume cells on the wing surface, so
this mesh is now valid); mesh -> reference RMS / max 3.66 / 20.9 mm (3.54 / 18.4); reference -> mesh
RMS 4.35 mm (4.43); wall left inside a component 0.064 m2 (0.030); extruded 44.6 % (50.8 %);
preparation 4.5 s, meshing 161 s (142).

So the change is not neutral: the reference -> mesh distance at the three junctions improves (RMS
-0.04 / -0.34 / -0.27 mm, the tail maxima from 11.1 and 8.5 to 7.4 and 6.4 mm) and the mesh loses
its hard checkMesh failures, while the junction layers collapse as they did with intersection
features (wing junction 57.3 -> 3.5 % extruded) and twice as much wall is left inside a component.
Whether the valid mesh is a consequence of the finer junction cells or a chance change of the layer
phase elsewhere on the wing (where the negative volumes were) was not separated.

## Proposed default

**CAD union**, falling back per part to intersection features (automatic, reported). Accepted by the owner (review of 2026-10-19); the fallback was confirmed by the investigation above (D-097). Reason, from
the numbers above: it is the only strategy that moves the junctions towards the reference (reference
-> mesh RMS at the three junctions 1.3-2.0 mm against 2.6-5.2 mm), it removes the internal surface at
the junctions (0 m2 against up to 0.0016 m2) and overall (0.030 against 0.080 m2), and it has the
smallest largest deviation (18.4 mm); intersection features measured within noise of doing nothing.
Its mesh is invalid at these settings, but so is the trimmed reference's, at a place away from the
junctions and only with the 24-layer stack (without layers it fails the same skewness check as the
as-is mesh): a prism-layer problem for 5.4, not a reason against the prepared surface. The owner
decides (D-093 [NUMERICS-REVIEW]; docs/QUESTIONS.md).

A shell wrapper (implicit-surface or envelope wrapping) does not look necessary for this model: the
CAD union succeeded on all six components (every one sews closed at 0.145 mm and the fuse is valid).
It would be needed for inputs that do not sew or fuse; the existing envelope repair already showed
on this model that wrapping can lose thin parts (RESULT_5.2_before.md: the wings lost on a one-part
envelope).

## Public benchmark (surface preparation must not change single-component geometry)

Full public benchmark (sphere, half wing, Ahmed body, with the y+ runs) at git `9c60ff0`, clean tree,
2026-10-19 18:37 UTC (benchmarks/results/20261019T183716Z_9c60ff0.json), `--compare
benchmarks/baseline.json`: **no regressions**. Cells, max non-orthogonality, faces above 70 degrees,
strict coverage, zone coverage and fidelity are identical to the baseline in all three cases (sphere
276,078 cells, wing 337,824, Ahmed 225,842); y+ means 26.79 / 43.28 / 67.76 (differences below 0.02);
total times 204 / 226 / 168 s (all faster). Wall-clock 599 s. The public cases are single-component
and never run the preparation (it is an explicit operation); a prepared one-part project meshes
byte-identically (D-093).
