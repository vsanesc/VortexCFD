# NASA TMR 2D backward-facing step: result

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

## Verdict

**PASS** (I5: the reattachment within 10 % of the experiment) on the finest level, x_r = 6.44 H (+2.8 % against
Driver & Seegmiller, -1.0 % against the TMR SST codes), with a note: grid convergence is not established. The five
levels scatter between 5.63 and 7.29 H, the three finest between 5.63 and 6.48 H (-10 % to +3.5 % against the
experiment), and neither study gives a GCI (order 0.27, then oscillatory). The Cf and Cp shapes agree with the TMR SST
plots in every feature listed above within their reading accuracy, except the Cp minimum and peak (0.03 and 0.007
off). Open: QUESTIONS 209.
