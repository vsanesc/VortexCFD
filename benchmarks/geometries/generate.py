"""Regenerate the benchmark geometries into this folder (D-081): sphere.stl, wing.step, ahmed.step.

The generators live in src/vortexcfd/bench/geometries.py; the files are git-ignored and byte-identical
from run to run. ``python -m vortexcfd.bench`` generates a missing file by itself.

    .venv/bin/python benchmarks/geometries/generate.py
"""

from pathlib import Path

from vortexcfd.bench.geometries import GEOMETRIES, ensure_geometry

if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    for name in GEOMETRIES:
        print(ensure_geometry(name, here, force=True))
