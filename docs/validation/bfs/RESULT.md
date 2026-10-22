# NASA TMR 2D backward-facing step: result

Round 1 below; round 2 (owner review, QUESTIONS 209) at the end, with the final verdict.

Task w3-internal, Part C (2026-10-22). Set-up in SETUP.md; numbers in result.json (the preset's study) and
result_finefamily.json (the finer study), the bottom-wall Cf and Cp per level in wall_<level>[_finefamily].csv, the
plot cf_cp.png; `scripts/validation/bfs_study.py`. Every level ran through the app's Mesh Study (StudyRun), two
turbulence stages (D-126), and stopped on its mean-stable criteria at iteration 4004 (stage 2 from 2002). Run's own
U_ref 0.9987-0.9992 m/s, Re_H 35,950-35,970 (target 36,000). Machine time: 8.6 min (first study) + 38.3 min (finer
study) + about 3 min (two mesh-only trials and a study stopped to set TMR's inflow turbulence).

## Mesh study

Two app studies of ratio sqrt(2): the "2D internal flow" preset's (D-128 placed the preset's mesh as the coarse level)
and a finer family whose current settings are 160,000 background cells as the medium level; the finer family's coarse
level is the preset family's fine level (the same 122,214-cell mesh, to the cell). h = (area / cells)^(1/2), so the
layer cells make the h ratios 1.26-1.35 instead of 1.414.

| Family, level | Surface cell | Cells | h | Layers lower / step / floor / upper | First cell over 2x plan | x_r / H | vs exp (6.26) | vs TMR SST (6.50) |
|---|---|---|---|---|---|---|---|---|
| preset, coarse | 0.258 H | 46,120 | 0.170 | 21 / 21 / 21 / 21 | 0.0 % | 7.292 | +16.5 % | +12.2 % |
| preset, medium | 0.182 H | 73,379 | 0.135 | 19 / 19 / 19 / 19 | 0.0 % | 6.892 | +10.1 % | +6.0 % |
| preset, fine = finer, coarse | 0.129 H | 122,214 | 0.104 | 17 / 8.5 / 16.8 / 17 | 0.39 % | 6.481 | +3.5 % | -0.3 % |
| finer, medium | 0.091 H | 213,155 | 0.079 | 14.9 / 10.3 / 15 / 15 | 0.21 % | 5.629 | -10.1 % | -13.4 % |
| finer, fine | 0.064 H | 389,904 | 0.058 | 14 / 14 / 14 / 14 | 0.0 % | **6.438** | **+2.8 %** | **-1.0 %** |

No level's layers collapsed (I5): every wall keeps its full stack except the 1 H step face and up to 1.5 % of the floor
next to it; the walked first cell is above twice the plan on at most 0.39 % of the wall area.

GCI of x_r (Celik et al. 2008, `foam/gci.py`): the preset family converges monotonically but at an apparent order of
0.27 (GCI 109 %: x_r falls by 0.40 H per level, not in the asymptotic range); the finer family is **oscillatory**
(6.48, 5.63, 6.44): no GCI. Over the five levels x_r is 7.29, 6.89, 6.48, 5.63, 6.44 H: grid convergence is not
established. The outlier, the finer family's medium level, is the one with a partial stack on the step face (10.3 of
15 layers); whether the step's layers move the corner bubble and the shear layer's origin enough to shorten the main
bubble is not established.

Upstream boundary layer at x/H = -4: delta_99 = 1.37 H (preset fine) and 1.32 H (finer medium) against TMR's
"approximately 1.5H"; Cf 0.00274-0.00278 against the experiment's 0.00288 (+- 0.00020).

## Bottom wall: Cf and Cp (finest level, 0.064 H)

