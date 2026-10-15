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
- **Python**: 3.12
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
  - Must **NOT** import Qt (`PySide6`), `pyvista`, `pyvistaqt`, or anything GUI-related.
  - Must **NOT** import `cfdgui.gui`.
- **`foam/`**:
  - Handles OpenFOAM integration (case generation/writing, process execution, log parsing).
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
Refer to `docs/PLAN.md` section 0 for the governing principles:

### Scope Principles
- OpenFOAM remains the numerical solver backend. The GUI orchestrates it via subprocesses. Solvers are not forked or rewritten unless explicitly mandated by a phase.
- Reuse before build: every module starts with an evaluation of existing tools.
- Plain OpenFOAM numerical behaviour is not re-validated. Anything added or modified numerically (custom mesher, layer extrusion, new boundary conditions, custom turbulence setup logic, solver variant) requires a simple validation case before it is considered done.

### Validation Policy
| What changed | Minimum validation |
|---|---|
| GUI / templates only (reproduces a known OpenFOAM setup) | Generated case must match a hand-written reference case dictionary-by-dictionary (diff test) |
| Mesher / layers | Benchmark suite (Phase 5.0): `checkMesh` metrics, layer coverage, y+ distribution |
| Turbulence setup logic (k, omega, nut, wall treatment) | Flat plate (Cf, y+) |
| New/modified solver, BC or numerics | Lid-driven cavity and/or NACA 0012 vs reference data |
| Moving mesh feature | Simple prescribed-motion case with known behaviour |

### Agent Workflow (Antigravity implements, Claude reviews)
- Everything lives in a Git repository. One branch per task, small PRs (< ~400 changed lines).
- Each task defines: Goal, Deliverables, Acceptance criteria. A task is done only when acceptance criteria pass in CI/pytest.
- Tasks tagged `[NUMERICS-REVIEW]` must be reviewed by Claude/Vic before merge (units, BCs, wall treatment, schemes).
- The agent must stop and ask if a task requires an architectural change not in `ARCHITECTURE.md`.
- Keep `ARCHITECTURE.md`, `DECISIONS.md`, and agent rules files updated whenever an interface changes.
- Code and documentation must be written in English.

## 9. Open Questions
1. Repository visibility (public vs. private) and GUI license selection (from `docs/PLAN.md` Section 0).
2. Long-term solver backend abstraction: whether to keep the backend open for alternative solvers (e.g., SU2) or remain strictly OpenFOAM-only (from `docs/PLAN.md` Section 0).
3. Launcher script implementation details for setting `GALLIUM_DRIVER=d3d12` and `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` (entry point wrapper vs. shell script vs. runtime environment bootstrap).
