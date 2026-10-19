# 5.2 starting point: the local aircraft through the current pipeline

Local cases (D-094): the owner's aircraft, two STEP exports of the same model from a conceptual design
tool, kept outside the repository; numbers only. Run on 2026-10-19 18:04 UTC at git `e860cba` (clean
tree; result file benchmarks/results/local/20261019T180456Z_e860cba.json, git-ignored), mesh only for
the untrimmed export; the trimmed export's y+ run was skipped because its mesh failed checkMesh (the
benchmark runs the solver only on a valid mesh). Wall-clock 507 s for the two cases, including the
reference analysis (about 160 s).

Settings: the New simulation defaults plus the local-case deviations of D-094: one Part per body,
30 m/s, l_ref = 1.500 m (the wing's geometric mean chord), target surface size 0.1 x l_ref. Surface
level 5 (84 mm cells), curvature refinement up to level 7, 24 y+ layers (first layer 0.64 mm).

## Units

Both files declare SI metres; OpenCASCADE reads them in millimetres, the app converts to metres. The
union of the parts' boxes is 10.276 x 10.000 x 2.420 m (x 0 to 10.276, y -5 to 5, z -0.5 to 1.92):
a 10 m aircraft, so metres is right.

## Import (File > Import with "one Part per body", the app's own path)

| Export | Body (app name) | Component | CAD type | Solids | Shells | Faces | Free CAD edges | Triangles | Open edges | Non-manifold edges | Duplicate faces | Self-intersections |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| untrimmed | COMPOUND | fuselage | loose faces | 0 | 0 | 8 | 24 | 4138 | 4 | 0 | 0 | 0 |
| untrimmed | COMPOUND_2 | wing, right half | loose faces | 0 | 0 | 6 | 16 | 738 | 0 | 2 | 2 | 0 |
| untrimmed | COMPOUND_3 | wing, left half | loose faces | 0 | 0 | 6 | 16 | 738 | 0 | 2 | 2 | 0 |
| untrimmed | COMPOUND_4 | horizontal tail, right | loose faces | 0 | 0 | 6 | 16 | 508 | 0 | 2 | 2 | 0 |
| untrimmed | COMPOUND_5 | horizontal tail, left | loose faces | 0 | 0 | 6 | 16 | 508 | 0 | 2 | 2 | 0 |
| untrimmed | COMPOUND_6 | vertical tail | loose faces | 0 | 0 | 6 | 16 | 548 | 0 | 2 | 2 | 0 |
| trimmed | Trimmed_Plane_1 | fuselage | solid | 1 | 1 | 8 | 0 | 4004 | 0 | 0 | 0 | 0 |
| trimmed | Trimmed_Plane_2 | wing | solid | 1 | 1 | 8 | 0 | 1590 | 0 | 2 | 2 | 0 |
| trimmed | Trimmed_Plane_3 | horizontal tail | solid | 1 | 1 | 8 | 0 | 966 | 0 | 2 | 2 | 0 |
| trimmed | Trimmed_Plane_4 | vertical tail | solid | 1 | 1 | 6 | 0 | 562 | 0 | 2 | 2 | 0 |

Columns: CAD type, solids, shells, faces and free CAD edges (edges used by one face) from the file as
read; triangles to self-intersections from the app's surface checks on the default tessellation
(1e-3 of the diagonal = 14.5 mm, 20 degrees). The untrimmed bodies are compounds of unsewn faces
(each face's edges are free), but every one of them sews into a closed solid at 1e-3 mm. The
tessellation's non-manifold edges and duplicate faces are one sliver triangle per tip or root cap,
next to the trailing edge, where the two halves of a flat cap meet (the same in both exports); the
fuselage's 4 open edges are a crack at the nose. The untrimmed body names come from the app's import
(the file's own component names are not read).

Inter-component intersections (the app's self-intersection check run on each pair of parts; the app
does not look across parts today): untrimmed: fuselage with each wing half (53 and 54 triangles),
each horizontal tail half (59, 43) and the vertical tail (49); each horizontal tail half with the
vertical tail (57, 82). Trimmed: fuselage with wing (108), horizontal tail (111) and vertical tail
(77); horizontal tail with vertical tail (141). The two wing halves (and the two tail halves) of the
untrimmed export touch along coincident root caps without crossing.

The trimmed export is not one outer skin: it is four closed solids that still overlap (OpenCASCADE
common volumes: fuselage and wing 0.257 m3, fuselage and horizontal tail 0.020 m3, fuselage and
vertical tail 0.009 m3, the two tails 0.003 m3, inside the fuselage). Its wing and tail halves are
joined (no root caps); otherwise its surfaces are those of the untrimmed export (same areas).

## What the existing repair offers (Edit > Repair part, D-072)

| Export | Part | Method | Result snappy-ready | Triangles after | Bounding box change | Time s |
|---|---|---|---|---|---|---|
| untrimmed | fuselage | pymeshfix | yes | 4138 | 0.0 % | 0.2 |
| untrimmed | each wing half | envelope (pymeshfix changed the box by 4.6 %) | yes | 2470 / 2630 | 0.50 / 0.29 % | 3.3 |
| untrimmed | each tail | envelope (pymeshfix changed the box by 16.7-16.9 %) | yes | 2178-2334 | 0.38-0.58 % | 2.7-3.3 |
| untrimmed | all six as ONE part ("regions" import) | envelope, NOT faithful | yes | 4070 | 30.9 % | 10.6 |
| trimmed | fuselage | none needed | yes | 4004 | - | 0.04 |
| trimmed | wing, tails | envelope (pymeshfix changed the box by 2.7-16.7 %) | yes | 2510-3242 | 0.28-0.36 % | 3.2-4.1 |
| trimmed | all four as ONE part | envelope | yes | 4976 | 0.46 % | 11.2 |

The repair works on one part at a time: it closes each component (pymeshfix drops the cap slivers
with part of the component, so the fTetWild envelope takes over) but does nothing about the
intersections between parts. On the untrimmed export imported as one part, the envelope keeps a
closed shell of 6.65 m3 (the union is 7.69 m3) and moves the bounding box by 30.9 % of the diagonal:
the wings are lost; the repair report flags it as not faithful.

## Meshes (as imported, no surface preparation)

| Case | Mesh valid | Cells | Failed checks | Max non-ortho | Faces >70 | Max skew | Strict coverage % (24 layers) | Extruded % | Mean layers | Mesh->ref RMS / max mm | Mesh->ref far % | Ref->mesh RMS / max mm | Ref->mesh far % | Wall left inside a component | Patches with faces | Force sum check | Mesh s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aircraft_trimmed | no | 257,752 | 5 | 174 | 22 | 23.4 | 0.0 | 65.2 | 2.27 | 3.96 / 55.5 | 0.32 | 6.52 / 60.5 | 0.16 | 79 points, 0.047 m2 | 4/4 | ok | 131 |
| aircraft_untrimmed_as_is | no | 270,758 | 1 | 64.9 | 0 | 4.23 | 0.0 | 58.4 | 1.69 | 3.80 / 28.7 | 0.59 | 4.47 / 60.5 | 0.14 | 170 points, 0.079 m2 | 6/6 | ok | 138 |

Failed checks: trimmed: negative-volume cells, non-orthogonality errors (above 90 degrees), face
pyramids, high aspect ratio and skewness 23.4; untrimmed as imported: skewness only (4.23 > 4).
"Far" = further than half the local surface cell size. Wall left inside a component: wall points
(and faces) further than half a cell inside a reference solid.

Per zone (zones of D-094, half-width 0.075 m):

| Case | Zone | Strict coverage % | Mesh->ref RMS / max mm | Mesh->ref far % | Ref->mesh RMS / max mm | Ref->mesh far % | Wall inside m2 |
|---|---|---|---|---|---|---|---|
| trimmed | wing junction | 0 | 3.03 / 8.78 | 0 | 5.08 / 27.2 | 0 | 0 |
| trimmed | horizontal tail junction | 0 | 3.56 / 26.1 | 0.34 | 4.55 / 21.7 | 0.61 | 0.0003 |
| trimmed | vertical tail junction | 0 | 9.97 / 45.6 | 10.4 | 3.54 / 21.5 | 0.21 | 0.037 |
| trimmed | trailing edge | 0 | 4.15 / 18.2 | 0 | 3.22 / 31.1 | 0 | 0 |
| trimmed | tips | 0 | 1.53 / 4.67 | 0 | 2.46 / 15.6 | 0 | 0 |
| untrimmed as is | wing junction | 0 | 4.80 / 11.9 | 0 | 4.87 / 27.7 | 0.007 | 0.0013 |
| untrimmed as is | horizontal tail junction | 0 | 3.20 / 28.7 | 0.33 | 5.10 / 22.0 | 0.38 | 0 |
| untrimmed as is | vertical tail junction | 0 | 2.51 / 17.9 | 0.17 | 2.60 / 10.7 | 0.016 | 0 |
| untrimmed as is | trailing edge | 0 | 4.17 / 18.2 | 0 | 2.36 / 31.1 | 0 | 0 |
| untrimmed as is | tips | 0 | 1.61 / 4.75 | 0 | 2.26 / 15.6 | 0 | 0 |

## Observations

1. Both exports import without error; neither is ready for snappyHexMesh as the app judges it: the
   untrimmed components are loose faces (sewable), and every wing and tail tessellation of both
   exports carries 2 duplicate sliver triangles at its caps.
2. Neither import reports the intersections between components: the self-intersection check runs per
   part and finds 0 everywhere, while every pair that overlaps crosses (49-141 triangles per pair).
3. The existing repair is per part and cannot help the junctions; on a one-part import of the
   untrimmed export it silently loses the wings (box change 30.9 %, flagged as not faithful).
4. Both meshes fail checkMesh at these settings. The trimmed export, the reference, is the worse one
   (negative volumes, max non-orthogonality 174, 22 faces above 70 degrees), the untrimmed one fails
   only on skewness (4.23). So the trimmed file is a reference for the shape, not for the mesh.
5. Layers: the y+ 50 stack on 84 mm cells is 24 layers; no wall face gets all of them (strict
   coverage 0 %), 58-65 % of the area gets at least one (mean 1.7-2.3). Prism layers are not in scope
   (5.4), but every variant below is compared at this target.
6. Fidelity: RMS 3.8-4.0 mm from the mesh to the reference skin and 4.5-6.5 mm back, dominated by the
   default 14.5 mm tessellation deflection; the largest misses (55-60 mm) are at the vertical tail
   junction and the trailing edge (thin, 84 mm cells).
7. Wall surface left inside a component: 0.047 m2 (trimmed) and 0.079 m2 (untrimmed), about 0.1 % of
   the 59 m2 wall; 0.037 m2 of the trimmed one sits at the vertical-tail junction.
8. Every component patch has faces (no lost part) and the per-part force objects partition the wall
   in both cases.
