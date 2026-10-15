# DECISIONS.md

## Architecture Decisions Log

| ID | Date | Decision | Reason |
|---|---|---|---|
| D-001 | 2026-10-15 | OpenFOAM ESI v2606 only | Target OpenFOAM ESI v2606 exclusively, installed at `/usr/lib/openfoam/openfoam2606`. Avoids version divergence, dialect differences, and maintenance burden across multiple OpenFOAM forks and versions during initial phases. |
| D-002 | 2026-10-15 | Run inside WSL + WSLg | Run the entire application inside WSL2 Ubuntu 24.04 and display on Windows 11 via WSLg. Avoids cross-OS filesystem translation overhead between Windows and Linux while leveraging native Linux solver performance and WSLg Mesa d3d12 hardware-accelerated 3D rendering. |
| D-003 | 2026-10-15 | Three-layer package structure | Enforce a strict three-layer architecture under `src/cfdgui/`: `core/` (simulation data model), `foam/` (OpenFOAM integration), and `gui/` (PySide6 / PyVista). `core` and `foam` must never import `gui`. Ensures decoupling, enabling headless simulation execution and clean testing without GUI dependencies. |
| D-004 | 2026-10-15 | OpenFOAM always launched via explicit sourcing | Never assume OpenFOAM binaries or environment variables are on `PATH`. Every OpenFOAM process is launched through `cfdgui.foam.runner`, which explicitly sources `/usr/lib/openfoam/openfoam2606/etc/bashrc`. Guarantees deterministic, reproducible execution across all environments regardless of user shell configuration. |

---

## Detailed Records

### D-001
- **ID**: D-001
- **Date**: 2026-10-15
- **Decision**: OpenFOAM ESI v2606 only (installed at `/usr/lib/openfoam/openfoam2606`).
- **Reason**: Target OpenFOAM ESI v2606 exclusively to establish a stable, modern, and standardized solver baseline, avoiding version fragmentation, incompatible dictionary formats, and overhead across multiple OpenFOAM forks during development.

### D-002
- **ID**: D-002
- **Date**: 2026-10-15
- **Decision**: Run inside WSL + WSLg (WSL2 Ubuntu 24.04 on Windows 11).
- **Reason**: Avoids path-translation friction, filesystem overhead, and IPC complexity across Windows and Linux. The solver runs natively on Linux while the GUI seamlessly integrates into Windows 11 via WSLg and Mesa d3d12 GPU hardware acceleration.

### D-003
- **ID**: D-003
- **Date**: 2026-10-15
- **Decision**: Three-layer package structure (`core/`, `foam/`, `gui/`).
- **Reason**: Enforces strict separation of concerns. `core` encapsulates simulation data structures without UI dependencies; `foam` handles OpenFOAM case construction and process execution; `gui` handles presentation. Forbidding `core` and `foam` from importing `gui` ensures headless execution, automated batch workflows, and fast CI testing.

### D-004
- **ID**: D-004
- **Date**: 2026-10-15
- **Decision**: OpenFOAM always launched via explicit sourcing.
- **Reason**: OpenFOAM environment variables are complex and shell-dependent. Sourcing `/usr/lib/openfoam/openfoam2606/etc/bashrc` explicitly inside `cfdgui.foam.runner` ensures that OpenFOAM never needs to be on `PATH` and execution is 100% deterministic regardless of the user's login shell or environment.
