# DECISIONS.md

| ID | Date | Decision | Reason |
|---|---|---|---|
| D-001 | 2026-10-15 | OpenFOAM ESI v2606 only | Avoids supporting multiple OpenFOAM forks and version differences during development. |
| D-002 | 2026-10-15 | Run inside WSL + WSLg | Eliminates cross-OS filesystem translation overhead while providing Linux solver execution and hardware-accelerated rendering on Windows. |
| D-003 | 2026-10-15 | Three-layer package structure | Decouples simulation logic from the UI to allow headless execution and testing without Qt dependencies. |
| D-004 | 2026-10-15 | OpenFOAM always launched via explicit sourcing | Ensures deterministic execution regardless of the user's host shell environment or PATH configuration. |
| D-005 | 2026-10-15 | Results stored as standard OpenFOAM cases | Allows cases to be opened directly in ParaView without relying on an application-specific format. |
| D-006 | 2026-10-15 | Project file format: JSON, validated with pydantic, with schema_version | Provides human-readable versioned project files with schema validation and migration support. |
