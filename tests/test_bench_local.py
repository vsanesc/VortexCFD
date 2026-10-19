"""Local-only benchmark cases (D-094): the config loader, the reference analysis on a small synthetic
two-solid model, the fidelity metrics and the local report. No OpenFOAM run; the owner's geometry is
never used here."""

import json
from pathlib import Path

import numpy as np
import pytest

from vortexcfd.bench import metrics, report
from vortexcfd.bench.cases import CASES
from vortexcfd.bench.local import LocalConfigError, load_local_cases


def _write_step(path: Path, shape) -> Path:
    from vortexcfd.bench.geometries import _write_step as write

    return write(shape, path)


@pytest.fixture(scope="module")
def plane_model(tmp_path_factory) -> Path:
    """A synthetic "aircraft": a fuselage box 4 x 1 x 1 m and a wing box (chord 1 m, span 6 m,
    0.2 m thick) through it, as two overlapping solids in one STEP file (millimetres)."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from OCP.gp import gp_Pnt

    fuselage = BRepPrimAPI_MakeBox(gp_Pnt(0, -500, -500), gp_Pnt(4000, 500, 500)).Shape()
    wing = BRepPrimAPI_MakeBox(gp_Pnt(1500, -3000, -100), gp_Pnt(2500, 3000, 100)).Shape()
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, fuselage)
    builder.Add(compound, wing)
    return _write_step(tmp_path_factory.mktemp("plane") / "plane.step", compound)


def _config(tmp_path: Path, model: Path, **extra) -> Path:
    data = {
        "format_version": 1,
        "reference": {"file": str(model), "components": {"fuselage": 0, "wing": 1},
                      "l_ref": {"mean_chord": "wing"},
                      "zones": {"band": 0.05, "junctions": {"wing_junction": "wing"}, "trailing_edge": "wing",
                                "tips": "wing"}},
        "defaults": {"import_mode": "parts", "inflow": {"speed": 30.0}, "mesh": {"target_surface_size": 0.1}},
        "cases": [{"name": "plane_ref", "file": str(model), "solve": True},
                  {"name": "plane_union", "file": str(model), "surface_prep": "cad_union", "mesh": {"curvature_levels": 0}},
                  {"name": "plane_missing", "file": str(tmp_path / "nowhere.step")}],
        **extra,
    }
    path = tmp_path / "local_cases.json"
    path.write_text(json.dumps(data))
    return path


def test_missing_config_gives_no_cases_and_a_message(tmp_path: Path) -> None:
    cases, messages = load_local_cases(tmp_path)
    assert cases == {} and len(messages) == 1 and "not found" in messages[0]


def test_config_cases_merge_defaults_and_skip_missing_geometry(tmp_path: Path, plane_model: Path) -> None:
    cases, messages = load_local_cases(tmp_path, _config(tmp_path, plane_model))
    assert set(cases) == {"plane_ref", "plane_union"}
    assert messages == [f"local case plane_missing skipped: geometry file {tmp_path / 'nowhere.step'} not found"]
    ref, union = cases["plane_ref"], cases["plane_union"]
    assert ref.local and ref.solve and ref.import_mode == "parts" and ref.surface_prep is None
    assert ref.inflow == {"speed": 30.0} and ref.mesh == {"target_surface_size": 0.1}
    assert union.mesh == {"target_surface_size": 0.1, "curvature_levels": 0} and not union.solve
    assert union.surface_prep == "cad_union" and union.reference == str(plane_model)
    assert union.reference_spec["components"] == {"fuselage": 0, "wing": 1}


@pytest.mark.parametrize("bad", [{"format_version": 2}, {"cases": [{"name": "sphere", "file": "x"}]},
                                 {"cases": [{"name": "a", "file": "x", "surface_prep": "magic"}]}])
def test_invalid_configs_are_refused(tmp_path: Path, plane_model: Path, bad: dict) -> None:
    path = _config(tmp_path, plane_model)
    data = {**json.loads(path.read_text()), **bad}
    path.write_text(json.dumps(data))
    with pytest.raises(LocalConfigError):
        load_local_cases(tmp_path, path)
    assert "sphere" in CASES  # public names are reserved


@pytest.fixture(scope="module")
def plane_reference(plane_model: Path, tmp_path_factory):
    """The synthetic model's reference analysis, split to 1e-3 of the diagonal (7 mm) to keep the test
    fast, through the cache (the second call reads it back)."""
    from vortexcfd.bench import reference

    cache = tmp_path_factory.mktemp("cache")
    args = (plane_model, {"fuselage": 0, "wing": 1},
            {"band": 0.05, "junctions": {"wing_junction": "wing"}, "trailing_edge": "wing", "tips": "wing"},
            {"mean_chord": "wing"}, cache)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(reference, "SPLIT_FRACTION", 1e-3)
        first = reference.cached_reference(*args)
        assert len(list(cache.iterdir())) == 1
        mp.setattr(reference, "load_reference", lambda *a: pytest.fail("not read from the cache"))
        again = reference.cached_reference(*args)
    assert again.skin.n_cells == first.skin.n_cells and again.l_ref == first.l_ref
    return again


def test_reference_skin_curves_chord_and_zones(plane_reference) -> None:
    ref = plane_reference
    assert ref.l_ref == pytest.approx(1.0, rel=1e-6)  # the wing box's chord
    # outer skin: fuselage 2*(4*1)*2 + 2*1*1 minus the wing's two 1 x 0.2 holes; wing outside the fuselage
    fuselage = 4 * 4.0 + 2 * 1.0 - 2 * 0.2
    wing = 2 * (5.0 * 1.0) + 2 * (5.0 * 0.2) + 2 * (1.0 * 0.2)
    assert ref.skin.area == pytest.approx(fuselage + wing, rel=2e-3)  # split to 7 mm along 9.6 m of curves
    # the intersection curves: two rectangles 1 x 0.2 m (perimeter 2.4 m each) on the fuselage sides
    (pair, segments), = ref.curves.items()
    assert pair == (0, 1)
    assert np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1).sum() == pytest.approx(4.8, rel=1e-6)
    names = [z.name for z in ref.zones]
    assert names == ["wing_junction", "trailing_edge", "tips"]
    te = ref.zones[1]
    assert te.segments and all(abs(a[0] - 2.5) < 1e-6 and abs(abs(a[1]) - 0.5) >= -1e-9 for a, _b in te.segments)
    assert all(abs(a[1]) >= 0.5 - 1e-6 for a, _b in te.segments)  # outside the fuselage only
    inside = ref.inside_any(np.array([[2.0, 0.0, 0.0], [2.0, 2.0, 0.0], [2.0, 4.0, 0.0]]))
    assert inside.tolist() == [True, True, False]


def test_reference_fidelity_point_sizes_and_far_share() -> None:
    d = np.array([0.0, 0.001, 0.004])
    size = np.array([0.01, 0.01, 0.006])
    f = metrics.reference_fidelity(d, size)
    assert f["max_mm"] == pytest.approx(4.0) and f["rms_mm"] == pytest.approx(1000 * np.sqrt((1e-6 + 16e-6) / 3))
    assert f["far_percent"] == pytest.approx(100 / 3)  # only 4 mm > 0.5 x 6 mm
    assert metrics.reference_fidelity(np.zeros(0), np.zeros(0))["max_mm"] is None
    faces = np.array([[0, 1, 2, -1], [0, 2, 3, 4]])
    sizes = metrics.point_sizes(np.zeros((6, 3)), faces, np.array([4.0, 16.0]))
    assert sizes.tolist() == [3.0, 2.0, 3.0, 4.0, 4.0, 0.0]


def test_force_partition_needs_disjoint_patches_with_faces() -> None:
    parts = {"Body": ("front", "body"), "Ball": ("Ball",)}
    total = ("front", "body", "Ball")
    ok = metrics.force_partition(parts, total, {"front": 3, "body": 5, "Ball": 2}, {"front": 1.0, "body": 2.0, "Ball": 0.5})
    assert ok["ok"] and ok["parts_area_m2"] == ok["total_area_m2"] == 3.5
    bad = metrics.force_partition({"Body": ("front", "body"), "Ball": ("Ball", "body")}, total,
                                  {"front": 3, "body": 5, "Ball": 0}, {})
    assert not bad["ok"]
    assert "patch body is in both Body and Ball" in bad["problems"] and "patch Ball of Ball has no faces" in bad["problems"]
    missing = metrics.force_partition({"Body": ("front",)}, total, {"front": 1, "body": 1, "Ball": 1}, {})
    assert not missing["ok"] and "patch body is in the total but in no part" in missing["problems"]


def test_zone_mask_with_many_segments_matches_the_loop() -> None:
    rng = np.random.default_rng(1)
    pts = rng.uniform(-1, 1, (500, 3))
    t = np.linspace(0, 2 * np.pi, 200)
    ring = np.c_[np.cos(t), np.sin(t), np.zeros_like(t)] * 0.5
    segments = tuple((tuple(a), tuple(b)) for a, b in zip(ring[:-1], ring[1:]))
    fast = metrics.zone_mask(pts, segments=segments, width=0.1)
    slow = np.zeros(len(pts), dtype=bool)
    for a, b in segments:
        slow |= metrics.point_segment_distance(pts, a, b) <= 0.1
    assert len(segments) > metrics.LOCATOR_SEGMENTS and (fast == slow).all() and fast.any()


def test_local_report_table() -> None:
    case = {"case": "plane_ref", "description": "d", "cells": 1000, "quality": {"failed_checks": 0},
            "reference_fidelity": {"mesh_to_reference": {"rms_mm": 1.5, "max_mm": 9.0, "far_percent": 2.0},
                                   "reference_to_mesh": {"rms_mm": 2.0, "max_mm": 30.0, "far_percent": 5.0},
                                   "internal": {"points": 0, "area_m2": 0.0},
                                   "zones": {"wing_junction": {"mesh_to_reference": {"rms_mm": 3.0}}}},
            "patch_faces": {"a": 10, "b": 0}, "force_partition": {"ok": True, "problems": []},
            "surface_prep": {"time_s": 4.2, "report": [("Strategy", "CAD union")]}}
    result = {"meta": {"local": True, "stamp": "x"}, "cases": [case]}
    table = report.local_table(result)
    assert "| plane_ref | ok | 1000 | 0 |" in table and "| 1/2 | ok | 4.2 |" in table
    assert "| plane_ref | wing_junction | - | 3 |" in report.local_zone_table(result)
    text = report.markdown_report(result)
    assert text.startswith("# Local benchmark cases") and "preparation: Strategy: CAD union" in text
