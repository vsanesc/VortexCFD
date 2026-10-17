# NASA Turbulence Modeling Resource: 2D zero pressure gradient flat plate, SST

Downloaded 2026-10-17, unmodified, from the SST results page of the 2D Zero Pressure Gradient Flat
Plate verification case, https://tmbwg.github.io/turbmodels/flatplate_sst.html (page "Last Updated:
01/17/2026"). Used by tests/validation/test_flat_plate.py (reference of D-036).

| File | Source URL | sha256 |
|---|---|---|
| cf_plate_sstv.dat | https://tmbwg.github.io/turbmodels/FlatPlate/SST/cf_plate_sstv.dat | a56bd2d16818456af015b13839f0a991b4b85bfa6c18242e7c331a2c7a4d40e8 |
| cf_incomp_results_sstv.dat | https://tmbwg.github.io/turbmodels/FlatPlate_validation/cf_incomp_results_sstv.dat | 65bbdbae974af5297db4387d67f2f9ac8d3c46750815d684e108a52e850647b9 |

Flow: M = 0.2 (compressible codes), Re = 5e6 per unit length, plate from x = 0 to 2, SST-Vm (SST, SST-V
and SST-Vm are "nearly identical for this flat plate case" according to the page).

## cf_plate_sstv.dat

Tecplot ASCII, `variables="x","cf"`, two zones: `CFL3D` and `FUN3D`, compressible, on the finest grid
(545 x 385). Columns: x (plate length units, the plate starts at x = 0; x < 0 is the symmetry section
upstream with cf = 0) and the skin friction coefficient cf.

## cf_incomp_results_sstv.dat

Tecplot ASCII, convergence of Cf at x = 0.970084071 for three incompressible codes (zones `FUN3D
incompressible SST/SST-V`, `SC/Tetra incompressible SST/SST-V`, `GHOST incompressible SST/SST-V`).
Columns: N (grid points), h^2 = 1/N, h = sqrt(1/N), Cf at x = 0.97. Five grids, finest first.

Derived values used by the validation (Celik et al. 2008 procedure on each code's three finest grids,
refinement ratio 2; the same procedure gives p = 1.21 and GCI 0.277 % for CFL3D, as published on the page):

| Code | Cf(0.97) finest grid | observed order p | extrapolated | GCI fine |
|---|---|---|---|---|
| FUN3D incompressible | 2.71736e-3 | 1.30 | 2.72251e-3 | 0.24 % |
| SC/Tetra incompressible | 2.72119e-3 | 2.03 | 2.72245e-3 | 0.06 % |
| GHOST incompressible | 2.71085e-3 | 1.19 | 2.71918e-3 | 0.38 % |
| **Mean (reference)** | 2.71647e-3 | | **2.72138e-3** | |

The compressible codes give 2.6908e-3 (CFL3D, finest) and 2.68e-3 on the 273 x 193 grid quoted on the
page, about 1 % below the incompressible results.
