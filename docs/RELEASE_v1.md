# VortexCFD v1 readiness

Checklist against the v1 definition in docs/PLAN.md ("v1", owner, 2026-10-22). Version: 1.0.0rc1
(`vortexcfd.__version__`). Prepared on task/w4-w5, 2026-10-23; updated on task/rc1-polish (owner review of w4-w5). Each item: its evidence (decisions, validation
records, tests, manual chapters) and what is still open.

## The definition, item by item

| # | v1 item | State | Evidence |
|---|---|---|---|
| 1 | External and internal steady incompressible flow, stopped on a mean-based criterion (D-118) | **met** | External: D-019 to D-027, D-078, D-116; internal: D-129 to D-131 (Accepted). Mean-stable criterion: D-118, D-119 (windowed means in the reports and studies). Tests: tests/test_mean_stable.py, tests/test_internal_flow.py, tests/test_stopping_gui.py. Validations: pipe PASS, backward-facing step PASS WITH NOTE (docs/validation/pipe, bfs). Manual: chapters 2, 4, 7.3 |
| 2 | Validations recorded: the flat plate, the Ahmed body (a documented result; PASS not required), a wing at several angles of attack | **met** | Flat plate: PASS WITH NOTE (docs/validation/flat_plate/README.md, tests/validation/test_flat_plate.py). Ahmed 25 degrees: FAIL, a documented known limitation accepted for v1 (docs/validation/ahmed/RESULT.md, "Conclusion"; W1 closed). Wing: the NACA 0012 2D section at 0, 10 and 15 degrees, PASS at each angle through the app's preset (docs/validation/naca0012/RESULT.md, Round 3; tests/validation/test_naca0012.py). Note: the "wing" is a 2D section; no 3D wing is validated against data. Manual: chapter 8 |
| 3 | A validated angle-of-attack method | **met** | Rotation of the geometry about the centre of rotation, wind-axis forces, one mesh per angle (D-120, Accepted); validated by the NACA 0012 at three angles (item 2). Tests: tests/test_attitude.py, tests/test_polar_sweep.py, tests/test_force_projection.py. Manual: chapter 3 |
| 4 | Post-processing for a report | **met** | Scalar scenes, sections, Cp and Cf (D-053, D-061, D-062); results scene objects and saved views (D-132); image export (D-133, its camera fixed in this task); the HTML report (D-134); the mesh study and polar sweep tables, line plots, the streamlines' scalar bar, the report's section choice (D-136, Accepted); 2D cases shown and exported looking along +y, flow left to right (D-140, Proposed). Tests: tests/test_report.py, tests/test_report_tables.py, tests/test_line_plot.py, tests/test_scene_objects.py, tests/test_image_export.py. Manual: chapter 5 |
| 5 | Installable on another PC, with a short manual | **met** | The start-up OpenFOAM check, scripts/install.sh, the version in one place (D-137, Accepted). **The owner ran scripts/install.sh in a clean WSL2 Ubuntu 24.04 distribution and it worked** (owner review of w4-w5). Qt from PySide6-Essentials only (D-139): the isolated install 1870 MB -> 1442 MB. ParaView optional and reported as such (D-138). Proof in isolation (a temporary HOME and prefix, task w4-w5): exit 0, `vortexcfd 1.0.0rc1`, `vortexcfd --check-openfoam` found /usr/lib/openfoam/openfoam2606; run again: the environment reused, exit 0; the manual copied and found by Help > User Manual. Tests: tests/test_openfoam_check.py, tests/test_install_script.py. Manual: docs/manual/ (8 chapters, 11 images exported by the app), linked from README.md and Help > User Manual |

## Known limitations shipped with v1

Recorded in docs/manual/08_validation_and_limits.md: steady incompressible RANS only (no transient, no
compressible flow); the Ahmed body's drag over-predicted by about 14 % with steady SST; the 3D mesh study's GCI is
indicative (D-127 stays Proposed, W3 closed by the owner's closure rule); the flat plate's Cf 3.3 % low,
unexplained; one layer specification for all walls; no restart from the latest time.

## Done by the owner

- **Install on a clean machine**: scripts/install.sh run in a clean WSL2 Ubuntu 24.04 distribution; it worked
  (owner review of w4-w5). D-136 and D-137 accepted; QUESTIONS 215 and 216 accepted for v1, 217 closed as fixed, 212
  kept as a note in the manual (5.4: images and reports made before the camera fix should be made again).

## What remains before v1.0.0

1. **The decision on a public repository**, and with it the GitHub settings (LICENSE and THIRD_PARTY_LICENSES.md are
   in place).
2. **The licence review sign-off** of THIRD_PARTY_LICENSES.md (prepared: no incompatible licence found; to confirm:
   foamlib GPL-3.0-only, pymeshfix AGPL-3.0, the MPL-2.0 files' "Incompatible With Secondary Licenses" notices not
   checked; Qt WebEngine and Qt Pdf are no longer installed, D-139).
3. **Tagging v1.0.0** (the version set once in `vortexcfd.__version__`, then the tag), after the full suite
   (scripts/ship.sh: the slow, long and validation tests are not run by agents).

Also open, not blocking:

- **QUESTIONS 214**: the WSLg desktop entry in the Windows Start menu has not been seen; for the owner to check on a
  real display (agents never use it).
- Review of this task's Proposed decisions: D-138 (ParaView optional), D-139 (PySide6-Essentials), D-140 (the 2D view
  convention, [NUMERICS-REVIEW]); QUESTIONS 218 to 222.
