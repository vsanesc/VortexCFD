# VortexCFD

A desktop workflow for steady, incompressible CFD on top of OpenFOAM ESI v2606: geometry, domain, mesh, physics,
run and results in one simulation tree (Python, PySide6, PyVista), running in WSL2 Ubuntu 24.04.

**User manual: [docs/manual/README.md](docs/manual/README.md)** (also Help > User Manual in the app).

## Install

On WSL2 Ubuntu 24.04, install OpenFOAM v2606 with the official ESI packages, then run the install script from this
checkout (details: [docs/manual/01_installation.md](docs/manual/01_installation.md)):

```bash
scripts/install.sh
```

```bash
vortexcfd --version
```

## Development

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

Run the fast tests offscreen (CLAUDE.md lists the project rules):

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q -m "not slow and not validation and not long"
```

Architecture: ARCHITECTURE.md. Decisions: DECISIONS.md. Plan and status: docs/PLAN.md, docs/STATUS.md. Validation
records: docs/validation/. Licence: GPL-3.0-or-later (LICENSE); dependencies: THIRD_PARTY_LICENSES.md.
