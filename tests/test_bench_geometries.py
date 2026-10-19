"""Benchmark geometries and case definitions (D-081): dimensions, closed solids, byte-identical files."""

import hashlib
from pathlib import Path

import numpy as np
import pytest

from vortexcfd.bench import cases, geometries
from vortexcfd.geometry.cad import read_cad, tessellate
from vortexcfd.geometry.loader import load_surface


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_naca_section_and_ahmed_dimensions() -> None:
    x = np.linspace(0, 1, 101)
    t = 2 * geometries.naca_half_thickness(x)
    assert t[0] == 0.0 and t[-1] == pytest.approx(0.0025)
    assert t.max() == pytest.approx(0.12, abs=2e-4) and x[np.argmax(t)] == pytest.approx(0.30, abs=0.01)
    s = geometries.ahmed_slant_points()
    assert s["x_start"] == pytest.approx(1044 - 222 * np.cos(np.radians(25)))
    assert s["z_rear"] == pytest.approx(288 - 222 * np.sin(np.radians(25)))


@pytest.mark.parametrize("name", ["sphere", "wing", "ahmed"])
def test_geometries_are_closed_deterministic_and_to_size(tmp_path: Path, name: str) -> None:
    first = geometries.ensure_geometry(name, tmp_path / "a")
    second = geometries.ensure_geometry(name, tmp_path / "b")
    assert _digest(first) == _digest(second)  # byte-identical from run to run
    if name == "sphere":
        mesh = load_surface(first, "m")
        assert mesh.bounds == pytest.approx((-0.5, 0.5, -0.5, 0.5, -0.5, 0.5), abs=1e-4)  # facets inside
        assert mesh.volume == pytest.approx(np.pi / 6, rel=1e-3)
    else:
        model = read_cad(first)
        assert model.units == "mm" and len(model.bodies) == 1 and model.bodies[0].name == name
        mesh = tessellate(model, 1e-4 * model.diagonal, 5.0)
        if name == "wing":  # NACA 0012 area 0.0822 c^2 (with the 0.25 % trailing edge), span 3 m
            assert mesh.bounds == pytest.approx((0, 1000, 0, 3000, -60.1, 60.1), abs=0.2)
            assert mesh.volume == pytest.approx(0.08217 * 1000**2 * 3000, rel=2e-3)
        else:  # the box minus the slant wedge minus the four front fillets; at each front corner the
            # two fillets overlap by the integral of (r - sqrt(r^2 - u^2))^2 over [0, r] = r^3 (5/3 - pi/2)
            s = geometries.ahmed_slant_points()
            r = 100.0
            box = 1044 * 389 * 288 - 0.5 * (1044 - s["x_start"]) * (288 - s["z_rear"]) * 389
            expected = box - (1 - np.pi / 4) * r**2 * (2 * 389 + 2 * 288) + 4 * r**3 * (5 / 3 - np.pi / 2)
            assert mesh.bounds == pytest.approx((0, 1044, -194.5, 194.5, 0, 288), abs=0.05)
            assert mesh.volume == pytest.approx(expected, rel=2e-3)
    assert mesh.n_open_edges == 0


def test_case_deviations_list_the_y_plus_run_settings() -> None:
    lines = cases.deviations(cases.CASES["wing"], cores=4)
    assert any("iterations" in line and "fixed" in line for line in lines)
    assert any(line.startswith("solvers.cores = 4") for line in lines)
    assert {z.name for z in cases.CASES["wing"].zones} == {"trailing_edge", "tips"}
    assert {z.name for z in cases.CASES["ahmed"].zones} == {"slant_edges", "rear_edges"}
    assert all(not c.mesh and not c.inflow and not c.domain for c in cases.CASES.values())  # app defaults
