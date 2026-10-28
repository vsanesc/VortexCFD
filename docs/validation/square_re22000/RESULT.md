# Square cylinder at Re 22,000, 2D URANS: result

Task 1.1-transient, Part 2, Part B (3a). Set-up and pass rule: [SETUP.md](SETUP.md) (written before the runs; two
amendments before any result). Numbers: [result.json](result.json). Driver: scripts/validation/square_study.py;
project builder: tests/validation/square_case.py; OpenFOAM v2606, 4 cores per level, nice 15, the two levels side
by side.

## Verdict: PASS

The medium level (the deciding one) passes both criteria; the coarse level passes too.

| Level | Cells | Steps | Δt range (s) | Sampling from (t_c, detected) | Cycles | St | mean Cd | RMS Cl | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| coarse | 27,234 | 112,902 | 0.00040-0.0022 | 95.8 | 14.1 | 0.1355 | 2.132 | 1.422 | PASS |
| medium | 40,527 | 65,593 | 0.00020-0.0073 | 82.3 | 8.9 | 0.1310 | 2.082 | 1.474 | PASS |

Errors against ERCOFTAC UFR 2-02 (Lyn et al. 1995: St 0.133 ± 0.004 measured; Cd ≈ 2.1 inferred from the wake;
the Evaluation page's Table 1 lists the experiments as St 0.132, C_D 1.9-2.2: both levels are inside that range
too):

| Level | St | mean Cd |
|---|---|---|
| coarse | +1.9 % | +1.5 % |
| medium | -1.5 % | -0.8 % |
| tolerance | 10 % | 15 % |

Both levels are inside the experiment's ±0.004 band for St (0.129-0.137). The two levels bracket the references
rather than converge monotonically towards them (St 0.1355 -> 0.1310, Cd 2.132 -> 2.082 from coarse to medium):
with two levels and a modulated signal no extrapolation is attempted. Mean Cl -0.004 / -0.014, Cd RMS 0.19 / 0.14.

## What the runs show

- **The start-up perturbation and the detection.** The shedding was developed from about 10 t_c (lift amplitude
  1.5-2.2 per 5 t_c from then on). The lift amplitude is modulated at low frequency (between 1.0 and 2.1 per 5 t_c
  over the whole run), so the detection (0.5 % on the window mean of Cd, 5 % on the ranges) settled only at
  95.8 t_c (coarse) and 82.3 t_c (medium); SETUP's fallback (a sampling start set by hand) was not needed.
- **The k-omega scheme.** The first run of this case crashed in its first step with D-181's limitedLinear k and
  omega (omega clipped to -1213, then a floating-point exception); with D-192's linearUpwind on limited gradients
  neither level clipped omega.
- **PIMPLE at Co 2 on a mesh with wall layers.** Every step ran 3 outer correctors (residual control 1e-4). The
  largest Courant number exceeded the target only in the first two steps of the impulsive start (6.1 and 11.0 at
  t ≈ 0.0015 s), not in the sampled flow.

## Cost

| Level | Cells | Solver wall time | Wall time per step | Wall µs per cell and step (4 cores) |
|---|---|---|---|---|
| coarse | 27,234 | 7,297 s (200 t_c) | 0.065 s | 2.4 |
| medium | 40,527 | 6,293 s (150 t_c) | 0.096 s | 2.4 |

## PISO and PIMPLE on this mesh (D-185)

A PISO run of the coarse level at Co 1 to 15 t_c (`level --name coarse --end 15 --tag piso_timing --set
algorithm=piso`, run/validation/square_re22000/, beside the DDES run) against the PIMPLE run's first 15 t_c (beside
the medium level): PISO 16,139 steps in 759 s, PIMPLE at Co 2 8,768 steps in 613 s (3 outer correctors each).
PIMPLE took 19 % less wall time here, where the wall layers set the Courant limit (on the laminar cylinder, whose
limit is set by the wake cells, it took 26 % more). The PISO run's statistics were not sampled (timing only).
