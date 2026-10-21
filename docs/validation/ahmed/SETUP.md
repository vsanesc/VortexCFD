# Ahmed body, 25 degree slant, in ground proximity: case set-up

Task validation-ahmed (owner decisions V1 to V7). The first force validation of the whole app
pipeline: geometry import, domain with the ground plane (D-116), meshing, the mesh-independence study
(D-066, D-117), the solver with the app's stopping criteria, the forces per part. Everything is set
through the app's own Qt-free workflow layer, as the GUI does:

- `tests/validation/ahmed_case.py`: the geometry generator (deterministic, OCP, STEP in millimetres) and
  the project set-up (`build_project`);
- `scripts/validation/ahmed_study.py setup | study | collect`: refinement volumes, surface preparation,
  study settings; the study run (`workflow/mesh_study.prepare_study`, `foam/mesh_study.StudyRun`, the
  same objects as the Mesh Study node); the numbers of `RESULT.md` into `result.json`.

The project and its cases live in `run/validation/ahmed/` (git-ignored); only numbers are committed.

## References

- **[A84]** S. R. Ahmed, G. Ramm, G. Faltin, "Some salient features of the time-averaged ground vehicle
  wake", SAE Technical Paper 840300 (1984), SAE Transactions 93(2), pp. 473-503,
  doi:10.4271/840300. Read from the scan hosted at
  https://flowvision.ru/images/articles/2020/Add_files/Ahmed_1984.pdf (JSTOR copy, text layer and
  figures 1 and 2 read on 2026-10-21; figure 4 could not be decoded, see "Experimental Cd").
- **[LB03]** H. Lienhart, S. Becker, "Flow and turbulence structure in the wake of a simplified car
  model", SAE Technical Paper 2003-01-0656 (2003), doi:10.4271/2003-01-0656; and H. Lienhart, C. Stoots,
  S. Becker, "Flow and turbulence structures in the wake of a simplified car model (Ahmed model)",
  in New Results in Numerical and Experimental Fluid Mechanics III, Notes on Numerical Fluid Mechanics
  77, Springer (2002), pp. 323-330. Not read directly: their set-up is taken from [ERC]. No force data
  (LDA and hot wire only).
- **[G08]** E. Guilmineau, "Computational study of flow around a simplified car body", J. Wind Eng.
  Ind. Aerodyn. 96 (2008) 1207-1217, doi:10.1016/j.jweia.2007.06.041. Read from the owner's copy on
  2026-10-21 (see "Reference files supplied"). Values taken, in this project's words:
  - k-omega SST (Menter 1993), steady, 25 degrees, body without stilts: **Cd 0.3074** (p. 1212, Table 1;
    with stilts not computed at 25 degrees). The same table lists the experiment of [A84] as 0.285 at 25
    degrees (0.260 at 35), in its "with stilts" column.
  - Near-wall treatment: low-Reynolds formulation for every model (p. 1211), first point 0.005 mm from
    the wall, y+ about 0.25, about 30 points in the boundary layer (p. 1212, section 3): wall-resolved.
  - Mesh: half body, unstructured, 1.8 million points without stilts (3.6 million with), 15,300 points on
    the body; domain 2 L ahead, 3 L behind, 0.935 m wide, 1.4 m high, body 50 mm above the ground plane
    (p. 1212, section 3). Steady solution, 10,000 non-linear iterations (p. 1212, section 4). Flow at
    [LB03]'s conditions, 40 m/s, Re_L 2.784e6 (p. 1208), compared with [A84]'s 60 m/s drag.
  - Slant flow at 25 degrees: every model except Spalart-Allmaras separates just past the slant's top
    edge, none reattaches on the slant as the experiment does (p. 1215, Fig. 8); the SST side-edge vortex
    is too weak against the measured one at x = 80 mm (p. 1216, Fig. 10 b); "all simulations predict
    massive separation, whereas the experiment shows reattachment about half-way down the center of the
    face" (p. 1217, Conclusions). [G08] describes the experiment ([LB03], p. 1214, Fig. 7) as two strong
    counter-rotating side vortices, separation on the middle of the slant's top edge and reattachment on
    the slant.
