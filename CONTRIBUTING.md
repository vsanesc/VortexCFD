# Contributing to VortexCFD

Thank you for helping. VortexCFD is a GUI for OpenFOAM ESI v2606 running in WSL2 Ubuntu 24.04; read
ARCHITECTURE.md (the layers and where things live) and DECISIONS.md (why things are as they are) before changing
anything.

## Setup

1. WSL2 Ubuntu 24.04 with OpenFOAM v2606 from the official ESI packages
   ([docs/manual/01_installation.md](docs/manual/01_installation.md)). OpenFOAM is not put on the PATH: the app runs
   it through the `openfoam2606` launcher (vortexcfd.foam.runner in code).
2. A virtual environment in the checkout; never install packages system-wide:

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

New dependencies are discussed in an issue first, and their licence is added to THIRD_PARTY_LICENSES.md (the
combined work is GPL-3.0; see README.md).

## Code rules

- core/ and foam/ never import Qt, pyvista or vortexcfd.gui (tests/test_layers.py enforces it).
- Code, comments and documentation in English; write code that reads like the code around it.
- Colours, sizes and text sizes come from gui/theme.py only (tests/test_theme.py and tests/test_typography.py fail
  otherwise).
- Every change of behaviour, defaults, file formats or workflow gets a DECISIONS.md entry in the same commit; a change
  of the project file format bumps the schema version with a migration in core/project_io.py.

## Tests

Anything that opens a window runs offscreen (tests/conftest.py applies the display guard). While working, run only
the tests of the modules you changed:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/test_the_module.py
```

Before a pull request, run the fast suite once (heavy commands at a low priority; `-n 8` is safe):

```bash
QT_QPA_PLATFORM=offscreen nice -n 15 .venv/bin/pytest -q -n 8 -m "not slow and not validation and not long"
```

The `slow`, `long` (real OpenFOAM runs above 60 s) and `validation` tests are run by the maintainer when a branch is
published. GUI changes are reviewed with offscreen screenshots at three window sizes and three interface sizes
(scripts/gui_review_sizes.py; tests/test_screen_layouts.py checks overlaps and clipped text automatically).

## Branches and review

- Work on a branch named `task/<topic>`; commit each completed part with the message `Task <id>: <summary>`, staging
  only the files that belong to it.
- Open a pull request against `main` with the template filled in. The maintainer reviews, runs the full suite and
  merges; contributors do not push to `main`, merge or delete branches.

## Numerics, boundary conditions and turbulence: [NUMERICS-REVIEW]

Any change to code that decides the numerics (schemes, solvers, relaxation, meshing parameters that change the mesh),
boundary conditions or turbulence modelling is marked `[NUMERICS-REVIEW]`: in the code comment next to it, in the
commit message and in the pull request title. Such a change needs evidence:

- the public benchmarks' dictionaries before and after (`scripts/validation/public_dicts.py` on `main` and on the
  branch, then `diff -r`): byte-identical when the defaults must not change, or each difference explained;
- for a change that is meant to alter results, the benchmark cases (sphere, wing, Ahmed body; benchmarks/README.md)
  run before and after, compared with the baselines and the reference data in docs/validation/, and recorded in
  benchmarks/ or docs/validation/.

A numerics change without that evidence is not merged.
