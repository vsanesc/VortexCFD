"""Tests for geometry.domain.compute_domain with synthetic bounds."""

import pytest

from vortexcfd.core.model import Domain
from vortexcfd.geometry.domain import compute_domain, face_corners

WING = (0.0, 2.0, 0.0, 10.0, 0.0, 0.5)  # L = 10 m (span along y)


def test_box_from_multipliers_and_reference_length() -> None:
    box = compute_domain([WING], Domain())
    assert box.reference_length == 10.0
    assert box.bounds == (-50.0, 102.0, -50.0, 60.0, -50.0, 50.5)
    assert box.size == pytest.approx((152.0, 110.0, 100.5))
    assert not box.warnings


def test_reference_length_uses_the_union_of_all_parts() -> None:
    a = (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
    b = (4.0, 5.0, 0.0, 1.0, 0.0, 1.0)  # union extent along x is 5
    box = compute_domain([a, b], Domain(upstream=1, downstream=2, lateral=1, vertical=1))
    assert box.reference_length == 5.0
    assert box.bounds[:2] == (-5.0, 15.0)


def test_scaling_the_parts_scales_the_box() -> None:
    small = tuple(v * 0.001 for v in WING)  # the same part in mm converted to metres
    box = compute_domain([small], Domain())  # type: ignore[arg-type]
    ref = compute_domain([WING], Domain())
    assert box.reference_length == pytest.approx(ref.reference_length * 0.001)
    assert box.size == pytest.approx(tuple(s * 0.001 for s in ref.size))


def test_named_boundaries_without_symmetry() -> None:
    box = compute_domain([WING], Domain())
    assert list(box.boundaries) == ["inlet", "outlet", "sides", "top", "bottom"]
    assert box.boundaries["inlet"] == ((0, 0),) and box.boundaries["outlet"] == ((0, 1),)
    assert box.boundaries["sides"] == ((1, 0), (1, 1))
    assert box.boundaries["top"] == ((2, 1),) and box.boundaries["bottom"] == ((2, 0),)


def test_symmetry_starts_at_the_parts_y_min() -> None:
    box = compute_domain([WING], Domain(symmetry="y_min"))
    assert box.bounds[2] == 0.0 and box.bounds[3] == 60.0
    assert box.boundaries["symmetry"] == ((1, 0),)
    assert box.boundaries["sides"] == ((1, 1),)
    assert not box.warnings


def test_symmetry_warns_for_parts_away_from_the_plane() -> None:
    body = (0.0, 2.0, 0.0, 10.0, 0.0, 0.5)
    floating = (0.0, 1.0, 0.5, 2.0, 0.0, 0.5)  # y_min 0.5 > 1% of L (0.1)
    box = compute_domain([body, floating], Domain(symmetry="y_min"), names=["body", "pod"])
    assert len(box.warnings) == 1 and "pod" in box.warnings[0]
    near = (0.0, 1.0, 0.05, 2.0, 0.0, 0.5)  # within 1% of L
    assert not compute_domain([body, near], Domain(symmetry="y_min")).warnings
    assert not compute_domain([body, floating], Domain()).warnings  # only with symmetry


def test_no_parts_gives_a_warning_and_no_box() -> None:
    box = compute_domain([], Domain())
    assert box.bounds is None and box.reference_length == 0.0 and box.boundaries == {}
    assert "No parts" in box.warnings[0]


def test_face_corners() -> None:
    corners = face_corners((0, 2, 0, 4, 0, 6), 0, 1)  # x_max face
    assert {c[0] for c in corners} == {2.0}
    assert {(c[1], c[2]) for c in corners} == {(0.0, 0.0), (4.0, 0.0), (4.0, 6.0), (0.0, 6.0)}
