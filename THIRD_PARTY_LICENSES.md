# Third-party licences

VortexCFD is GPL-3.0-or-later. This file lists every runtime dependency, its version in the
development environment (.venv, 2026-10-18) and its licence, as declared in the installed package
metadata (`License-Expression`, `License` or the licence classifier). Development-only tools
(pytest, pytest-qt, pytest-xdist) are not listed. Decision: D-074.

## Direct dependencies (pyproject.toml)

| Package | Version | Licence | Notes |
|---|---|---|---|
| PySide6 (with PySide6_Essentials, PySide6_Addons, shiboken6) | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Qt for Python; bundles the Qt libraries (LGPL-3.0) |
| pyvista | 0.49.1 | MIT | |
| pyvistaqt | 0.13.1 | MIT | |
| pydantic | 2.14.1 | MIT | with pydantic_core 2.50.1 (MIT) |
| foamlib | 1.8.1 | GPL-3.0-only | |
| matplotlib | 3.11.2 | Matplotlib License (PSF-based) | colormaps only (D-054) |
| cadquery-ocp-novtk | 8.0.1.1.0 | Apache-2.0 | bundles OpenCASCADE Technology (LGPL-2.1 with the OCCT exception); with cadquery-ocp-proxy 8.0.1.1.0 (Apache-2.0) |
| pymeshfix | 0.18.1 | AGPL-3.0 (classifier) | wraps MeshFix (GPL-3.0); AGPL-3.0 is combinable with GPL-3.0 (section 13 of both); its network clause does not apply to a desktop application (D-074) |
| pytetwild | 0.4.2 | MPL-2.0 (classifier) | wraps fTetWild (MPL-2.0) |

## Transitive dependencies

| Package | Version | Licence |
|---|---|---|
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| vtk | 9.7.1 | BSD (BSD-3-Clause) |
| scooby | 0.12.0 | MIT |
| pooch | 1.9.0 | BSD-3-Clause |
| pyvista-validation | 0.2.2 | MIT |
| cyclopts | 5.2.0 | Apache-2.0 |
| QtPy | 2.4.3 | MIT |
| pillow | 12.3.0 | MIT-CMU |
| contourpy | 1.4.0 | BSD-3-Clause |
| cycler | 0.12.1 | BSD |
| fonttools | 4.67.0 | MIT |
| kiwisolver | 1.5.1 | BSD |
| pyparsing | 3.3.3 | MIT |
| python-dateutil | 2.9.0.post0 | Apache-2.0 OR BSD-3-Clause (dual) |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| six | 1.17.0 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| annotated-types | 0.8.0 | MIT |
| typing-inspection | 0.4.4 | MIT |
| aioshutil | 1.6 | BSD |
| multicollections | 1.2.0 | Apache-2.0 |
| rich | 15.0.0 | MIT |
| rich-rst | 2.2.0 | MIT |
| markdown-it-py | 4.2.0 | MIT |
| mdurl | 0.1.2 | MIT |
| pygments | 2.21.0 | BSD-2-Clause |
| docstring-parser | 0.18.0 | MIT |
| attrs | 26.1.0 | MIT |
| platformdirs | 4.13.0 | MIT |
| requests | 2.34.2 | Apache-2.0 |
| urllib3 | 2.8.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| charset-normalizer | 3.5.2 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |

## External programs (not bundled)

| Program | Licence | Use |
|---|---|---|
| OpenFOAM ESI v2606 | GPL-3.0 | the solver and mesher, run as separate processes (D-001, D-004) |
| ParaView (optional, Windows) | BSD-3-Clause | "Open in ParaView" starts it on a case (D-055) |

To refresh the versions: `.venv/bin/pip list`; the licence fields are in each package's
`*.dist-info/METADATA`.