- **[ERC]** ERCOFTAC Knowledge Base Wiki, Application Challenge AC1-05 "Flow around a simplified car
  body (Ahmed body)", Description, https://www.kbwiki.ercoftac.org/w/index.php/Description_AC1-05
  (read 2026-10-21). Also the ERCOFTAC classic database case 082 (http://cfd.mace.manchester.ac.uk/ercoftac/,
  unreachable on 2026-10-21) and the 9th ERCOFTAC/IAHR workshop on refined turbulence modelling (2001),
  test case 9.4.

## Which experiment (V1)

The two experiments differ: [A84] measured forces at 60 m/s (Re_L 4.29e6) in the DFVLR open-jet tunnels
with the model on a stationary ground board; [LB03] measured the wake (no forces) at 40 m/s (Re_L 2.78e6)
in the LSTM 3/4-open test section with the model on a ground plate. V1: the force data compared against
are [A84]'s, so the flow, the ground and the boundary layer follow [A84]. Neither moves its ground.

| Item | [A84] | [LB03] / [ERC] | Used |
|---|---|---|---|
| Speed, Re_L | 60 m/s, 4.29e6 | 40 m/s, 2.78e6 | [A84] |
| Ground | stationary ground board 3 m x 5 m, rounded leading edge, 1.35 L ahead of the model | ground plate above the tunnel floor | stationary no-slip ground from 1.35 L ahead of the nose |
| Boundary layer | grows from the board's leading edge; no suction mentioned | 30 mm at x = -1.444 m in the 9.4 workshop specification ([ERC] lists no value; the figure is from a numerical paper found by search, not used) | grows from the inlet, 1.35 L ahead |
| Turbulence intensity | below 0.5 % | not stated | 0.5 % |
| Forces | strain-gauge balance below the ground plane, four stilts; "Total drag value has been corrected for tare drag of stilts" | none | body only (V2) |

## Geometry (V2)

All from [A84] Fig. 1 and nomenclature unless noted; the generator rebuilds the benchmark's Ahmed body
(`bench/geometries._ahmed_shape`) and cuts it at its plane of symmetry.

| Input | Value | Source |
|---|---|---|
| Length l, width b, height h | 1.044 m, 0.389 m, 0.288 m | [A84] |
| Fore body | 182 mm long, front edges R100 | [A84] Fig. 1 |
| Slant | 25 degrees, 222 mm along the slant, sharp edges | [A84] |
| Ground clearance | 50 mm | [A84] ("fixed on cylindrical stilts 50 mm above a ground board") |
| Stilts | 4 cylinders; the half model has 2 | [A84] Fig. 1 |
| Stilt positions | 202 mm and 672 mm behind the nose (Fig. 1: 202 and 470 mm between them), 163.5 mm from the plane of symmetry | [A84] Fig. 1 |
| Stilt diameter | 30 mm | [ERC] ("placed on stilts of 30 mm diameter"); not dimensioned in [A84] |
| Stilt ends | 10 mm below the ground plane (cut by the domain) and 10 mm inside the body (cut by the body) | V2 |
| Tessellation | linear deflection 0.1 mm, angular 5 degrees (the import default, 1/1000 of the diagonal and 20 degrees, leaves 1.5 mm chord error on R100) | set-up choice |

Parts: `body` (half body, its symmetry face on y = 0), `stilt_front`, `stilt_rear`; one patch each.
The stilts cross the body: the surface preparation "Intersection features" (D-093) adds the two
intersection curves as snap features (0.1885 m in 578 segments).

## Flow and reference values

