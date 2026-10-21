# Ahmed body, 25 degree slant, in ground proximity: result

Set-up and sources: [SETUP.md](SETUP.md). Numbers: [result.json](result.json) (written by
`scripts/validation/ahmed_study.py collect` from the git-ignored cases in run/validation/ahmed/). Run on
2026-10-21, task validation-ahmed, three levels through the app's mesh study (D-066, D-117), meshing on 8
cores, simpleFoam on 4, nice -n 15.

**Verdict: FAIL** (V6). The finest grid's body Cd is 0.3250, **14.0 % above** the experimental 0.285
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
- E. Guilmineau, "Computational study of flow around a simplified car body", J. Wind Eng. Ind.
  Aerodyn. 96 (2008) 1207-1217, doi:10.1016/j.jweia.2007.06.041 (not read: paywalled; cited for the
  over-predicted separation at 25 degrees as reported by secondary sources).
- I. B. Celik, U. Ghia, P. J. Roache, C. J. Freitas, H. Coleman, P. E. Raad, "Procedure for estimation and
  reporting of uncertainty due to discretization in CFD applications", J. Fluids Eng. 130 (2008) 078001.
