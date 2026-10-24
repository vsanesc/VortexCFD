## What and why

<!-- What this changes and why; link the issue. -->

## Decisions

<!-- The DECISIONS.md entries added or changed (every change of behaviour, defaults, file formats or workflow has
one). A project file format change: the new schema version and its migration. -->

## Checks

- [ ] Tests for the change, and the fast suite passes offscreen:
      `QT_QPA_PLATFORM=offscreen nice -n 15 .venv/bin/pytest -q -n 8 -m "not slow and not validation and not long"`
- [ ] GUI changes: reviewed at three window sizes and three interface sizes (scripts/gui_review_sizes.py)
- [ ] User manual (docs/manual/) and docs/STATUS.md updated where the behaviour changed
- [ ] No new dependency, or it is listed in THIRD_PARTY_LICENSES.md with its licence

## [NUMERICS-REVIEW]

<!-- Delete if the change does not touch numerics, boundary conditions or turbulence. Otherwise: the
scripts/validation/public_dicts.py diff against main (byte-identical, or each difference explained), and for a
change meant to alter results the benchmark runs before and after against the baselines (CONTRIBUTING.md). -->