| Input | Value | Source |
|---|---|---|
| U_inf | 60 m/s | [A84] |
| nu | 1.4601e-5 m2/s = U l / Re_L | [A84] Re_L 4.29e6 on l = 1.044 m; the air's properties are not stated |
| rho_ref | 1.225 kg/m3 (app default) | scales forces only; the coefficients do not depend on it |
| Inlet turbulence | I = 0.5 %, nut/nu = 10 (app default ratio): k = 0.135 m2/s2, omega = 924.6 1/s | [A84] "below 0.5 per cent"; the ratio is not stated |
| Turbulence model, near wall | kOmegaSST, wall functions (nutUSpaldingWallFunction), target y+ 50 at the first cell centre | app defaults (V3) |
| A_ref | 0.056016 m2 = (0.389 x 0.288) / 2, custom | [A84] F, "projected frontal area of model" (the body without stilts), halved for the half model |
| l_ref | 1.044 m | [A84] l |
| Coefficients | Cd, Cl of the half model with the half area: equal to the full body's | |

## Domain (V1, V4)

Box, symmetry plane at y = 0 (`symmetry y_min`, the body's symmetry face), ground plane at z = 0
(stationary, `position value`, z = 0: the stilts reach 10 mm below it, so "the parts' lowest z" would put
the plane 10 mm low). Sizes in L = 1.044 m (the largest extent of the parts):

| Size | Value | Source / reason |
|---|---|---|
| Upstream (inlet to nose) | 1.35 L = 1.409 m | [A84]: the ground board projected 1.35 model lengths in front of the model; the ground boundary layer starts at the inlet, as it started at the board's leading edge. Smaller than the app default 5 L: chosen for the ground boundary layer (V1) |
| Downstream (base to outlet) | 10 L = 10.44 m | app default; common practice 5 to 10 L (e.g. the SimFlow validation case: 10 body lengths) |
| Lateral (body side to side) | 5 L | app default; [A84] is an open jet 3 m wide, the slip side at 5.2 m gives a smaller blockage than any wall |
| Height (roof to top) | 5 L, top at z = 5.558 m | app default; open jet, 3 m nozzle |
| Bottom | ground plane, z = 0 | [A84] |

Domain 12.893 x 5.415 x 5.558 m (388.1 m3). Boundary conditions: the app's (D-022, D-116): inlet
fixedValue U, k, omega; outlet p = 0, inletOutlet; sides and top slip; symmetry symmetryPlane; body,
stilts and ground walls with the wall functions; the ground U noSlip. Prism layers on the ground: off (the
default, D-116): the ground boundary layer is carried by the wall functions on the castellated cells;
its y+ is reported per level in RESULT.md.

## Mesh

App defaults (absolute y+ layers, robust controls, curvature refinement, parallel snappyHexMesh) except
the two sizing targets that set the fine level (below), plus two refinement volumes (D-103):

- `wake`: the app's wake helper on the body (Edit > Add Wake Volume): a box 2 L long behind the body,
  1.1 x its y extent wide, 2 x its height tall, target 2 x the surface cell size;
- `slant`: a box over the slant and the rear edges (from 50 mm ahead of the slant to 100 mm behind the
  base, the half width plus 35 mm, from 50 mm below the base's top edge to 60 mm above the roof) at the
  surface cell size. Reason: at 25 degrees the drag is set on the slant and the base ([A84] Table 2:
  "the pressure drag for the basic body considered here is mainly generated on the slant and vertical base of the rear end") by the slant separation bubble and
  the C-pillar vortices ([A84] Figs. 6, 9, 10), which form within a few cm of the slant's edges; the
  surface refinement alone reaches only 3 cells (nCellsBetweenLevels) from the wall.

Fine level (the study's "current" settings): background cell target 800,000 and target surface size
0.005 l_ref, twice finer in linear size than the app defaults (100,000 and 0.01 l_ref). The study
(D-066, ratio sqrt(2), current = fine) scales every size by 2 (coarse) and sqrt(2) (medium); the coarse
level therefore has exactly the app defaults' sizes. Shared prism stack (D-066, from the fine settings):
9 layers, first 0.635 mm (target y+ 50 at the first cell centre, D-107), ratio 1.2, 13.2 mm.

Measured before the study (app defaults = the coarse level's sizes, one mesh on 8 cores): 216,549 cells,
29 s, checkMesh OK (max non-orthogonality 64.9, max skewness 2.45), body layer thickness 74 %, stilts 0
to 1.5 % (their stacks collapse at the ground and body junctions); 100 solver iterations on 4 cores:
0.38 s per iteration, 1.8 us per cell-iteration.

| Level | Factor | Base size | Surface cell | Background cells (estimate) | Planned cells | Solver time, 1500 iterations, 4 cores | Meshing (8 cores) |
|---|---|---|---|---|---|---|---|
| coarse | 2 | 157 mm | 9.8 mm | 97,580 | 0.22 M (measured: 216,549) | 10 min | 0.5 min |
| medium | 1.414 | 111 mm | 6.9 mm | 284,200 | 0.6-0.8 M | 20-25 min | 1-2 min |
| fine | 1 | 78.6 mm | 4.9 mm | 803,436 | 1.5-1.8 M | 45-80 min | 3-5 min |

The planned cells scale the measured coarse count by the background-cell ratio (upper value) and by the
D-066 measured r^2.3 per level (lower value). Total estimate: 1.3 to 2.1 h of machine time for the study,
within V7 (4 h) with the 0.3 h of trials before it.

## Solver and stopping criteria

simpleFoam, the app's numerics (D-022, preset "robust": SIMPLEC, linearUpwindV for U, upwind k and
omega), 4 ranks (the recommended solver cores, D-064), meshing on 8 (the automatic meshing cores,
D-111). Stopping criteria: the app's defaults for this case, the four residual criteria (p 1e-4, U, k,
omega 1e-5) and the asymptotic criterion on the body's Cd (window 50, relative range 1e-3), combined with
"all"; iteration limit 1500.

Trial (1500 iterations on the coarse-level mesh, before the study): the steady solution does not
settle. From iteration 300 on the body's Cd oscillates with a period of about 167 iterations and a
range of 5 to 8 % of its mean inside every 50-iteration window; the initial residuals stay at 1e-3 (U,
p) and 1e-5 (omega). Neither the residual targets nor the asymptotic criterion can be met. The mean is
stationary: over iterations 300-600, 600-900, 900-1200 and 1200-1500 the body's Cd averages 0.3543,
0.3544, 0.3530, 0.3533 (standard deviation 0.007-0.009), Cl 0.339, 0.350, 0.344, 0.330 (0.055-0.061).
So every level runs to the 1500-iteration limit and the judged values are the means over the last 1000
iterations (about six periods); the study's own end values (the last iteration) are reported beside
them, and the GCI is computed both ways with the app's foam/gci.py. This is recorded as an open question
(docs/QUESTIONS.md): the app has no time-averaged report or criterion for a steady run that oscillates.

## Experimental Cd

[A84] gives the drag against the slant angle in Fig. 4 only (Table 1 lists 5, 12.5 and 30 degrees), and
the figure is a JBIG2 scan that could not be decoded here. The 25 degree value used is **0.285**, the
value quoted from [A84] by the published comparisons found (the CFD Support TCFD benchmark,
https://www.cfdsupport.com/ahmed-body-tcfd-benchmark/: "0.285"; SimScale's validation case reads 0.2875
off the same figure, https://www.simscale.com/docs/validation-cases/aerodynamics-flow-around-the-ahmed-body/).
The two readings differ by 0.9 %; the verdict is also given against 0.2875. [A84]'s values exclude the
stilts ("Total drag value has been corrected for tare drag of stilts"): the comparison uses the body
alone (V2).

## Round 2 (owner review of round 1, 2026-10-21)

The owner read round 1's FAIL as inconclusive: (a) the grids are not converged and the slant regime
changes between levels; (b) the inlet 1.35 L ahead of the nose was where Ahmed's ground board started, not
where the free stream started; (c) the ground boundary layer was unresolved (y+ 1,200-1,700 under the
body); (d) the reference Cd and the SST literature values are unverified. Round 2 fixes (b) and (c) in the
set-up and repeats the three levels; round 1's project, cases and numbers are kept as they are.

### What changes

| Item | Round 1 | Round 2 | Reason |
|---|---|---|---|
| Inlet | 1.35 L ahead of the nose | 5 L ahead (the app default) | (b): the free stream starts well ahead of the board |
| Ground | no-slip wall from the inlet | slip strip `ground_slip` from the inlet to x = -1.4094 m (1.35 L ahead of the nose), the no-slip wall `ground` from there (D-118) | (b): the board's boundary layer starts at its leading edge, as in [A84] |
| Ground prism layers | off (D-116 default) | on: the body's shared stack (9 layers, first 0.635 mm, ratio 1.2, 13.2 mm: the same y+ 50 rule, D-066, D-107) | (c) |
| Base sizes | from the background target 800,000 on 388.1 m3 | pinned to round 1's (base size 78.6 mm on the fine level, `BASE_SIZE_ROUND1`; the study scales it to 111.1 and 157.1 mm) | the three level sizes of round 1 in the longer domain |
| Stopping | 4 residual criteria + the asymptotic criterion on body Cd ("all"); never met, every level to 1500 | the mean-stable criterion on the body Cd alone (W 500, tol 0.5 %, D-118); the 1500-iteration limit kept as the safety cap | QUESTIONS 170; round 1's histories would have stopped at 1002-1036 |
| Judged values | means over the last 1000 iterations | means over the last 500 (the criterion's window) at the stop | the criterion's own mean |
| Cores | meshing 8, solver 4 | meshing 8, solver 8 | to fit the evening's deadline (owner); the solver speed-up from 4 to 8 ranks on this machine is small (1.0-1.2, D-064), so the estimates below assume none |

Unchanged: the geometry and the stilts, the half model, the flow and reference values, the downstream,
lateral and vertical sizes (10, 5, 5 L), the two refinement volumes, the wall functions on the body, the
surface target sizes, the numerics. The wall start is placed on the background cell face nearest to
-1.4094 m (D-118): -1.4380 m (coarse), -1.4338 m (medium), -1.3773 m (fine) (QUESTIONS 176).

Domain 16.704 x 5.415 x 5.558 m (x from -5.220 to 11.484 m), 502.7 m3.

### Reference files supplied (2026-10-21, after round 2)

The owner's folder `~/vortexcfd-geometry/refs/` holds three PDFs (and three Windows `Zone.Identifier`
download records). Read on 2026-10-21 (text and page renders, not copied into the repository):

| File | Expected | Actual content | Used |
|---|---|---|---|
| `guilmineau_2008_jweia.pdf` | [G08] | [G08], J. Wind Eng. Ind. Aerodyn. 96 (2008) 1207-1217 | yes: the values above |
| `ahmed_1984_sae840300.pdf` | [A84] | **another paper**: M. Grandemange, M. Gohlke, O. Cadot, "Turbulent wake past a three-dimensional blunt body. Part 1. Global modes and bi-stability", J. Fluid Mech. 722 (2013) 51-84 (the square-back body, no slant) | no |
| `lienhart_becker_2003_sae2003-01-0656.pdf` | [LB03] | **another paper**: S. Becker, H. Lienhart, F. Durst, "Flow around three-dimensional obstacles in boundary layers", J. Wind Eng. Ind. Aerodyn. 90 (2002) 265-279 (building-like blocks, no Ahmed body) | no |

So [A84] Fig. 4 and [LB03] are still not read. What changed: the peer-reviewed SST result is now read
first hand ([G08]: 0.3074, wall-resolved; it was cited from secondary sources only for the over-predicted
separation); the experimental 0.285 is unchanged and still second hand (now also quoted by [G08] Table 1);
[A84]'s stilt correction is kept from [A84]'s own text read in round 1 ("Total drag value has been
corrected for tare drag of stilts"), although [G08] tabulates 0.285 under "with stilts"; [LB03]'s slant
flow is known only from [G08]'s description (reattachment about half-way down the slant's centre). The
reading uncertainty of Fig. 4 and [LB03]'s inlet, ground and bubble data are still missing.

### References (QUESTIONS 171, 172)

The owner's reference folder `~/vortexcfd-geometry/refs/` does not exist on this machine (checked
2026-10-21 20:33): no papers were supplied. The experimental Cd stays **0.285** as quoted (with 0.2875 as
SimScale's reading), and the SST values of RESULT.md stay as cited; both items stay open. (Superseded
by "Reference files supplied" above.)

### Plan (app estimate; times from round 1's measured rates)

`setup` output (`--round 2`): background cells and the study's cell estimate (assumed ratio 1.90 cells
per background cell, the app's default before a study has run; the ground layers are not in it). The
times scale round 1's same level by the cells: meshing 1.5 x round 1's (ground layers, longer domain), the
solver at round 1's 4-core rate (no gain from 8 ranks assumed), for the full 1500 iterations (the
criterion cannot stop before iteration 1000).

Since the owner's review of round 2, the driver's solver estimate (`setup` and the `--deadline` guard of
`study`) uses the rate measured on the round's own levels at the same core count when one exists (the
same level if it was run before, else the measured level nearest in cells; from the per-level records
`case_study/study_<level>.json`), and falls back to round 1's rate otherwise; it prints the rate's source
(`tests/validation/ahmed_case.estimate_level`).

