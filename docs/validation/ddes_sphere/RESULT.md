# DDES functional run, sphere at Re 10,000: killed before completion, no verdict

Task 1.1-transient, Part 2. Set-up: [SETUP.md](SETUP.md). The run (4 cores) was stopped when the machine was shut
down overnight, at t = 8.46 t_c of the 25 planned; the sampling (from 15 t_c) never started. No statistics, no
verdict.

What it showed before it stopped:

- A DDES project set up through the app (k-omega SST DDES, Δω̃, σ, DEShybrid, PIMPLE at Co 1) meshes (574,611
  cells; the prism layers on the sphere were not extruded: 0.09 %) and runs; the app's DDES mesh warning was
  silent for its focus box (D/20 cells, 40 across).
- The first launch stopped at once in parallel: "Unknown decompositionMethod type scotch", from the wall distance
  method exactDistance of the tutorial; D-191 now uses meshWave (with the wall normal).
- The last written time, 5 t_c, holds turbulenceProperties:fd and turbulenceProperties:LESRegion (the
  turbulenceFields function object of D-191), and the app's Results Scene offers them ("DDES shielding function
  f_d", "DDES LES region"): the RANS layer around the sphere is visible in both.
- Cost: about 4.1 s per step on 4 cores at 574,611 cells (7.1 µs per cell and step).

Figures (off-screen, outside the repository): ~/vortexcfd-research/1.1-ddes-figures/sphere/.
