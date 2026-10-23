# VortexCFD v1 readiness

Checklist against the v1 definition in docs/PLAN.md ("v1", owner, 2026-10-22). Version: 1.0.0rc1
(`vortexcfd.__version__`). Prepared on task/w4-w5, 2026-10-23. Each item: its evidence (decisions, validation
records, tests, manual chapters) and what is still open.

## The definition, item by item

| # | v1 item | State | Evidence |
|---|---|---|---|
| 1 | External and internal steady incompressible flow, stopped on a mean-based criterion (D-118) | **met** | External: D-019 to D-027, D-078, D-116; internal: D-129 to D-131 (Accepted). Mean-stable criterion: D-118, D-119 (windowed means in the reports and studies). Tests: tests/test_mean_stable.py, tests/test_internal_flow.py, tests/test_stopping_gui.py. Validations: pipe PASS, backward-facing step PASS WITH NOTE (docs/validation/pipe, bfs). Manual: chapters 2, 4, 7.3 |
| 2 | Validations recorded: the flat plate, the Ahmed body (a documented result; PASS not required), a wing at several angles of attack | **met** | Flat plate: PASS WITH NOTE (docs/validation/flat_plate/README.md, tests/validation/test_flat_plate.py). Ahmed 25 degrees: FAIL, a documented known limitation accepted for v1 (docs/validation/ahmed/RESULT.md, "Conclusion"; W1 closed). Wing: the NACA 0012 2D section at 0, 10 and 15 degrees, PASS at each angle through the app's preset (docs/validation/naca0012/RESULT.md, Round 3; tests/validation/test_naca0012.py). Note: the "wing" is a 2D section; no 3D wing is validated against data. Manual: chapter 8 |
| 3 | A validated angle-of-attack method | **met** | Rotation of the geometry about the centre of rotation, wind-axis forces, one mesh per angle (D-120, Accepted); validated by the NACA 0012 at three angles (item 2). Tests: tests/test_attitude.py, tests/test_polar_sweep.py, tests/test_force_projection.py. Manual: chapter 3 |
| 4 | Post-processing for a report | **met (owner review of D-136 pending)** | Scalar scenes, sections, Cp and Cf (D-053, D-061, D-062); results scene objects and saved views (D-132); image export (D-133, its camera fixed in this task); the HTML report (D-134); the mesh study and polar sweep tables, line plots, the streamlines' scalar bar, the report's section choice (D-136, Proposed). Tests: tests/test_report.py, tests/test_report_tables.py, tests/test_line_plot.py, tests/test_scene_objects.py, tests/test_image_export.py. Manual: chapter 5 |
| 5 | Installable on another PC, with a short manual | **met on this machine; the second-machine test is owed** | The start-up OpenFOAM check, scripts/install.sh, the version in one place (D-137, Proposed). Proof in isolation (a temporary HOME and prefix, task w4-w5): exit 0, `vortexcfd 1.0.0rc1`, `vortexcfd --check-openfoam` found /usr/lib/openfoam/openfoam2606; run again: the environment reused, exit 0; the manual copied and found by Help > User Manual. Tests: tests/test_openfoam_check.py, tests/test_install_script.py. Manual: docs/manual/ (8 chapters, 11 images exported by the app), linked from README.md and Help > User Manual |

## Known limitations shipped with v1

Recorded in docs/manual/08_validation_and_limits.md: steady incompressible RANS only (no transient, no
compressible flow); the Ahmed body's drag over-predicted by about 14 % with steady SST; the 3D mesh study's GCI is
indicative (D-127 stays Proposed, W3 closed by the owner's closure rule); the flat plate's Cf 3.3 % low,
unexplained; one layer specification for all walls; no restart from the latest time.

## Owed by the owner

1. **Install on a second machine.** A fresh WSL2 Ubuntu 24.04: install OpenFOAM with the ESI commands
   (docs/manual/01_installation.md), run `scripts/install.sh`, start the app from the Start menu (the WSLg desktop
   entry has not been seen on a real display), mesh and solve the sphere of chapter 2. The isolation proof here used
   the existing pip cache, so the second machine is also the first test of the downloads.
2. **Making the repository public**: the decision, and with it the GitHub settings (licence file and notices are in
   place: LICENSE, THIRD_PARTY_LICENSES.md).
3. **The licence review** of THIRD_PARTY_LICENSES.md (prepared: no incompatible licence found; to confirm: foamlib
   GPL-3.0-only, pymeshfix AGPL-3.0, the unused PySide6 WebEngine / Pdf packages, the MPL-2.0 files'
   "Incompatible With Secondary Licenses" notices not checked).
4. **Review of the Proposed decisions** of this task: D-136 (report tables, line plots, the streamlines' scalar bar,
   report sections; schema v21) and D-137 (installation). D-127 stays Proposed as a recorded limitation.
5. **QUESTIONS 212 to 217** (docs/QUESTIONS.md, task w4-w5).
6. **Running the full suite** (scripts/ship.sh) when publishing: the slow, long and validation tests were not run
   in this task.
