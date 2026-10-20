"""The flat-plate validation grids under the cell-centre y+ convention (D-107, docs/QUESTIONS.md item 150).

Fast (no OpenFOAM run): the case now asks for y+ 1 at the first cell centre; the recorded study asked for 2
with the target distance as the cell height. Both give the same first cells, so the recorded validation
(docs/validation/flat_plate/, PASS WITH NOTE) applies by construction.
"""

import pytest

from tests.validation import flat_plate_report as report
from tests.validation.flat_plate_case import CASE_A, CASE_B_GRIDS, first_cell_height
from vortexcfd.foam.yplus import first_layer_thickness

RELATIVE = 1e-9


def test_case_b_first_cells_equal_the_recorded_study() -> None:
    recorded = report.load_study()["grids"]
    assert [g.cells_normal for g in CASE_B_GRIDS] == [r["cells_normal"] for r in recorded] == [128, 256, 512]
    for grid, row in zip(CASE_B_GRIDS, recorded):
        assert first_cell_height(grid) == pytest.approx(row["first_cell_m"], rel=RELATIVE)


def test_case_a_first_cell_equals_the_cell_height_rule_at_target_2() -> None:
    assert CASE_A.yplus_target == 1.0
    old = first_layer_thickness(2.0, CASE_A.speed, CASE_A.nu, CASE_A.yplus_length, "cell_height")
    assert first_cell_height(CASE_A) == pytest.approx(old, rel=RELATIVE)
    assert old == pytest.approx(7.2e-5, rel=0.01)  # the value in the validation README