Cf = -tau_x / (0.5 U_ref^2), Cp = (p - p(x/H = 40)) / (0.5 rho U_ref^2) (the experiment's shift). TMR's SST curves are
published only as plots (backstep_val_sst.html): the SST values below are read from cf_sst-CF.jpg and cp_sst-CF.jpg by
eye (about +- 0.0001 in Cf, +- 0.005 in Cp, +- 0.3 in x/H).

| Feature | This run | TMR SST (CFL3D, FUN3D; plot) | Experiment (data files) |
|---|---|---|---|
| Cf at x/H = -4 | 0.00275 | about 0.0029-0.0030 | 0.00288 |
| Cf = 0 (reattachment) | 6.44 | 6.50 (page text) | 6.26 +- 0.10 |
| Cf minimum, location | -0.00144 at 3.5 | about -0.00145 at 3.8 | -0.00102 at 3.8 (lowest point) |
| Cf at x/H = 20 | 0.00171 | about 0.0018 | 0.00202 |
| Cp minimum, location | -0.232 at 2.0 | about -0.205 at 2.5 | -0.190 at 3.0 |
| Cp peak, location | 0.020 at 9.8 | about 0.027 at 9.5 | 0.039 at 9.0 |

Qualitatively the run reproduces the SST curves of the TMR codes: the small corner bubble at the step (Cf changes sign
near x/H = 0.8-1.2 on every level), a main bubble whose Cf minimum (-0.00144) matches SST's and is deeper than
the experiment's, as SST's is, reattachment within 1 % of SST's, and a recovery that stays below the experiment
(Cf 0.0017 at x/H = 20 against SST's 0.0018 and the experiment's 0.0020). The pressure differs more: the Cp minimum is
0.03 deeper and 0.5 H closer to the step than SST's and the recovery peak 0.007 lower, so the run's bubble is a little
more concentrated; the experiment's recovery peak (0.039) is above both. The per-level CSVs and cf_cp.png show the
same features on every level; their sizes do not change monotonically with refinement (the Cp peak 0.011, 0.009,
0.016, 0.024, 0.020 from the coarsest level).

Deviations from TMR (SETUP.md): the inflow at x/H = -110 with a uniform velocity (no symmetry strip: the app has no
such role), incompressible; the incoming boundary layer about 10 % thinner than TMR's.

## Verdict (round 1)

**PASS** (I5: the reattachment within 10 % of the experiment) on the finest level, x_r = 6.44 H (+2.8 % against
Driver & Seegmiller, -1.0 % against the TMR SST codes), with a note: grid convergence is not established. The five
levels scatter between 5.63 and 7.29 H, the three finest between 5.63 and 6.48 H (-10 % to +3.5 % against the
experiment), and neither study gives a GCI (order 0.27, then oscillatory). The Cf and Cp shapes agree with the TMR SST
plots in every feature listed above within their reading accuracy, except the Cp minimum and peak (0.03 and 0.007
off). Open: QUESTIONS 209.

## Round 2 (QUESTIONS 209, owner review)

Task w3-internal, owner review of W3 (2026-10-22), item 2; result_round2.json, wall_<level>_round2.csv, cf_cp.png
(the round 2 curves added). Machine time 69 min (two calibration runs 16 min, the study 52.9 min).

(a) Incoming boundary layer. TMR adjusts "the inflow length prior to the area of interest" so that the lower wall's
naturally developing boundary layer is "approximately 1.5H" before the step (backstep_val.html; U_ref and the
boundary layer at x/H = -4). Here the walls start at the inlet, which was moved upstream: delta_99 at x/H = -4 (the
height where Ux reaches 0.99 of the centre-channel value at z/H = 5, linear between cell centres;
`bfs_study.boundary_layer`) on single meshes of 0.129 H surface cells:

| Inlet (walls from) | delta_99 / H at x/H = -4 | Cf at x/H = -3.956 | U_ref (m/s) | x_r / H |
|---|---|---|---|---|
| -123 H | 1.423 | 0.00270 | 1.0039 | 6.467 |
| **-131 H** (used) | **1.501** | 0.00268 | 1.0069 | 6.468 |

(Round 1's inlet at -110 H gave about 1.32-1.37 H, measured without the interpolation.) Re_H on the run's own U_ref is
36,240-36,260 (+0.7 % against 36,000; the inlet speed was kept at 0.95 m/s). The experiment's Cf at x/H = -3.956 is
0.00288 +- 0.00020: the run's 0.00268 is 7 % lower, at the lower edge of the experiment's error band (0.00268-0.00308); TMR says its inflow
length gives "approximately the correct thickness and ... approximately the correct wall skin friction"; matching the
thickness, as the owner asked, leaves Cf 7 % low.

(b, c) The finer family again (`bfs_study.py --family round2`: the medium level's base cell 0.09117 H set explicitly so
the levels keep round 1's cells): every level stopped on its mean-stable criteria at iteration 4004. Layers from the
mesh walk: per wall the mean count, the share of the target kept and the area share of faces with the full count; a
level with an incomplete stack on any wall does not count (I5).

| Level | Surface cell | Cells | h | Target layers | Step face: mean / kept / faces full | Other walls | Valid | x_r / H | vs exp (6.26) | vs TMR SST (6.50) |
|---|---|---|---|---|---|---|---|---|---|---|
| coarse | 0.129 H | 138,024 | 0.1042 | 17 | 17.0 / 100 % / 100 % | complete | **yes** | 6.468 | +3.3 % | -0.5 % |
| medium | 0.091 H | 240,295 | 0.0790 | 15 | 10.3 / 68.8 % / 36.3 % | lower 99.4 % full | **no** | 5.637 | -10.0 % | -13.3 % |
| fine | 0.064 H | 439,456 | 0.0584 | 14 | 14.0 / 100 % / 100 % | complete | **yes** | **6.434** | **+2.8 %** | **-1.0 %** |

The medium level is again the outlier and again the level whose step face kept only part of its stack (round 1's
finer medium: 10.3 of 15, the same); round 1's coarse level of this size had 8.5 of 17 on the step and 6.48 H, round
2's has the full stack and 6.47 H.

(d) GCI (Celik et al. 2008 with the levels' own ratios, `foam/gci.study`, which takes r21 and r32 from h): it needs
three valid levels; with two (coarse and fine) there is none. The two valid levels differ by 0.5 % (6.468, 6.434;
h ratio 1.78).

Bottom wall on the fine level (the SST values read from TMR's plots as in round 1): Cf minimum -0.00140 at 3.5 (SST
about -0.00145 at 3.8), Cf at x/H = 20 0.00165 (SST about 0.0018, experiment 0.00202), Cp minimum -0.227 at 2.0 (SST
about -0.205 at 2.5), Cp peak 0.018 at 9.8 (SST about 0.027 at 9.5). The shapes are round 1's; matching the
boundary layer moved the fine level's x_r by -0.004 H.

## Verdict (round 2, final)

**PASS WITH NOTE.** The finest valid level reattaches at 6.43 H, +2.8 % against Driver & Seegmiller (within the 10 %
of I5) and -1.0 % against the TMR SST codes, but the owner's PASS also needs the valid levels to converge, and that is
not shown: only two of the three levels are valid (the medium level's step face kept 69 % of its layers), so there is
no GCI; the two valid levels agree within 0.5 %. Left open: a complete stack on the step face at every level (the
cause of the outlier).

## Round 3: the step face's layers (QUESTIONS 209, task w3-close)

Task w3-close, item 2 (2026-10-22); result_round3.json, wall_medium_round3.csv (the coarse and fine levels are round
2's solutions: their meshes are unchanged, below, so wall_coarse_round2.csv and wall_fine_round2.csv stand).
`bfs_study.py --family round2 study --level medium`, then `collect --family round3`. Machine time: diagnosis and
mesh checks about 9 min (eight 2D meshes of 30-90 s, two NACA meshes of 3-4 min), the medium level 12.1 min (8 ranks).

Cause (D-135): in the layer phase's first iteration snappyHexMesh's face-weight check (minFaceWeight 0.05, the main
meshQualityControls value; D-122's relaxed set does not touch it) finds 3 faces below 0.05 and removes the extrusion at
2 wall faces, the step face's top face and the lower wall's last face, both at the step's **top (convex) corner**.
There snapping left a sliver lower-wall face 6.3 mm long (0.07 of the 91 mm cell) beside a 146 mm one, and the first
layer cells in the fan around the corner have faces with weights 0.042-0.050. The count then tapers from the corner:
the step face has 15 layers from its foot to z = 0.32 H, then 14, 12, 10, 8, 6, 4 and 0 at the top face; the lower
wall 0 over its last 0.2 H. It is the medium level's background grid against the corner (the preset's surface level
is the base cell, so the surface level acts only through the grid): the coarse and fine levels have no sliver there
(minimum weights 0.095 and 0.109); a 30 mm shift of the medium grid removes this sliver but puts 8 other faces below
0.05 and costs the floor 1.6 % of its full faces. Not the corner feature edge as such, and not one of D-122's
settings, but a check D-122 left at its default.

Fix (D-135, [NUMERICS-REVIEW]): minFaceWeight 0.02 in the wall-resolved layer phase's relaxed set. Checks:

| Level | Mesh against round 2 | Cells | Step face: mean / kept / faces full | Other walls | checkMesh |
|---|---|---|---|---|---|
| coarse (0.129 H) | geometrically identical (sorted points 0.0 m apart) | 138,024 | 17.0 / 100 % / 100 % | complete | OK |
| medium (0.091 H) | changed: the corner keeps its stack | 240,423 (240,295) | 15.0 / 100 % / 100 % (10.3 / 68.8 / 36.3) | complete (lower 99.4 % full before) | OK, max skewness 3.23 (3.23) |
| fine (0.064 H) | geometrically identical | 439,456 | 14.0 / 100 % / 100 % | complete | OK |

The NACA 0012 round 3 15 deg mesh (wall-resolved, the other user of the set) is identical with and without the fix;
the public benchmark (robust controls) has byte-identical dictionaries (51 files) and `--compare` (mesh only) gives
"no regressions" (every mesh metric equal to the baseline).

Three valid levels (stopped on their mean-stable criteria at iteration 4004; U_ref 1.0067-1.0071 m/s, Re_H
36,240-36,260):

| Level | h | Cells | x_r / H | vs exp (6.26) | vs TMR SST (6.50) | Cf(x/H = -3.956) |
|---|---|---|---|---|---|---|
| coarse | 0.1042 | 138,024 | 6.468 | +3.3 % | -0.5 % | 0.00268 |
| medium | 0.0789 | 240,423 | **6.227** (round 2: 5.637) | -0.5 % | -4.2 % | 0.00270 |
| fine | 0.0584 | 439,456 | **6.434** | **+2.8 %** | **-1.0 %** | 0.00268 |

GCI (Celik et al. 2008 with the levels' own ratios, `foam/gci.study`: r21 = 1.352, r32 = 1.320): e21 = +0.207 H,
e32 = -0.241 H, opposite signs: **oscillatory, GCI not applicable**. The three valid levels lie within 0.24 H of each
other (6.23-6.47 H, a band of 3.9 % of the experiment's value), all within 3.5 % of the experiment. The medium level's
bottom wall: Cf minimum -0.00127 at 3.5, Cf at x/H = 20 0.00166, Cp minimum -0.205 at 2.0, Cp peak 0.018 at 9.7 (the
corner bubble's sign change at 1.08). The complete stack moved the medium level's x_r by +0.59 H, so the step face's
layers did cause round 1 and 2's outlier.

### Verdict (round 3, final)

**PASS WITH NOTE** (I5: PASS needs the valid levels to converge and the finest within 10 % of 6.26). The finest level
is +2.8 % (-1.0 % against TMR SST) and all three levels are now valid, but they oscillate (6.47, 6.23, 6.43 H), so
grid convergence is not shown and there is no GCI; the oscillation band (0.24 H, 3.9 %) is the best available
estimate of the discretisation uncertainty. By the owner's closure rule W3 closes with this note.
