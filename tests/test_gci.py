"""foam/gci.py: the Celik et al. (2008) procedure against the paper's worked example and synthetic
monotonic, oscillatory and divergent cases."""

import math

import pytest

from vortexcfd.foam.gci import DIVERGENT, MONOTONIC, OSCILLATORY, OSCILLATORY_TEXT, UNDEFINED, cell_size, celik_gci, study


def test_celik_2008_worked_example() -> None:
    """Celik et al. 2008, Table 1, first column (monotonic): N = 18000, 8000, 4500 (2D), so
    r21 = 1.5 and r32 = sqrt(8000 / 4500) = 1.333; phi = 6.063, 5.972, 5.863. The paper gives
    p = 1.53, phi_ext^21 = 6.1685, e_a^21 = 1.5 %, e_ext^21 = 1.7 %, GCI_fine^21 = 2.2 %
    (an independent reproduction, github.com/oscar-monsalve/GCI, prints p 1.5340,
    phi_ext 6.1685, GCI_fine 2.1750 %, GCI_medium 4.1129 %)."""
    r = celik_gci(6.063, 5.972, 5.863, 1.5, math.sqrt(8000 / 4500))
    assert r.convergence == MONOTONIC and r.applicable
    assert r.order == pytest.approx(1.5340, abs=5e-5)
    assert r.extrapolated == pytest.approx(6.1685, abs=5e-5)
    assert r.approx_error == pytest.approx(0.015, abs=5e-4)
    assert r.extrapolated_error == pytest.approx(0.017, abs=5e-4)
    assert r.gci_fine == pytest.approx(0.021750, abs=5e-6)
    assert r.gci_medium == pytest.approx(0.041129, abs=5e-6)
    assert r.in_asymptotic_range  # 1.015
    assert r.text == "GCI 2.17 %"


def test_celik_2008_oscillatory_column_gets_no_number() -> None:
    """Table 1, third column: phi = 6.0042, 5.9624, 6.0909, the differences change sign."""
    r = celik_gci(6.0042, 5.9624, 6.0909, 1.5, math.sqrt(8000 / 4500))
    assert r.convergence == OSCILLATORY and not r.applicable
    assert r.order is None and r.gci_fine is None and r.extrapolated is None
    assert r.text == OSCILLATORY_TEXT == "oscillatory, GCI not applicable"


@pytest.mark.parametrize("p, r21, r32", [(2.0, math.sqrt(2), math.sqrt(2)), (1.0, 2.0, 1.5), (1.6, 1.3, 1.7)])
def test_exact_power_law_recovers_order_and_limit(p: float, r21: float, r32: float) -> None:
    def phi(h: float) -> float:
        return 0.3 - 0.05 * h**p

    h1 = 0.01
    r = celik_gci(phi(h1), phi(h1 * r21), phi(h1 * r21 * r32), r21, r32)
    assert r.convergence == MONOTONIC
    assert r.order == pytest.approx(p, rel=1e-8) and r.extrapolated == pytest.approx(0.3, rel=1e-10)
    assert r.gci_fine == pytest.approx(1.25 * abs((phi(h1) - 0.3) / phi(h1)), rel=1e-6)


def test_differences_growing_with_refinement_are_divergent() -> None:
    assert celik_gci(1.0, 1.2, 1.3, 2.0, 2.0).convergence == DIVERGENT
    assert celik_gci(1.0, 1.0, 1.3, 2.0, 2.0).convergence == UNDEFINED
    assert "GCI not applicable" in celik_gci(1.0, 1.2, 1.3, 2.0, 2.0).text


def test_study_sorts_by_cell_size_and_cell_size_formula() -> None:
    def phi(h: float) -> float:
        return 1.0 + h**2

    sizes = [0.2, 0.1, 0.1 * math.sqrt(2)]
    r = study([phi(h) for h in sizes], sizes)
    assert r.order == pytest.approx(2.0, rel=1e-8) and r.extrapolated == pytest.approx(1.0, rel=1e-10)
    assert cell_size(8.0, 1000) == pytest.approx(0.2)
    with pytest.raises(ValueError):
        celik_gci(1, 2, 3, 1.0, 2.0)
    with pytest.raises(ValueError):
        study([1, 2], [1, 2])
