# Ahmed body, 25 degree slant, in ground proximity: result

Set-up and sources: [SETUP.md](SETUP.md). Numbers: [result.json](result.json) (written by
`scripts/validation/ahmed_study.py collect` from the git-ignored cases in run/validation/ahmed/). Run on
2026-10-21, task validation-ahmed, three levels through the app's mesh study (D-066, D-117), meshing on 8
cores, simpleFoam on 4, nice -n 15.

Round 2 (the set-up fixed after the owner's review): [below](#round-2); also **FAIL**, fine-grid body
Cd 0.3246 (+13.9 %). Re-verdict with the references read after round 2: still **FAIL**
([Re-verdict](#re-verdict-with-the-verified-references)); the reading: [Reading of round 2](#reading-of-round-2).

**Verdict (round 1): FAIL** (V6). The finest grid's body Cd is 0.3250, **14.0 % above** the experimental 0.285
(13.0 % above the alternative reading 0.2875): inside the 10-20 % band, but above every published
k-omega SST result found (0.284 to 0.313), so the PASS WITH NOTE condition is not met. The grid study is
oscillatory (no GCI, no extrapolation) and the fine level is 6.3 % below the medium one, so the result is
not grid-converged; and no level met the app's stopping criteria (the steady solution oscillates about a
stationary mean, QUESTIONS 170).

## Per level

Values are the means over the last 1000 of 1500 iterations (SETUP.md, "Solver and stopping criteria");
the standard deviation over the same iterations is in brackets. A_ref = half the body's frontal area,
so the coefficients are those of the full body.

| | coarse | medium | fine |
|---|---|---|---|
| Size factor (linear) | 2 | 1.414 | 1 |
| Cells (checkMesh) | 202,717 | 524,785 | 1,338,191 |
| h = (V / N)^(1/3) | 0.12416 m | 0.09042 m | 0.06619 m |
| checkMesh | OK, 0 failed checks | OK, 0 | OK, 0 |
| Max non-orthogonality / skewness | 73.5 / 2.38 | 64.8 / 3.23 | 65.0 / 2.39 |
| Body y+ mean (area-weighted) | 87.6 | 57.6 | 55.2 |
| Body area with y+ in [25, 100] | 56.0 % | 90.1 % | 91.7 % |
| Layers, body (mesh layers of 9 / thickness) | 6.33 / 79.0 % | 7.65 / 86.9 % | 8.05 / 90.1 % |
| Layers, stilts front / rear (thickness) | 16.8 / 9.0 % | 9.8 / 7.3 % | 18.4 / 16.4 % |
| Faces extruded (all walls) | 69.4 % | 88.8 % | 90.2 % |
| Ground y+ mean, under the body / whole ground | 1,707 / 10,782 | 1,240 / 7,656 | 1,518 / 5,438 |
| Iterations, end state | 1500, iteration limit | 1500, iteration limit | 1500, iteration limit |
| Stopping criteria met | no | no | no |
| **Cd body** | **0.3409** (0.0065) | **0.3468** (0.0046) | **0.3250** (0.0016) |
| Cd body: pressure / viscous | 0.2972 / 0.0437 | 0.3023 / 0.0446 | 0.2791 / 0.0459 |
| Pressure share of the body's drag | 87.2 % | 87.1 % | 85.9 % |
| Cd stilts (front + rear) | 0.0235 + 0.0113 | 0.0217 + 0.0134 | 0.0196 + 0.0107 |
| **Cd body + stilts** | **0.3756** | **0.3819** | **0.3553** |
| Cl body (pressure / viscous) | 0.341 (0.034) / 0.0009 | 0.395 (0.044) / 0.0006 | 0.382 (0.040) / 0.0005 |
| Cl body + stilts | 0.341 | 0.394 | 0.381 |
| Body Cd at the last iteration (the study's own value) | 0.3441 | 0.3435 | 0.3227 |
| Meshing / solver time | 56 s / 535 s | 60 s / 1654 s | 167 s / 4564 s |

The y+ band is the benchmark's [0.5, 2] x target (D-107). The body's mean y+ reaches the target of 50
on the medium and fine levels; the coarse level's thinner stack (the shared 9-layer stack of D-066 under
cells twice as large) puts it at 88. The stilts' layers collapse at both ends (QUESTIONS 174). The ground
has no layers (D-116 default): its y+ under the body is 1,200-1,700, far above the wall-function range,
so the ground boundary layer is not resolved (QUESTIONS 168 c). The parts' forces add up to all walls
(body + stilts = Cd within 2e-6 on every level; the ground is in no force object).

## Grid convergence (Celik 2008, foam/gci.py)

| Quantity | coarse | medium | fine | Convergence | p | Extrapolated | GCI fine | Asymptotic |
|---|---|---|---|---|---|---|---|---|
| Cd body (means) | 0.34090 | 0.34684 | 0.32497 | oscillatory | - | - | - | - |
| Cd body + stilts (means) | 0.37560 | 0.38193 | 0.35525 | oscillatory | - | - | - | - |
| Cl body (means) | 0.34129 | 0.39456 | 0.38153 | oscillatory | - | - | - | - |
| Cd body, pressure (means) | 0.29723 | 0.30225 | 0.27910 | oscillatory | - | - | - | - |
| Cd body, viscous (means) | 0.04366 | 0.04459 | 0.04587 | divergent | - | - | - | - |
| Cd body (last iteration, the study's table) | 0.34411 | 0.34346 | 0.32267 | divergent | - | - | - | - |

No apparent order, no extrapolated value and no GCI: the changes have opposite signs (+1.7 % coarse to
medium, -6.3 % medium to fine), so the three grids are not in the asymptotic range. The coarse-to-medium
change is of the order of the uncertainty of a 1000-iteration mean (standard deviation 0.005-0.007 with
a period of about 167 iterations: about six periods per mean); the medium-to-fine drop is not, and
coincides with the change of the slant flow below. The judged value is therefore the finest grid's
(V6). The actual size ratios are 1.373 and 1.366 (V/N with the measured cells), inside the 1.3-1.5 asked.

## Against the experiment and the literature

| Source | Method | Cd | Error vs 0.285 |
|---|---|---|---|
| Ahmed et al. (1984), Fig. 4, as quoted (SETUP.md) | experiment, 60 m/s, stilt tare removed | 0.285 (0.2875 as read by SimScale) | - |
| This study, fine grid, body | k-omega SST, wall functions, 1.34 M cells (half model) | 0.3250 | **+14.0 %** (+13.0 % vs 0.2875) |
| This study, fine grid, body + stilts | same | 0.3553 | +24.7 % (not comparable: the experiment removed the stilts) |
| Hachimy, Omar, Elsayed (2022) [H22] | k-omega SST, ANSYS Fluent | 0.2839 | -0.4 % |
| SimScale validation case [SS] | k-omega SST, wall functions, stationary no-slip floor, stilts excluded from the forces, 6.9 M cells | 0.2915 | +2.3 % |
| SimFlow validation case [SF] | k-omega SST, simpleFoam (OpenFOAM), wall functions, 40 m/s, 16.6 M cells | 0.313 | +9.8 % (+4.7 % vs its own reference 0.299) |

The published SST values span 0.284 to 0.313; this study's 0.325 is 3.8 % above the highest. Grid
resolution is the most likely gap: the published cases use 5 to 12 times more cells (as full or half
models), and this study's own fine level is still moving (-6.3 %). With the oscillatory study there is no
grid uncertainty to put on the fine value, so it is compared as it is (QUESTIONS 172 on the sources).

Cl: [A84] reports no lift. For orientation only, [SF] quotes 0.345 from the Graz experiment of Meile
et al. (2011, 40 m/s); this study's 0.38 (with a 0.04 oscillation) is in the same range. The SST lift is
known to depend strongly on the slant separation (the next section).

Pressure / viscous split: [A84] reports 85 % of the body drag as pressure drag ("almost 85 % of body
drag is pressure drag"; Table 2: 76 % at 12.5 degrees, 85 % at 30 degrees, high drag); this study gives
85.9 % on the fine grid (friction 14.1 %, at the low end of [A84]'s 15-24 %).

## The slant flow

From the wall shear stress at the last iteration: the skin friction along the downslope direction
(cos 25, 0, -sin 25), negative where the near-wall flow runs up the slant (reversed).

| | coarse | medium | fine |
|---|---|---|---|
| Slant area with reversed flow | 30.8 % | 26.5 % | 7.8 % |
| Centre strip (within 30 mm of the plane of symmetry) reversed | 89.8 % | 87.9 % | 51.4 % |
| Reversed along the centre strip, from / to (fraction of the slant length) | 0.11 / 0.98 | 0.07 / 0.94 | 0.07 / 0.80 |

Experiment ([A84], section 3): below the critical angle of 30 degrees the flow on the slant is the
low-drag regime: a separation region on the middle of the slant "is already initiated at still lower
values" of the slant angle (oil flow, Fig. 11), the side-edge vortices keep the flow on the slant's
flanks attached, and configurations "slightly less than 30 degrees" show the three separate vortices A,
B and E of a separation bubble that closes on the slant; the fully separated slant appears only above
30 degrees. The fine grid reproduces that pattern qualitatively: a bubble from 7 % of the slant length,
reattached at 80 %, attached flanks (only 7.8 % of the slant reversed). The coarse and medium grids
separate the centre almost down to the base (to 98 % and 94 %), the over-predicted separation reported
for RANS models at this angle (Guilmineau 2008, known from secondary sources only), which raises the
base and slant pressure drag; this is where the medium-to-fine drop of Cd comes from. The bubble's
length in the experiment is not taken from [LB03] here (not read); only the state is compared.

## Machine time (V7)

| Item | Time |
|---|---|
| Trials before the study (one mesh at the coarse sizes, 100 + 1500 solver iterations) | about 12 min |
| Mesh study (three levels, meshing and solving) | 123 min (7,401 s) |
| Result collection | 2 min |
| **Total** | **about 2 h 17 min** (limit 4 h) |

## References

[A84], [LB03], [ERC]: SETUP.md.

- **[H22]** F. Hachimy, A. A. Omar, O. Elsayed, "The accuracy of the numerical solution in predicting
  Ahmed body components drag coefficients", CFD Letters 14(5) (2022) 24-32,
  https://semarakilmu.com.my/journals/index.php/CFD_Letters/article/download/594/575/4808. The SST
  value is from a search engine's extract of the full text; the article returned HTTP 403 when fetched
  (QUESTIONS 172).
- **[SS]** SimScale, "Aerodynamics: Flow around the Ahmed Body" (validation case, updated 2025-08-29),
  https://www.simscale.com/docs/validation-cases/aerodynamics-flow-around-the-ahmed-body/ (read
  2026-10-21): k-omega SST, 60 m/s, three meshes, Cd 0.2985 / 0.2915 / 0.2835 (3.7, 6.9 and 10.1 M
  cells), the chosen mesh 0.2915; the experimental 0.2875 read from [A84] Fig. 4.
- **[SF]** SimFlow, "Flow around the Ahmed Body - Validation Case", https://help.sim-flow.com/validation/ahmed-body
  (read 2026-10-21): simpleFoam, k-omega SST with wall functions, 40 m/s, Re 2.784e6, Cd 0.313 and
  Cl 0.355 against Meile et al. (2011) 0.299; "the flow remains attached over the slant".
- **[G08]** E. Guilmineau, "Computational study of flow around a simplified car body", J. Wind Eng. Ind.
  Aerodyn. 96 (2008) 1207-1217, doi:10.1016/j.jweia.2007.06.041. Not read for round 1 (cited then from
  secondary sources); read from the owner's copy after round 2 (SETUP.md, [G08]; the re-verdict above).
- I. B. Celik, U. Ghia, P. J. Roache, C. J. Freitas, H. Coleman, P. E. Raad, "Procedure for estimation and
  reporting of uncertainty due to discretization in CFD applications", J. Fluids Eng. 130 (2008) 078001.

## Round 2

Set-up: SETUP.md, "Round 2" (inlet 5 L ahead with a slip strip to the ground wall 1.35 L ahead of the
nose, D-118; prism layers on the ground wall; the mean-stable criterion on the body Cd, W 500, tol 0.5 %,
with the 1500-iteration cap; round 1's level sizes; meshing and solver on 8 cores). Run on 2026-10-21:
coarse and medium 20:46-21:17, fine 21:26-22:36, nice -n 15. Numbers: [result_round2.json](result_round2.json)
(`--round 2 collect`). Values are means over the last 500 iterations at the stop (the criterion's
window), standard deviation over the same iterations in brackets.

**Verdict: FAIL** (V6), as round 1. The fine grid's body Cd is 0.3246, **13.9 % above** the experimental
0.285 (12.9 % above 0.2875): inside the 10-20 % band but 3.7 % above the highest published k-omega SST
value (0.313), so the PASS WITH NOTE condition is not met. The grid study is oscillatory again (no GCI, no
extrapolation). Unlike round 1, the medium and fine levels agree within the oscillation (-0.8 %), and all
three levels stopped on the mean-stable criterion.

| | coarse r1 | coarse r2 | medium r1 | medium r2 | fine r1 | fine r2 |
|---|---|---|---|---|---|---|
| Cells (checkMesh) | 202,717 | 245,577 | 524,785 | 627,219 | 1,338,191 | 1,614,529 |
| h = (V / N)^(1/3) | 0.12416 m | 0.12697 m | 0.09042 m | 0.09289 m | 0.06619 m | 0.06778 m |
| checkMesh / max non-orth. / skewness | OK / 73.5 / 2.38 | OK / 79.1 / 1.95 | OK / 64.8 / 3.23 | OK / 81.3 / 3.09 | OK / 65.0 / 2.39 | OK / 76.3 / 1.67 |
| Ground layers (of 9) / thickness | none | 2.08 / 25.7 % | none | 2.68 / 28.8 % | none | 2.93 / 30.8 % |
| **Ground y+ mean under the body** (whole ground) | 1,707 (10,782) | **316** (10,696) | 1,240 (7,656) | **602** (7,558) | 1,518 (5,438) | **366** (5,331) |
| Body y+ mean / in [25, 100] | 87.6 / 56.0 % | 66.4 / 90.5 % | 57.6 / 90.1 % | 58.1 / 89.3 % | 55.2 / 91.7 % | 56.1 / 89.7 % |
| End state | 1500, iteration limit | **criteria met** (mean stable), 1164 | 1500, iteration limit | **criteria met** (mean stable), 1006 | 1500, iteration limit | **criteria met** (mean stable), 1021 |
| **Cd body** (mean) | 0.3409 (0.0065) | **0.3003** (0.0049) | 0.3468 (0.0046) | **0.3272** (0.0104) | 0.3250 (0.0016) | **0.3246** (0.0067) |
| Cd body: pressure / viscous | 0.2972 / 0.0437 | 0.2576 / 0.0427 | 0.3023 / 0.0446 | 0.2854 / 0.0418 | 0.2791 / 0.0459 | 0.2811 / 0.0435 |
| Pressure share of the body's drag | 87.2 % | 85.8 % | 87.1 % | 87.2 % | 85.9 % | 86.6 % |
| Cd stilts (front + rear) | 0.0235 + 0.0113 | 0.0196 + 0.0105 | 0.0217 + 0.0134 | 0.0195 + 0.0121 | 0.0196 + 0.0107 | 0.0179 + 0.0109 |
| **Cd body + stilts** (all walls, mean) | 0.3756 | **0.3305** | 0.3819 | **0.3589** | 0.3553 | **0.3534** |
| Cl body (mean) | 0.341 (0.034) | 0.348 (0.018) | 0.395 (0.044) | 0.270 (0.061) | 0.382 (0.040) | 0.395 (0.055) |
| Slant reversed area / centre strip reversed | 30.8 % / 89.8 % | 23.2 % / 96.0 % | 26.5 % / 87.9 % | 37.2 % / 95.7 % | 7.8 % / 51.4 % | 40.4 % / 67.9 % |
| Centre strip reversed from / to (slant length) | 0.11 / 0.98 | 0.08 / 0.98 | 0.07 / 0.94 | 0.05 / 0.98 | 0.07 / 0.80 | 0.06 / 0.96 |
| Meshing / solver time | 56 s / 535 s (4 cores) | 87 s / 400 s (8 cores) | 60 s / 1654 s (4 cores) | 187 s / 1128 s (8 cores) | 167 s / 4564 s (4 cores) | 560 s / 3578 s (8 cores) |

Round 1 judged the means over iterations 501-1500 (1000 iterations); round 2 the 500 before the stop. On
round 1's own histories the two differ by at most 0.21 % (D-118), far less than the changes below.

### Re-verdict with the verified references

The owner supplied three PDFs after round 2; only Guilmineau (2008) [G08] is the paper expected. The
files named for Ahmed et al. (1984) and Lienhart & Becker (2003) hold other papers (SETUP.md, "Reference
files supplied"), so [A84] Fig. 4 and [LB03] are still not read.

| Source | Near-wall treatment | Cd (25 degrees, body) | Error vs 0.285 | This study's fine level against it |
|---|---|---|---|---|
| Ahmed et al. (1984), as quoted (also by [G08] Table 1, p. 1212) | experiment, 60 m/s | 0.285 | - | +13.9 % |
| [SS] SimScale, k-omega SST | wall functions | 0.2915 | +2.3 % | +11.4 % |
| **[G08] Guilmineau 2008, k-omega SST, steady (Table 1, p. 1212)** | **wall-resolved, low-Re, y+ about 0.25 (p. 1212)** | **0.3074** | **+7.9 %** | **+5.6 %** |
| [SF] SimFlow, simpleFoam k-omega SST | wall functions | 0.313 | +9.8 % | +3.7 % |
| This study, round 2, fine | wall functions, body y+ 56 | 0.3246 | +13.9 % | - |

**Verdict (verified references): FAIL** (V6). The fine level's error (+13.9 %) is inside the 10-20 % band,
but the value lies above the published SST range 0.2915-0.313 (3.7 % above its top), so the PASS WITH
NOTE condition is not met. Hachimy et al. (2022) (0.2839) is no longer in the range: its full text was
never read. The verdict is not decided by the unverified values: the highest of the range, SimFlow's, is
a vendor page, and the one peer-reviewed SST result is 5.6 % below this study. The experimental 0.285 is
still second hand (QUESTIONS 171).

Of the three SST results, the one wall-resolved ([G08]) is not the closest to the experiment: the two
wall-function results lie on either side of it. So the owner's expectation that the literature values used
wall-resolved meshes holds for [G08] only, and wall functions alone do not explain why this study is
higher. [G08] also differs in speed (40 m/s, Re_L 2.78e6, p. 1208, against [A84]'s 60 m/s used here), domain
(2 L ahead, 3 L behind, 1.4 m high, p. 1212) and code (ISIS-CFD, 10,000 steady iterations, p. 1212).

**The slant flow against the experiment.** [LB03] itself is not read; its 25 degree slant is known only
from [G08]'s description: separation along the middle of the slant's top edge, two strong side-edge
vortices, and reattachment "about half-way down the center of the face" (p. 1214, Fig. 7; p. 1217). This
study's fine level separates at the slant's leading edge and reattaches at 0.7 of the slant length on the
centre line and 0.6-0.7 further out, with the outer 35 mm of the half span attached and 40 % of the slant
area reversed (below, "The slant flow on the fine level"). Along the centre line the bubble is therefore
**longer than described** (reattachment at 0.6-0.7 against about 0.5); its width and area cannot be
compared without [LB03]'s data. [G08]'s SST separates massively with no reattachment and a too-weak side
vortex (p. 1215, Fig. 9 b; p. 1216, Fig. 10 b), a larger bubble than this study's, yet a lower Cd (0.3074).
Within this study, round 1's fine level had a much smaller bubble (7.8 % of the slant) and the same Cd
(0.3250). In neither comparison does a larger slant bubble go with more drag, so the drag excess cannot
be attributed to the bubble's size from these data; where on the body the extra drag sits (slant, base or
fore body) is not established.

### Reading of round 2

The owner's review of round 2 (2026-10-21) records it as **FAIL** under V6; with the references read
after it (above):

- The medium and fine levels agree within 0.8 % (0.3272 and 0.3246), so the grid uncertainty is small,
  although no GCI can be computed (the three levels are oscillatory).
- Steady k-omega SST with wall functions gives a body Cd of 0.325 (+14 %) on this case.
- The remaining error is not the set-up: the set-up fixes of round 2 moved the fine level by -0.1 %.
- The one peer-reviewed SST result read, [G08] (steady, wall-resolved), also over-predicts the drag
  (0.3074, +7.9 %) with a different slant flow (no reattachment). This study is 5.6 % above it and 3.7 %
  above the highest vendor result (wall functions). What causes the remaining gap is not established:
  near-wall treatment, Reynolds number (60 against 40 m/s), domain and numerics all differ, and the slant
  bubble's size does not track the drag in the results compared.
- This study's slant bubble reattaches later on the centre line than the experiment as described by
  [G08] (0.6-0.7 against about half-way); [LB03]'s own data are still needed to compare its width, its
  area and the side vortices (QUESTIONS 171).
- FAIL stands. It no longer rests on the unverified Hachimy et al. value; the experimental Cd and its
  reading uncertainty are still second hand until [A84] is supplied.

### Grid convergence (Celik 2008, foam/gci.py)

| Quantity (round 2 means) | coarse | medium | fine | Convergence |
|---|---|---|---|---|
| Cd body | 0.30032 | 0.32723 | 0.32456 | oscillatory |
| Cd body + stilts | 0.33046 | 0.35886 | 0.35341 | oscillatory |
| Cl body | 0.34790 | 0.26949 | 0.39503 | oscillatory |
| Cd body, pressure | 0.25759 | 0.28540 | 0.28105 | oscillatory |
| Cd body, viscous | 0.04273 | 0.04183 | 0.04351 | oscillatory |

**No GCI can be computed:** the changes have opposite signs (+9.0 % coarse to medium, -0.8 % medium to
fine), so there is no apparent order and no extrapolated value; every quantity is oscillatory (the stilts'
Cd: front divergent, rear oscillatory). The medium-to-fine change (-0.0027) is smaller than the standard
deviation of either level over its window (0.0104 and 0.0067; the oscillation period is about 167
iterations, so a 500-iteration mean holds three periods), so medium and fine agree within the uncertainty
of the windowed mean; the coarse level is the outlier (its ground y+ and its body layers differ most, the
table above). Two grids within the noise do not make a GCI: the judged value is the fine grid's, without a
grid uncertainty (V6). Size ratios from the measured cells: 1.367 and 1.371.

### Against the experiment and the literature

| Source | Cd | Error vs 0.285 |
|---|---|---|
| Ahmed et al. (1984), as quoted (SETUP.md) | 0.285 (0.2875 as read by SimScale) | - |
| **This study, round 2, fine grid, body** | **0.3246** | **+13.9 %** (+12.9 % vs 0.2875) |
| This study, round 1, fine grid, body | 0.3250 | +14.0 % |
| Published k-omega SST: [H22], [SS], [SF] | 0.2839, 0.2915, 0.313 | -0.4 %, +2.3 %, +9.8 % |

The fine value is 0.0116 (3.7 %) above the highest published SST result (SimFlow's simpleFoam case,
16.6 M cells), and 0.033 and 0.041 above the other two. The references are still unverified (no papers supplied;
QUESTIONS 171, 172).

### The slant flow on the fine level

The fine level now shows a **closed separation bubble on the slant's centre, larger than round 1's**.
Reversed share of the slant faces per tenth of the slant length (wall shear stress at the last
iteration, 1021), by distance y from the plane of symmetry (the half width is 0.1945 m):

| y | 0-0.1 | 0.1-0.2 | 0.2-0.3 | 0.3-0.4 | 0.4-0.5 | 0.5-0.6 | 0.6-0.7 | 0.7-0.8 | 0.8-0.9 | 0.9-1 |
|---|---|---|---|---|---|---|---|---|---|---|
| 0-0.03 m | 50 | 50 | 92 | 100 | 100 | 100 | 100 | 46 | 17 | 17 |
| 0.03-0.10 m | 50 | 93 | 100 | 100 | 100 | 100 | 30 | 0 | 0 | 0 |
| 0.10-0.16 m | 40 | 81 | 77 | 33 | 25 | 23 | 23 | 4 | 0 | 0 |
| 0.16-0.20 m | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| round 1 fine, 0-0.03 m (1500) | 23 | 100 | 100 | 100 | 88 | 58 | 38 | 17 | 4 | 0 |
| round 1 fine, 0.03-0.20 m | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

The near-wall flow separates at the slant's leading edge, runs up the slant over the first 60-70 % of its
length on the inner half of the span and reattaches before the base (from 0.7 at the centre, 0.6-0.7
further out); the outer 35 mm (under the side-edge vortices) stays attached everywhere. That is the
low-drag regime of [A84] below 30 degrees (a bubble closing on the slant, attached flanks), the same
state as round 1's fine level, but the bubble covers most of the inner span (40 % of the slant area,
round 1: 7.8 %, only the centre strip). Coarse and medium r2 separate to the base (to 0.98 on the centre
strip). The fine level's centre "to 0.96" in the main table is a few isolated faces (17 % per tenth past
0.8), not the bubble. These are the fields at one iteration of an oscillating solution (Cl over the window
0.30 to 0.51); the bubble length moves with it. With the bubble so different from round 1's and Cd the
same (0.3246 against 0.3250), the slant regime alone does not decide the fine level's drag.

### What the set-up fixes did

The change from round 1 shrinks with refinement: -11.9 % (coarse), -5.7 % (medium), -0.1 % (fine). The
fixes moved the coarse levels toward the experiment but not the fine level, where the error stays 14 %.
Ground y+ under the body: 316 / 602 / 366 (round 1: 1,707 / 1,240 / 1,518); the ground stacks keep 2.1-2.9
of 9 layers (26-31 % of the thickness), so the medium level is still above the wall-function range there
(QUESTIONS 177).

**The separating run (QUESTIONS 177; SETUP.md, "The separating run").** Coarse level, round 2's set-up
with the ground layers off (inlet 5 L ahead and the slip strip kept), run 22:37-22:43 (63 s meshing, 322 s
solving, 8 cores). Numbers: [result_round3.json](result_round3.json).

| Coarse level | r1 | r2 without ground layers | r2 |
|---|---|---|---|
| Inlet / slip strip / ground layers | 1.35 L / no / off | 5 L / yes / off | 5 L / yes / on |
| Cells | 202,717 | 235,082 | 245,577 |
| Ground y+ mean under the body | 1,707 | 1,478 | 316 |
| Body y+ mean / in [25, 100] | 87.6 / 56.0 % | 70.9 / 79.1 % | 66.4 / 90.5 % |
| End state | 1500, iteration limit | criteria met (mean stable), 1007 | criteria met (mean stable), 1164 |
| **Cd body** (mean) | 0.3409 (0.0065) | **0.3189** (0.00001) | 0.3003 (0.0049) |
| Cd body: pressure / viscous | 0.2972 / 0.0437 | 0.2758 / 0.0430 | 0.2576 / 0.0427 |
| Cd body + stilts | 0.3756 | 0.3510 | 0.3305 |
| Cl body | 0.341 (0.034) | 0.409 (0.0002) | 0.348 (0.018) |
| Slant reversed area / centre strip reversed | 30.8 % / 89.8 % | 9.7 % / 63.3 % | 23.2 % / 96.0 % |
| Centre strip reversed from / to | 0.11 / 0.98 | 0.08 / 0.92 | 0.08 / 0.98 |

Of the coarse level's drop from 0.3409 to 0.3003 (-0.0406), the inlet and the slip strip (b) account for
-0.0220 and the ground layers (c) for -0.0186: about half each, both almost all pressure drag. That split
is only indicative: the middle run is a different flow, **steady** (Cd standard deviation 1e-5 over its
window, against 0.005-0.007 for the two others: the only steady level of either round) with a smaller
slant separation (9.7 % of the slant reversed against 23-31 %). So each fix also changes the coarse
level's slant state, and the two effects need not add. On the fine level the two fixes together change
Cd by -0.1 %. Not run: the fine level without ground layers.

**Lift.** Cl oscillates much more than Cd (standard deviation 0.018-0.061 over the window; fine 0.30 to
0.51); the windowed means (0.348 / 0.269 / 0.395) are less certain than Cd's.

**Stopping.** All three levels met the mean-stable criterion and stopped cleanly through the app: coarse
at 1164, medium 1006, fine 1021 (written iterations), 336 to 494 before the cap; the oscillation stays
(Cd standard deviation 0.005-0.010).

**Machine time and the deadline.** The fine level was started at 21:26 on the medium level's measured
rate (1.80 us per cell-iteration on 8 ranks, scaled by cells; estimated end 22:40-22:53 for 1000-1200
iterations; the driver's own estimate, round 1's 4-core rate for 1500 iterations, gave 23:25, so it was
run without `--deadline` and a separate 23:15 watcher would have sent the app's clean stop, SIGUSR1 to
mpirun, D-058). It ended by itself at 22:36:39: 9 min 20 s meshing (1,614,529 cells against 1,982,625
estimated), 3,578 s solving 1021 iterations (2.17 us per cell-iteration; round 1's fine on 4 cores:
2.27). No level was stopped at the deadline.