| Level | Base | Background cells | Estimated cells | Meshing | Solver (1500 it.) | Runs |
|---|---|---|---|---|---|---|
| coarse | 157.1 mm | 126,140 | 239,666 | 1.7 min | 10.5 min | tonight, if its estimated end is before 23:15 |
| medium | 111.1 mm | 367,500 | 698,250 | 2.0 min | 36.7 min | tonight, if its estimated end is before 23:15 |
| fine | 78.6 mm | 1,043,487 | 1,982,625 | 6.2 min | 112.7 min | tomorrow |

Deadline rules of the evening (owner): no OpenFOAM process may run after 23:15; a level is started only
if its estimated end is before 23:15 (the driver refuses otherwise), and a level still running at 23:15 is
stopped through the app's stop (the solver's clean stop, D-058; the meshing stop, D-111) and recorded as
partial.

### Commands

One level per command (the record of each level is kept as `case_study/study_<level>.json`; a later
level never touches an earlier level's directory), all at nice -n 15:

```bash
nice -n 15 .venv/bin/python scripts/validation/ahmed_study.py --round 2 setup
nice -n 15 .venv/bin/python scripts/validation/ahmed_study.py --round 2 study --level coarse --deadline 23:15
nice -n 15 .venv/bin/python scripts/validation/ahmed_study.py --round 2 study --level medium --deadline 23:15
nice -n 15 .venv/bin/python scripts/validation/ahmed_study.py --round 2 study --level fine
nice -n 15 .venv/bin/python scripts/validation/ahmed_study.py --round 2 collect
```

`collect` writes `docs/validation/ahmed/result_round2.json` from the levels run so far (round 1's
`result.json` is not touched).

### The separating run (QUESTIONS 177)

`--round 3`: round 2's set-up with the ground prism layers off (the inlet 5 L ahead and the slip strip
kept), in its own project ahmed25_r2_nolayers; the coarse level only. Against coarse r1 it isolates the
inlet distance and slip strip (b); against coarse r2, the ground layers (c).

```bash
nice -n 15 .venv/bin/python scripts/validation/ahmed_study.py --round 3 setup
nice -n 15 .venv/bin/python scripts/validation/ahmed_study.py --round 3 study --level coarse --deadline 23:15
nice -n 15 .venv/bin/python scripts/validation/ahmed_study.py --round 3 collect   # -> result_round3.json
```
