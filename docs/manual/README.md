<p align="center"><img src="images/vortexcfd-lockup.svg" alt="VortexCFD" width="420"></p>

# VortexCFD user manual

VortexCFD 1.0 (1.0.0) is a desktop workflow for steady, incompressible RANS flow on top of
OpenFOAM ESI v2606: geometry, domain, mesh, physics, run and results in one simulation tree, without editing
OpenFOAM dictionaries by hand. Every case it writes is a standard OpenFOAM case that ParaView can open.

Short and practical; the reasons behind each behaviour are in DECISIONS.md (D-numbers below).

| Chapter | What it covers |
|---|---|
| [1. Installation](01_installation.md) | The install script, the OpenFOAM step, the start-up check |
| [2. A first external case](02_first_external_case.md) | A sphere: import, domain, mesh, physics, run, results |
| [3. A 2D airfoil](03_airfoil_2d.md) | The "2D airfoil" preset, airfoil import, angle of attack, the polar sweep |
| [4. Internal flow](04_internal_flow.md) | The internal presets, patch roles, which inlet to use, pressure drop |
| [5. Results and the report](05_results_and_report.md) | The Results Scene, scene objects, line plots, images, the HTML report |
| [6. Meshing guidance](06_meshing_guidance.md) | y+ and wall treatment, layer warnings, refinement volumes, parallel meshing |
| [7. Troubleshooting](07_troubleshooting.md) | checkMesh failures, the first-cell drift, oscillating runs, a run that will not converge |
| [8. Validation and known limitations](08_validation_and_limits.md) | The validated cases and their verdicts, what v1 does not do |
| [9. Properties reference](09_properties_reference.md) | What every section of the Properties panel does, its defaults and why (the "?" of each section) |
| [10. Transient flow](10_transient_flow.md) | 1.1: when to use it, the Courant number, the sampling window, the averaged results and the Strouhal number |

Images: every picture of results in this manual was exported by the app itself (File > Export Image, the line plot's
Export PNG, the report's plots) from real results, with `scripts/manual_images.py`; the pictures of the window
(welcome screen, New simulation, Compare tab) are the app's own window captures, made offscreen with
`scripts/gui_review.py`.

The manual is opened from the app with Help > User Manual.
