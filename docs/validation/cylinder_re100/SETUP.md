# Circular cylinder at Re 100: set-up

Task 1.1-transient, Part B. Written before the validation runs; the pass rule below is not changed after them.

## What it checks

The transient solver of release 1.1 (D-181: pimpleFoam, the adaptive time step, the second-order transient schemes,
the detected sampling window, the time-weighted statistics, the Strouhal number from the lift spectrum) and the
laminar option (D-182) on the classic periodic laminar wake of a circular cylinder (parallel shedding, Re 100), set up
and run through the app: the "2D airfoil" preset (2D mode, D-121), the cylinder imported as a 2D section, Generate
Mesh and Run Solver as the workflow layer runs them (scripts/validation/cylinder_study.py; the project builder is
tests/validation/cylinder_case.py).

## Case

| Item | Value |
|---|---|
| Geometry | circular cylinder, D = 1 m, a closed 720-segment circle imported as a Selig section (sharp closure) |
| Flow | U = 1 m/s, nu = 0.01 m²/s: Re = U D / nu = 100; laminar (no turbulence model), incompressible, transient |
| Reference values | l_ref = D = 1 m, A_ref = D x span (2D), the coefficients per unit span; t_c = D / U = 1 s |
| Domain | the preset's C-type far field: radius 30 D (inlet 30 D ahead, far field 30 D to each side), wake 50 D behind |
| Boundary conditions | the app's external-flow defaults: inlet fixed U, outlet fixed p 0, far field slip, the cylinder no-slip |

Blockage: D / H = 1 / 60 = 1.7 %. Behr, Hastreiter, Mittal and Tezduyar (1995, Comput. Methods Appl. Mech. Engrg.
123) found the Re 100 Strouhal number and forces converge once the lateral boundaries are about 8 D or more from the
cylinder and the inlet about 8 D ahead; Posdziech and Grundmann (2007, J. Fluids Struct. 23) showed the remaining
dependence of Cd on the domain size (a few per cent between domains of 25 D and several hundred D), which is one
reason the Cd tolerance is 5 %. The far field here is slip, not a free-stream condition: with 30 D to each side its
effect on the forces is of the order of the blockage.

## Mesh study

Three levels made by the app's mesher, every size scaled by the background cell (refinement ratio sqrt(2) between
levels; the surface refinement level and the wake box's relative size are fixed): background cell 1.414, 1 and
0.707 m (coarse, medium, fine), surface cell base / 128 (D/90.5, D/128, D/181), four relative prism layers on the
cylinder (the laminar boundary layer is about D / sqrt(Re) = 0.1 D thick), and a wake box from 0.5 D ahead of the
centre to 16.5 D behind it, 5 D high, at base / 16. The GCI (Celik et al. 2008, foam/gci.py) on St and the mean Cd,
with h = (A / N)^(1/2).

## Run

The app's transient defaults: adaptive step at a maximum Courant number of 1, backward in time, linearUpwind for U,
PISO (1 outer corrector, 2 pressure correctors); start from the free stream (the shedding starts from the mesh's
own asymmetry); the sampling start detected (window 20 t_c, about 3.3 shedding periods); end time 180 t_c. 4 cores,
nice 15.

Amendment (after the coarse level, before the fine one; the pass rule is unchanged): the fine level runs to 200 t_c.
The coarse level's start-up was detected at 153.7 t_c, leaving 26 t_c (4.3 cycles) to sample; 20 more t_c keep the
finest level above the 3-cycle minimum even if its start-up ends later.

## References

- Strouhal number: Williamson (1996), "Vortex dynamics in the cylinder wake", Annu. Rev. Fluid Mech. 28, 477-539:
  the parallel-shedding St-Re relation gives St = 0.164 to 0.166 at Re 100 (the band used).
- Mean drag: about 1.33 (Park, Kwon and Choi 1998, KSME Int. J. 12: 1.33; Posdziech and Grundmann 2007: about 1.32 to
  1.35 depending on the domain; Qu, Norberg, Davidson, Peng and Wang 2013, J. Fluids Struct. 39: about 1.33).
- RMS of the lift: about 0.23 (Park et al. 1998: lift amplitude 0.332, an RMS of 0.235; Qu et al. 2013: about 0.23;
  Posdziech and Grundmann 2007: about 0.23).

The numbers are the values these papers are commonly quoted with; they were not re-read for this task (no access to
the papers here): QUESTIONS asks the owner to confirm them.

## Pass rule

Per level, on the statistics of the detected sampling window:

| Quantity | Reference | PASS within |
|---|---|---|
| St (lift spectrum) | the band 0.164-0.166 | 3 % of the nearer band end (0 inside the band) |
| mean Cd | 1.33 | 5 % |
| RMS of Cl | 0.23 | 15 % |

The case PASSES when the finest level passes all three; the study shows whether the levels converge towards it. A
level whose sampling window holds fewer than 3 shedding cycles does not count.
