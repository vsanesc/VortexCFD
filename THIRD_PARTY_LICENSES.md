# Third-party licences

VortexCFD is GPL-3.0-or-later. This file lists every runtime dependency installed by `scripts/install.sh`
(`scripts/requirements-v1.txt`, the pinned versions of 1.0.0) with its licence as declared in the installed
package metadata (`License-Expression`, else `License`, else the licence classifier), read on 2026-10-23.
Development-only tools (pytest, pytest-qt, pytest-xdist, iniconfig, pluggy, execnet) are not listed. Decision:
D-074; licence review for v1: the section at the end (prepared for the owner, task w4-w5).

## Direct dependencies (pyproject.toml)

| Package | Version | Licence | Notes |
|---|---|---|---|
| PySide6_Essentials | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Qt for Python, the essential modules only (D-139; not the PySide6 meta-package); bundles the Qt libraries (LGPL-3.0) |
| pyvista | 0.49.1 | MIT | |
| pyvistaqt | 0.13.1 | MIT | |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | |
| pydantic | 2.14.1 | MIT | |
| foamlib | 1.8.1 | GPL-3.0-only | see the review, item 1 |
| matplotlib | 3.11.2 | Matplotlib License (PSF-based) | colormaps, the report's plots, the line plot charts |
| cadquery-ocp-novtk | 8.0.1.1.0 | Apache-2.0 | bundles OpenCASCADE Technology (LGPL-2.1 with the OCCT exception) |
| pymeshfix | 0.18.1 | AGPL-3.0 (classifier) | wraps MeshFix (GPL-3.0); see the review, item 2 |
| pytetwild | 0.4.2 | MPL-2.0 (classifier) | wraps fTetWild (MPL-2.0) |

## Transitive dependencies

| Package | Version | Licence | Required by |
|---|---|---|---|
| shiboken6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | PySide6_Essentials |
| cadquery-ocp-proxy | 8.0.1.1.0 | Apache-2.0 | cadquery-ocp-novtk |
| pydantic_core | 2.50.1 | MIT | pydantic |
| annotated-types | 0.8.0 | MIT | pydantic |
| typing-inspection | 0.4.4 | MIT | pydantic |
| typing_extensions | 4.16.0 | PSF-2.0 | pydantic and others |
| vtk | 9.7.1 | BSD (BSD-3-Clause) | pyvista |
| scooby | 0.12.0 | MIT | pyvista |
| pooch | 1.9.0 | BSD-3-Clause | pyvista |
| pyvista-validation | 0.2.2 | MIT | pyvista |
| cyclopts | 5.2.0 | Apache-2.0 | pyvista |
| docstring_parser | 0.18.0 | MIT | cyclopts |
| attrs | 26.1.0 | MIT | cyclopts |
| rich | 15.0.0 | MIT | cyclopts, foamlib |
| rich-rst | 2.2.0 | MIT | cyclopts |
| markdown-it-py | 4.2.0 | MIT (classifier) | rich |
| mdurl | 0.1.2 | MIT (classifier) | markdown-it-py |
| Pygments | 2.21.0 | BSD-2-Clause | rich |
| QtPy | 2.4.3 | MIT | pyvistaqt |
| pillow | 12.3.0 | MIT-CMU | matplotlib |
| contourpy | 1.4.0 | BSD-3-Clause | matplotlib |
| cycler | 0.12.1 | BSD (classifier) | matplotlib |
| fonttools | 4.67.0 | MIT | matplotlib |
| kiwisolver | 1.5.1 | BSD (classifier) | matplotlib |
| pyparsing | 3.3.3 | MIT | matplotlib |
| python-dateutil | 2.9.0.post0 | Apache-2.0 OR BSD-3-Clause (dual) | matplotlib |
| six | 1.17.0 | MIT | python-dateutil |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | matplotlib, pooch, QtPy |
| platformdirs | 4.13.0 | MIT | pooch |
| requests | 2.34.2 | Apache-2.0 | pooch |
| urllib3 | 2.8.0 | MIT | requests |
| idna | 3.20 | BSD-3-Clause | requests |
| charset-normalizer | 3.5.2 | MIT | requests |
| certifi | 2026.7.22 | MPL-2.0 | requests |
| aioshutil | 1.6 | BSD (classifier) | foamlib |
| multicollections | 1.2.0 | Apache-2.0 | foamlib |

## External programs (not bundled)

| Program | Licence | Use |
|---|---|---|
| OpenFOAM ESI v2606 | GPL-3.0-or-later | the solver and mesher, run as separate processes (D-001, D-004); installed by the user from the ESI packages |
| ParaView (optional, not installed by VortexCFD: Ubuntu package or Windows) | BSD-3-Clause | "Open in ParaView" starts it on a case (D-055, D-138) |

To refresh: `.venv/bin/pip freeze --exclude-editable`; the licence fields are in each package's
`*.dist-info/METADATA`.

## Licence review for v1 (prepared for the owner; not legal advice)

Against GPL-3.0-or-later, no dependency was found that is **incompatible**. Points to confirm:

1. **foamlib is GPL-3.0-only.** Compatible, but a distribution of VortexCFD together with foamlib can only be
   offered under GPL-3.0 (version 3 exactly), not under a later GPL version. VortexCFD's own files can stay
   "or later".
2. **pymeshfix is AGPL-3.0.** GPL-3.0 section 13 allows combining it with AGPL-3.0 code; the combination must then
   keep AGPL-3.0's terms for pymeshfix, whose section 13 (offering the source to users interacting over a network)
   does not apply to a desktop application used locally (D-074). If the repository is made public and the app
   distributed, this stays true; it would matter for a hosted or remote-access version.
3. **Qt: PySide6_Essentials only** (D-139, QUESTIONS 213). The PySide6 meta-package (which also installed
   PySide6_Addons, PySide6_Pdf and PySide6_WebEngine with Chromium) is no longer a dependency; the app uses only
   modules of PySide6_Essentials. Qt's LGPL-3.0 libraries are used as shared libraries from the wheel, which LGPL
   allows with GPL-3.0 code.
4. **MPL-2.0 (pytetwild, fTetWild, certifi).** MPL-2.0 is compatible with GPL-3.0 through its secondary-licence
   clause unless a file is marked "Incompatible With Secondary Licenses"; no such notice was looked for in their
   sources (not checked: to confirm).
5. **Apache-2.0 (cadquery-ocp, requests, cyclopts, multicollections)** is compatible with GPL-3.0 (not with
   GPL-2.0). OpenCASCADE's LGPL-2.1 with its exception is compatible.
6. **OpenFOAM** runs as a separate program and is installed by the user; VortexCFD does not distribute it.
