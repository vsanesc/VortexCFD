# Square cylinder at Re 22,000, 3D DDES: set-up

Task 1.1-transient, Part 2, Step 3. Written and committed before the scaling test and the run; the pass rule below
is not changed after them.

## What it checks

k-omega SST DDES (D-191; the app's defaults: Δω̃, the σ variant, DEShybrid with linear in the resolved LES region and
linearUpwind elsewhere, k and omega by linearUpwind on limited gradients (D-192), PIMPLE with residual control at
Co 1, the start-up perturbation) on the case validated in 2D URANS (docs/validation/square_re22000/), now in 3D with
resolved spanwise turbulence.

## Mesh

The validated 2D medium mesh (40,527 cells, the app's mesher, 4 prism layers at y+ 50 with wall functions; a wake
box from 0.5 D ahead of the front face to 14.5 D behind it at 0.0625 D) extruded in the spanwise direction:

| Item | Value | Source |
|---|---|---|
| Span | 4 D | ERCOFTAC UFR 2-02, Test Case page (https://kbwiki.ercoftac.org/w/index.php/UFR_2-02_Test_Case): the LES workshop domain extended "4 D in the spanwise direction" |
| Spanwise cells | 20 (Δz = 0.2 D) | UFR 2-02 Evaluation (https://kbwiki.ercoftac.org/w/index.php?title=UFR_2-02_Evaluation), Table 1: the LES grids' N_z is 20 for most entries (13 to 48 in all; one 127) |
| Sides | periodic (translational cyclic pair) | the workshop's periodic spanwise boundaries |
| Cells | 810,540 (checkMesh: Mesh OK, max non-orthogonality 58.1) | |

The extrusion and the periodic pair are made by OpenFOAM utilities (topoSet, createPatch, extrudeMesh): the app
meshes a 2D section one cell thick and has no periodic boundary. Everything else is the app's: the solver files
(physics_case.build_solver_files of the DDES project) and the run (SolverRun). Expected memory: about 2.0 GB per
million cells for pimpleFoam, +30 % at 8 processes: about 1.6 GB, 2.1 GB at 8 processes.

Two compromises are known before the run: Δz = 0.2 D is coarser than the in-plane wake cells (0.0625 D), so the
focus region is not cubic as Spalart (NASA/CR-2001-211032) asks; the walls use wall functions (y+ 50), as the 2D
validation.

## Run

Free stream U = 1 m/s, D = 1 m, nu = 1/22,000 (t_c = 1 s), inlet turbulence 2 %; the start-up perturbation for
10 t_c; the sampling start set by hand at 40 t_c (not detected: a modulated 3D flow may not settle under the
detection rule, and the window must be fixed in advance); end time 100 t_c: a 60 t_c window, about 8 shedding
periods at St 0.132. Field averages from 40 t_c. The process count is the one the scaling test finds fastest; the
run starts only if its estimate is at most 12 hours (else options are reported instead).

## References

ERCOFTAC UFR 2-02 Evaluation, Table 1 "Global parameters for flow past square cylinder", row "Experiments" (Lyn
et al. 1995): St 0.132, C_D 1.9-2.2, L_R/D 1.38; C_L' was not measured ("there are no experimental results
available for comparison"). The Test Case page: "St of 0.133 ± 0.004", C_D ≈ 2.1 inferred from the wake.

## Pass rule

| Quantity | Reference | PASS within |
|---|---|---|
| St (lift spectrum) | 0.132 | 10 % |
| mean Cd | the experiments' range 1.9-2.2 | 5 % outside the range (1.805-2.31) |

The case PASSES when both pass. Reported without a verdict: RMS Cl (no experimental value; Table 1's LES give
1.15-1.79) and L_R/D from the mean velocity on the centre line at mid-span (reference 1.38). A window with fewer
than 5 shedding cycles does not count.
