"""Domain extents in m or mm (D-157, QUESTIONS 226): stored with their unit, a fixed length when L changes; extents in
L stay relative; older projects (every extent in L) migrate unchanged."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Domain, Simulation
from vortexcfd.core.presets import BUILTIN_PRESETS, preset_description
from vortexcfd.core.project_io import load_simulation, migrate, save_simulation
from vortexcfd.geometry.domain import compute_domain


def test_extents_in_metres_millimetres_or_l() -> None:
    d = Domain(upstream=2.5, downstream=800.0, units={"upstream": "m", "downstream": "mm", "lateral": "L"})
    assert d.units == {"upstream": "m", "downstream": "mm"}  # an "L" entry is the default: dropped
    assert d.extent_unit("upstream") == "m" and d.extent_unit("lateral") == "L"
    assert d.extent_m("upstream", 4.0) == 2.5  # metres: L does not matter
    assert d.extent_m("downstream", 4.0) == pytest.approx(0.8)
    assert d.extent_m("lateral", 4.0) == 20.0  # 5 L
    with pytest.raises(ValidationError, match="unknown domain extent"):
        Domain(units={"sideways": "m"})
    with pytest.raises(ValidationError):
        Domain(units={"upstream": "cm"})


def _box(sim: Simulation, size: float):
    """The domain box around one cube part of edge ``size`` (L = size)."""
    return compute_domain([(0.0, size, 0.0, size, 0.0, size)], sim.domain)


def test_a_length_in_metres_stays_when_l_changes() -> None:
    sim = Simulation(name="s")
    sim.domain = Domain(upstream=3.0, units={"upstream": "m"})
    small, big = _box(sim, 1.0), _box(sim, 2.0)
    assert small.bounds[0] == pytest.approx(-3.0) and big.bounds[0] == pytest.approx(-3.0)  # fixed: 3 m
    assert small.bounds[1] == pytest.approx(1.0 + 10.0) and big.bounds[1] == pytest.approx(2.0 + 20.0)  # 10 L


def test_older_projects_keep_every_extent_in_l(tmp_path: Path) -> None:
    old = {"schema_version": 22, "name": "s", "domain": {"upstream": 4.0}}
    data = migrate(old)
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION == 25
    sim = Simulation.model_validate(data)
    assert sim.domain.upstream == 4.0 and sim.domain.units == {}
    sim.domain = Domain(upstream=1.5, units={"upstream": "m"})
    path = tmp_path / "p.json"
    save_simulation(sim, path)
    assert json.loads(path.read_text())["domain"]["units"] == {"upstream": "m"}
    assert load_simulation(path).domain.extent_unit("upstream") == "m"


def test_a_preset_description_names_the_units() -> None:
    preset = BUILTIN_PRESETS[0].model_copy(deep=True)
    assert "5 L upstream" in preset_description(preset)
    preset.domain = Domain(upstream=2.0, units={"upstream": "m"})
    assert "2 m upstream" in preset_description(preset)


def test_a_preset_keeps_the_units() -> None:
    from vortexcfd.core.presets import apply_preset, preset_from_simulation

    sim = Simulation(name="s")
    sim.domain = Domain(upstream=2.0, units={"upstream": "m"})
    preset = preset_from_simulation(sim, "Fixed inlet")
    assert preset.domain.units == {"upstream": "m"}
    assert apply_preset(Simulation(name="t"), preset).domain.extent_m("upstream", 9.0) == 2.0
