# ARCHITECTURE.md

## 1. Overview and Target
`cfdgui` is a Python-based desktop application providing a STAR-CCM+-style workflow (single simulation tree, integrated geometry → mesh → physics → solve → post-processing) orchestrating OpenFOAM as its numerical backend.

## 2. Runtime Environment
- The entire application runs inside **WSL2** running **Ubuntu 24.04**.
- The graphical user interface is displayed on the host operating system (**Windows 11**) via **WSLg**.

## 3. Numerical Backend
- **OpenFOAM ESI v2606 only**, installed at `/usr/lib/openfoam/openfoam2606`.
- OpenFOAM is **never assumed to be on `PATH`**.
- Every OpenFOAM process is launched through `cfdgui.foam.runner`, which sources `/usr/lib/openfoam/openfoam2606/etc/bashrc` explicitly.

## 4. Technology Stack
- **Python**: >= 3.11 (developed on 3.12)
- **GUI Framework**: PySide6 (Qt)
- **3D Viewer / Visualization**: PyVista + pyvistaqt
- **Testing**: pytest + pytest-qt

## 5. Package Layers
All application code resides under `src/cfdgui/` and is strictly partitioned into three layers:

```
src/cfdgui/
├── core/   # Simulation data model
├── foam/   # OpenFOAM integration
└── gui/    # Presentation and 3D viewer
```

### Layer Constraints
- **`core/`**:
  - Encapsulates the simulation data model.
  - `core/model.py`: defines the simulation tree data models validated via Pydantic.
  - `core/project_io.py`: handles saving, loading, validation, and migration of JSON project files.
  - Must **NOT** import Qt (`PySide6`), `pyvista`, `pyvistaqt`, or anything GUI-related.
  - Must **NOT** import `cfdgui.gui`.
- **`foam/`**:
  - Handles OpenFOAM integration (case generation/writing, process execution, log parsing).
  - `foam/dictfile.py`: thin wrapper encapsulating `foamlib` for OpenFOAM dictionary reading and writing.
  - `foam/case_writer.py`: orchestrates writing complete OpenFOAM case directory trees from file dictionaries.
  - `foam/reference_cases/`: generators for standard reference cases (e.g. cavity).
  - `foam/runner.py`: process execution via `run_foam` and streaming runner `FoamRun` returning `RunResult`.
  - `foam/logparse.py`: incremental solver log parsing via `LogParser` recording `TimeStep` events.
  - Must **NOT** import Qt (`PySide6`) or anything GUI-related.
  - Must **NOT** import `cfdgui.gui`.
- **`gui/`**:
  - Implements UI components, main window, and 3D visualization using PySide6 and PyVista/pyvistaqt.
  - May import `core` and `foam`.
- **Enforcement Rule**: `core` and `foam` must never import `gui`. This guarantees that simulation data manipulation, case generation, and solver execution remain fully decoupled from the graphical user interface, enabling headless automation and CLI operation.

## 6. Simulation Outputs
- All simulation output directories, intermediate files, and temporary execution logs are written under `run/` at the repository root.
- The `run/` directory is git-ignored.

## 7. GPU Acceleration
- 3D rendering relies on WSLg + Mesa `d3d12`.
- A future launcher task will set the following environment variables if not already set:
  - `GALLIUM_DRIVER=d3d12`
  - `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA`
  *(Note: not implemented yet.)*

## 8. Validation Policy and Agent Workflow
Validation policy and agent workflow: see docs/PLAN.md section 0.

## 9. Results and ParaView
Simulation results are always stored as standard OpenFOAM cases (no app-specific result format), so any case produced by the app can be opened in ParaView. The app's own viewer is a convenience, not a replacement. An "Open in ParaView" button is planned for Phase 6 and is not implemented yet.

## 10. Open Questions
1. Long-term solver backend abstraction: whether to keep the backend open for alternative solvers (e.g., SU2) or remain strictly OpenFOAM-only.
2. Where user projects and simulation outputs live in the released app (run/ in the repo root is a development-only location).
3. Launcher script implementation details for setting `GALLIUM_DRIVER=d3d12` and `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA`.
