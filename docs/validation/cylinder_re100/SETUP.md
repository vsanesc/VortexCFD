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
effect on the forces is of the order of the blockage. (Behr et al. 1995 and Posdziech and Grundmann 2007 are cited
here from memory for the domain-size argument only; they were not re-read and give no reference value of the rule.)

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

Sourced in Part 2, Part 0 of task 1.1-transient (2026-10-27), replacing the values first written here from memory.
The tolerances of the pass rule are unchanged (see "Amendment of the references" below).

- **Strouhal number: 0.164-0.165.** Constant, Li, Favier, Meldi, Meliga and Serre (2016), "Implementation of a
  discrete Immersed Boundary Method in OpenFOAM", arXiv:1609.04364 (https://arxiv.org/abs/1609.04364), Table 3
  (2D flow past a fixed cylinder at Re 100): Barkley and Henderson (1996, J. Fluid Mech. 322, 215-241) 0.165;
  Williamson (1996, Annu. Rev. Fluid Mech. 28, 477-539) 0.164; Norberg (1994, J. Fluid Mech. 258, 287-316) 0.164.
- **Mean drag: 1.35.** The same Table 3: Henderson (1995, Phys. Fluids 7(9), 2102-2104) 1.35; Blackburn and
  Henderson (1999, J. Fluid Mech. 385, 255-286) 1.35.
- **RMS of the lift: 0.253.** Dong and Shen (2014), "A Pressure Correction Scheme for Generalized Form of
  Energy-Stable Open Boundary Conditions for Incompressible Flows", arXiv:1409.6676
  (https://arxiv.org/abs/1409.6676), Table 2: their 2D spectral-element results at Re 100 are 0.261, 0.254, 0.253
  and 0.253 for wake lengths of 5, 10, 15 and 20 D (domain 20 D high, periodic sides); the reference is the
  domain-independent 0.253. The same table lists earlier 2D simulations at Re 100 from 0.21 (Braza et al. 1986;
  Tang and Audry 1997) to 0.27 (Persillon and Braza 1998; Hwang and Lin 1992).

Opened for this: the two arXiv papers above (full text). The original papers behind Table 3 (Henderson 1995;
Blackburn and Henderson 1999; Barkley and Henderson 1996; Williamson 1996; Norberg 1994) are not open access and
were not opened; their values are cited as Constant et al. tabulate them.

### Amendment of the references (after the runs; the rule is unchanged)

The first version of this file used St 0.164-0.166, mean Cd 1.33 and RMS Cl 0.23, quoted from memory (Park, Kwon
and Choi 1998; Posdziech and Grundmann 2007; Qu et al. 2013) and not re-read. The owner asked for sourced values.
The tolerances (3 %, 5 %, 15 %) and the rule are the ones written before the runs; only the reference values
changed, and RESULT.md recomputes every level's verdict against them. The verdict did not change (PASS on all three
levels); the RMS Cl error moved from about 0 % to about -9 %.

## Pass rule

Per level, on the statistics of the detected sampling window:

| Quantity | Reference | PASS within |
|---|---|---|
| St (lift spectrum) | the band 0.164-0.165 | 3 % of the nearer band end (0 inside the band) |
| mean Cd | 1.35 | 5 % |
| RMS of Cl | 0.253 | 15 % |

The case PASSES when the finest level passes all three; the study shows whether the levels converge towards it. A
level whose sampling window holds fewer than 3 shedding cycles does not count.
