# Start-up perturbations: equivalence measurements (A and B): result

Task 1.1-transient, Part 2 closing brief (D-198, QUESTIONS 259). Set-up and rules: [SETUP.md](SETUP.md), committed
before any run (8f73cbc). Comparison by scripts/validation/window_compare.py (the app's own St, mean and RMS from the
force history; the app's start-up detection). OpenFOAM v2606, nice 15, one run at a time. Another workload ran on the
machine during these runs: every wall time below is **indicative only, measured with another workload running**; no
cost conclusion is drawn from them.

## A. Circular cylinder, Re 100, laminar, coarse level

Three runs (17,182 cells, PISO at Co 1, 4 processes, sampling set at 180 t_c, end 240 t_c), differing only in the
start. Numbers: [cylinder.json](cylinder.json). The initial-field run's setExprFields set 0/U (peak cross-flow
0.098 U on 358 cells) and the declaration opened its solver log.

Window [180, 240] t_c (9.8 shedding cycles), with the halves [180, 210] / [210, 240]:

| Run | St | mean Cd | RMS Cl |
|---|---|---|---|
| none | 0.163831 (0.163820 / 0.163803) | 1.339790 (1.339774 / 1.339806) | 0.228333 (0.228873 / 0.227770) |
| initial | 0.163832 (0.163850 / 0.163823) | 1.339854 (1.339920 / 1.339782) | 0.230263 (0.231188 / 0.229335) |
| swing | 0.163831 (0.163830 / 0.163803) | 1.339787 (1.339800 / 1.339783) | 0.228783 (0.229593 / 0.227958) |

Differences from "none" against the rule's limit v = max(|half-difference| of the run, of "none"):

| Run | St: d / v | mean Cd: d / v | RMS Cl: d / v | Verdict |
|---|---|---|---|---|
| initial | 1.3e-6 / 2.8e-5 | 6.4e-5 / 1.4e-4 | **1.93e-3 (0.85 %)** / 1.85e-3 | **not equivalent** (RMS Cl just over v) |
| swing | 2.3e-7 / 2.4e-5 | 2.9e-6 / 4.2e-5 | 4.5e-4 (0.20 %) / 1.6e-3 | **equivalent** |

**Verdict under the committed rule: the inflow swing is equivalent to no perturbation; the initial-field
perturbation fails the rule (not equivalent)** — its St and mean Cd agree to 1e-6 and 5e-5 relative, but its RMS Cl is 0.85 % higher, 4 %
over the limit (1.93e-3 against 1.85e-3). Reading (not part of the verdict): in all three runs the RMS of Cl still
falls from the first half to the second (by 0.5-0.8 %), so the lift amplitude was still settling slowly at 180-240
t_c, and the initial-field run, whose shedding grew differently, sits slightly higher on that slow approach. Whether
the unperturbed run had settled is checked by the follow-up A2 (SETUP.md, rule committed before it); A's rule is not
relaxed.

**Start-up time** (the app's detection on each force history: two windows of 20 t_c, mean of Cd within 0.5 %,
ranges within 5 %, both windows after the perturbation's end):

| Run | Perturbation ends | Start-up detected | Time steps to it | Saved vs none | Indicative wall time to it |
|---|---|---|---|---|---|
| none | — | 148.0 t_c | 20,712 | — | 253 s |
| initial | 5 t_c | 105.8 t_c | 15,119 | **42.2 t_c, 5,593 steps (27 %)** | 178 s |
| swing | 10 t_c | 84.0 t_c | 12,171 | **64.0 t_c, 8,541 steps (41 %)** | 142 s |

(The indicative wall times are each run's solver time scaled by its share of steps; 4 processes, measured with
another workload running.) The swing saves more start-up time here than the initial-field perturbation.
