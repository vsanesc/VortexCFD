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
