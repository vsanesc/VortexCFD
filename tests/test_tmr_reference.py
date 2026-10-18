"""The TMR reference data and the Celik grid-convergence procedure used by the flat plate validation."""

import pytest

from tests.validation.tmr import (
    X_REF,
    celik_gci,
    cf_plate,
    incompressible_reference,
    read_zones,
    verdict,
    DATA,
)


def test_celik_procedure_reproduces_the_published_cfl3d_numbers() -> None:
    # flatplate_sst.html: CFL3D, three finest grids: p 1.21, e_a 0.292 %, e_ext 0.221 %, GCI 0.277 %.
    g = celik_gci(0.269085355e-2, 0.268299226e-2, 0.266477116e-2, 2.0, 2.0)
    assert g.applicable
    assert g.order == pytest.approx(1.21, abs=0.005)
    assert g.approx_error == pytest.approx(0.00292, abs=5e-6)
    assert g.extrapolated_error == pytest.approx(0.00221, abs=5e-6)
    assert g.gci_fine == pytest.approx(0.00277, abs=5e-6)


def test_celik_order_with_unequal_ratios_and_oscillation() -> None:
    # Exact second-order data with r21 = 2, r32 = 1.5: p = 2 and the exact limit is recovered.
    phi = lambda h: 1.0 + 0.3 * h**2  # noqa: E731
    g = celik_gci(phi(1.0), phi(2.0), phi(3.0), r21=2.0, r32=1.5)
    assert g.order == pytest.approx(2.0, rel=1e-9) and g.extrapolated == pytest.approx(1.0, rel=1e-12)
    assert celik_gci(1.0, 1.1, 1.05, 2.0, 2.0).convergence == "oscillatory"


def test_reference_files_and_values() -> None:
    zones = read_zones(DATA / "cf_incomp_results_sstv.dat")
    assert len(zones) == 3 and all(len(rows) == 5 for rows in zones.values())
    finest, extrapolated = incompressible_reference()
    assert finest == pytest.approx(2.7165e-3, rel=1e-4) and extrapolated == pytest.approx(2.7214e-3, rel=1e-4)
    x, cf = cf_plate("CFL3D")
    assert x[0] == 0.0 and 1.98 < x[-1] <= 2.0 and all(c > 0 for c in cf[1:])
    i = min(range(len(x)), key=lambda j: abs(x[j] - X_REF))
    assert cf[i] == pytest.approx(2.69e-3, rel=0.01)  # the compressible finest-grid value at x = 0.97


@pytest.mark.parametrize("error, band", [(0.0, "PASS"), (-0.03, "PASS"), (0.031, "PASS WITH NOTE"),
                                         (-0.05, "PASS WITH NOTE"), (0.051, "FAIL"), (-0.11, "FAIL")])
def test_verdict_bands(error: float, band: str) -> None:
    assert verdict(error) == band


def test_committed_study_is_consistent_with_its_verdict_and_the_readme() -> None:
    from tests.validation import flat_plate_report as report

    study = report.load_study()
    again = report.grid_study(study["grids"])
    assert again["verdict"] == study["verdict"] and again["extrapolated"] == pytest.approx(study["extrapolated"])
    assert [g["cells_normal"] for g in study["grids"]] == [128, 256, 512]
    readme = (report.OUT / "README.md").read_text()
    assert report.replace_block(readme, "grid study", report.study_tables(study)) == readme
    assert report.replace_block(readme, "k wall", report.k_wall_table(study)) == readme


def test_replace_block_needs_the_markers() -> None:
    from tests.validation.flat_plate_report import replace_block

    text = "a\n<!-- BEGIN generated: x -->\nold\n<!-- END generated: x -->\nb\n"
    assert replace_block(text, "x", "new") == "a\n<!-- BEGIN generated: x -->\nnew\n<!-- END generated: x -->\nb\n"
    with pytest.raises(ValueError):
        replace_block(text, "y", "new")
