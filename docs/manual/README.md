# VortexCFD user manual

VortexCFD 1.0 (release candidate 1.0.0rc1) is a desktop workflow for steady, incompressible RANS flow on top of
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

Images: every picture in this manual was exported by the app itself (File > Export Image, the line plot's Export
PNG, the report's plots) from real results, with `scripts/manual_images.py`.

The manual is opened from the app with Help > User Manual.
