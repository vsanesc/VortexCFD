# CFD GUI

A Python-based GUI orchestrating OpenFOAM (ESI v2606) for CFD workflows.

## Getting Started

### Prerequisites

- Python >= 3.11
- OpenFOAM v2606 (installed at `/usr/lib/openfoam/openfoam2606` with `openfoam2606` launcher)

### Virtual Environment & Installation

1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   ```

2. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

3. Install the project in editable mode with development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

### Running Tests

Run the test suite with pytest:
```bash
pytest
```

To run only the OpenFOAM smoke tests:
```bash
pytest -m openfoam
```
