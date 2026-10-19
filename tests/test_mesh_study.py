"""Mesh independence study (D-066): level scaling of the mesh settings, the shared layer stack, the
record, the GCI rows, the CSV and the level sequence with fake runners."""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import pytest

from vortexcfd.core.model import Mesh
from vortexcfd.foam.mesh_case import MeshCaseInput, snappy_hex_mesh_dict
from vortexcfd.foam.mesh_estimate import estimate_mesh
from vortexcfd.foam.mesh_study import (
    LevelResult,
    StudyRecord,
    StudyRun,
    export_csv,
    level_factors,
    quantity_rows,
    read_record,
    reference_layers,
    scale_mesh,
    study_levels,
    write_record,
)
from vortexcfd.foam.solver_run import CRITERIA_MET, ITERATION_LIMIT, SolverRunResult

DOMAIN = (-5.0, 10.0, -5.0, 5.0, -5.0, 5.0)


def test_level_factors() -> None:
    r = math.sqrt(2)
    assert level_factors(r, "fine") == pytest.approx((2.0, r, 1.0))
    assert level_factors(r, "medium") == pytest.approx((r, 1.0, 1 / r))
    with pytest.raises(ValueError):
        level_factors(1.2, "fine")
    with pytest.raises(ValueError):
        level_factors(1.5, "coarse")


def test_levels_scale_cells_by_r_cubed_and_keep_the_surface_levels() -> None:
    """Each level divides the background cell budget by f^3 and multiplies the target surface size
    by f: base size and surface cells scale by f, the refinement levels stay the same."""
    mesh = Mesh()  # 100,000 cells, 0.01 L
    levels = study_levels(mesh, math.sqrt(2), "fine")
    assert [lv.name for lv in levels] == ["coarse", "medium", "fine"]
    assert [lv.mesh.background_cells_target for lv in levels] == [12_500, 35_355, 100_000]
    assert [lv.mesh.target_surface_size for lv in levels] == pytest.approx([0.02, 0.01 * math.sqrt(2), 0.01])
    est = [estimate_mesh(DOMAIN, 1.0, lv.mesh) for lv in levels]
    assert len({(e.level_min, e.level_max) for e in est}) == 1
    assert est[0].base_size / est[2].base_size == pytest.approx(2.0, rel=1e-3)
    assert est[1].surface_size / est[2].surface_size == pytest.approx(math.sqrt(2), rel=1e-3)
    medium = study_levels(mesh, 1.5, "medium")
    assert medium[1].mesh == mesh.model_copy(update={"background_cells_target": 100_000, "target_surface_size": 0.01})
    assert medium[2].mesh.background_cells_target == round(100_000 * 1.5**3)
    # an explicit base size scales too; explicit levels are kept
    fixed = Mesh(base_size=0.2, surface_level_min=3, surface_level_max=4)
    coarse = scale_mesh(fixed, 2.0)
    assert coarse.base_size == pytest.approx(0.4) and (coarse.surface_level_min, coarse.surface_level_max) == (3, 4)


def test_every_level_gets_the_same_absolute_layer_stack() -> None:
    """Relative sizing: first = final * h_surface / ER^(n-1) at the current surface size, the same
    on every level (relativeSizes false); absolute y+: the y+ first layer and the current count.
    The quality controls stay those of the project's sizing (no relaxed set for relative)."""
    mesh = Mesh()
    surface = estimate_mesh(DOMAIN, 1.0, mesh).surface_size
    stack = reference_layers(mesh, surface, None)
    assert stack.count == 3 and stack.first == pytest.approx(0.5 * surface / 1.2**2)
    dicts = []
    for lv in study_levels(mesh, math.sqrt(2), "fine"):
        inp = MeshCaseInput(DOMAIN, False, ("Ball",), (-0.5, 0.5, -0.5, 0.5, -0.5, 0.5), 1.0, lv.mesh,
                            fixed_layers=(stack.first, stack.count))
        dicts.append(snappy_hex_mesh_dict(inp).content["addLayersControls"])
    for d in dicts:
        assert d["relativeSizes"] is False and d["firstLayerThickness"] == pytest.approx(stack.first)
        assert d["expansionRatio"] == 1.2 and d["layers"]['"Ball.*"'] == {"nSurfaceLayers": 3}
        assert "nRelaxedIter" not in d
    yplus = Mesh(layer_sizing="absolute_yplus", target_yplus=1.0)
    s2 = reference_layers(yplus, surface, 2e-5)
    assert s2.first == 2e-5 and s2.count > 3
    assert reference_layers(Mesh(layers=0), surface, None) is None
    with pytest.raises(ValueError):
        reference_layers(yplus, surface, None)


def _record(values, states=(CRITERIA_MET,) * 3, sizes=(0.04, 0.04 / math.sqrt(2), 0.02)) -> StudyRecord:
    levels = []
    for i, (v, s, h) in enumerate(zip(values, states, sizes)):
        levels.append(LevelResult(i, ("coarse", "medium", "fine")[i], 1.0, cells=1000 * (i + 1), h=h, mesh_ok=True,
                                  state=s, criteria_met=s == CRITERIA_MET, values={"Cd": v} if v is not None else {}))
    return StudyRecord(math.sqrt(2), "fine", ["Cd"], 1, 8.0, levels)


def test_rows_flag_unreliable_levels_and_oscillation(tmp_path: Path) -> None:
    phi = lambda h: 0.5 + 10 * h**2  # noqa: E731
    sizes = (0.04, 0.04 / math.sqrt(2), 0.02)
    rec = _record([phi(h) for h in sizes])
    (row,) = quantity_rows(rec)
    assert row.reliable and row.note == "" and row.result.order == pytest.approx(2.0, rel=1e-6)
    assert row.result.extrapolated == pytest.approx(0.5, rel=1e-9)
    rec2 = _record([phi(h) for h in sizes], states=(CRITERIA_MET, ITERATION_LIMIT, CRITERIA_MET))
    (row2,) = quantity_rows(rec2)
    assert not row2.reliable and "unreliable: medium did not meet the stopping criteria" in row2.note
    (row3,) = quantity_rows(_record([1.0, 1.1, 1.05]))
    assert row3.result.convergence == "oscillatory" and row3.note == "oscillatory, GCI not applicable"
    (row4,) = quantity_rows(_record([1.0, None, 1.05]))
    assert row4.result is None and row4.note.startswith("incomplete")
    write_record(tmp_path, rec2)
    back = read_record(tmp_path)
    assert back == rec2
    out = tmp_path / "study.csv"
    export_csv(rec, out)
    rows = list(csv.reader(out.open()))
    assert rows[0][0] == "quantity" and rows[1][0] == "Cd" and rows[1][7] == "monotonic"
    assert float(rows[1][8]) == pytest.approx(2.0, rel=1e-6)


# -- the level sequence with fake runners ------------------------------------------------------------

@dataclass
class _Report:
    cells: int
    valid: bool = True

    def summary(self) -> str:
        return "fake"


@dataclass
class _MeshResult:
    success: bool
    report: _Report


class FakeMeshRun:
    cells = [1000, 2800, 8000]
    calls: list = []

    def __init__(self, case, *, on_line=None, step_timeout_s=None, parts=()):
        self.case = Path(case)
        FakeMeshRun.calls.append(self.case.name)

    def start(self):
        pass

    def wait(self, timeout=None):
        return _MeshResult(True, _Report(self.cells[len(FakeMeshRun.calls) - 1]))

    def request_stop(self):
        pass


class FakeSolverRun:
    values = [0.40, 0.36, 0.35]
    states = [CRITERIA_MET, CRITERIA_MET, CRITERIA_MET]
    n = 0

    def __init__(self, case, **kwargs):
        self.case, self.kwargs = Path(case), kwargs
        self.i = FakeSolverRun.n
        FakeSolverRun.n += 1

    def start(self):
        coeffs = self.case / "postProcessing" / "forceCoeffs1" / "0"
        coeffs.mkdir(parents=True)
        (coeffs / "coefficient.dat").write_text(
            "# Time\tCd\tCd(f)\tCd(r)\tCl\tCl(f)\tCl(r)\tCmPitch\tCmRoll\tCmYaw\tCs\tCs(f)\tCs(r)\n"
            f"1\t{self.values[self.i]}\t0\t0\t0.1\t0\t0\t0\t0\t0\t0\t0\t0\n")

    def wait(self, timeout=None):
        return SolverRunResult(self.states[self.i], 0, 50, duration_s=1.0)

    def request_stop(self):
        pass


def test_study_run_meshes_and_solves_every_level_in_order(tmp_path: Path) -> None:
    FakeMeshRun.calls, FakeSolverRun.n = [], 0
    rec = StudyRecord(math.sqrt(2), "fine", ["Cd", "Cl"], 2, 8.0,
                      [LevelResult(i, n, f) for i, (n, f) in enumerate([("coarse", 2.0), ("medium", 1.41), ("fine", 1.0)])])
    written = []
    run = StudyRun(tmp_path, rec, written.append, mesh_run_factory=FakeMeshRun, solver_run_factory=FakeSolverRun)
    run.start()
    out = run.wait(10)
    assert out.status == "finished"
    assert FakeMeshRun.calls == ["level_1", "level_2", "level_3"]
    assert [p.name for p in written] == ["level_1", "level_2", "level_3"]
    assert [lv.values["Cd"] for lv in out.levels] == [0.40, 0.36, 0.35]
    assert [lv.h for lv in out.levels] == pytest.approx([(8.0 / c) ** (1 / 3) for c in (1000, 2800, 8000)])
    assert all(lv.criteria_met for lv in out.levels)
    assert read_record(tmp_path).status == "finished"


def test_level_labels_name_the_criteria(tmp_path: Path) -> None:
    from vortexcfd.core.model import AsymptoticCriterion, StoppingCriteria

    class MetSolverRun(FakeSolverRun):
        def wait(self, timeout=None):
            return SolverRunResult(CRITERIA_MET, 0, 50, duration_s=1.0, criteria_met=("c1_asymptotic_Cd",))

    FakeMeshRun.calls, FakeSolverRun.n = [], 0
    stopping = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd")])
    rec = StudyRecord(math.sqrt(2), "fine", ["Cd"], 1, 8.0,
                      [LevelResult(i, n, 1.0) for i, n in enumerate(("coarse", "medium", "fine"))])
    run = StudyRun(tmp_path, rec, lambda case: None, stopping=stopping, mesh_run_factory=FakeMeshRun,
                   solver_run_factory=MetSolverRun)
    run.start()
    assert run.wait(10).levels[0].state_label == "Criteria met: Cd asymptotic"


def test_study_run_flags_a_level_that_misses_its_criteria(tmp_path: Path) -> None:
    FakeMeshRun.calls, FakeSolverRun.n = [], 0
    FakeSolverRun.states = [CRITERIA_MET, ITERATION_LIMIT, CRITERIA_MET]
    try:
        rec = StudyRecord(math.sqrt(2), "fine", ["Cd"], 1, 8.0,
                          [LevelResult(i, n, 1.0) for i, n in enumerate(("coarse", "medium", "fine"))])
        out = StudyRun(tmp_path, rec, lambda case: None, mesh_run_factory=FakeMeshRun,
                       solver_run_factory=FakeSolverRun)
        out.start()
        rec = out.wait(10)
    finally:
        FakeSolverRun.states = [CRITERIA_MET] * 3
    assert rec.levels[1].criteria_met is False and rec.levels[1].state_label == "Iteration limit"
    (row,) = quantity_rows(rec)
    assert not row.reliable and "medium" in row.note


# -- real study (marker long) -------------------------------------------------------------------------

@pytest.mark.long
@pytest.mark.slow
def test_real_mesh_study_on_the_coarse_sphere_at_re_200(tmp_path: Path) -> None:
    """The app's mesh study on the coarse sphere (radius 0.5 m, 24 x 24 STL, default domain and
    mesh as the fine level, r = sqrt(2)) at Re = 200 (0.003 m/s, steady and converged), alpha 4 deg,
    4 cores; stopping criteria Cd and Cl asymptotic (window 50, tolerance 1e-4) combined with "all",
    limit 1500 iterations. Every level must meet the criteria; prints the GCI table (Cd, Cl).

        .venv/bin/pytest -m long -s tests/test_mesh_study.py
    """
    import pyvista as pv

    from vortexcfd.core.model import AsymptoticCriterion, Part, StoppingCriteria
    from vortexcfd.core.project import Project
    from vortexcfd.workflow.mesh_study import prepare_study, solver_writer

    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24).save(str(folder / "geometry" / "sphere.stl"))
    project = Project.new("study")
    project.add_part(Part(name="Sphere", source_file="geometry/sphere.stl", units="m"))
    project.save(folder / "p.json")
    project.update_inflow(speed=0.003, alpha_deg=4.0)
    stopping = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=50, tolerance=1e-4),
                                          AsymptoticCriterion(quantity="Cl", window=50, tolerance=1e-4)])
    project.update_solver(iterations=1500, write_interval=1500, stopping=stopping.model_dump())
    project.update_study("mesh", quantities=["Cd", "Cl"], cores=4)
    study_dir, record, inputs = prepare_study(project)
    run = StudyRun(study_dir, record, solver_writer(project), stopping=project.sim.solvers.stopping,
                   parts=inputs.parts, solver_timeout_s=1800, mesh_timeout_s=900)
    run.start()
    try:
        rec = run.wait(5400)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(120)
    assert rec is not None and rec.status == "finished", rec
    print()
    print("| Level | Cells | h [m] | Cd | Cl | Iterations | Run |")
    print("|---|---|---|---|---|---|---|")
    for lv in rec.levels:
        print(f"| {lv.name} | {lv.cells:,} | {lv.h:.5f} | {lv.values['Cd']:.6g} | {lv.values['Cl']:.6g} | "
              f"{lv.iterations} | {lv.state_label} |")
    print("| Quantity | Convergence | p | Extrapolated | GCI fine | GCI medium | Asymptotic ratio |")
    print("|---|---|---|---|---|---|---|")
    for row in quantity_rows(rec):
        r = row.result

        def f(v, fmt):
            return "—" if v is None else fmt.format(v)

        print(f"| {row.quantity} | {r.convergence} | {f(r.order, '{:.3g}')} | {f(r.extrapolated, '{:.6g}')} | "
              f"{f(r.gci_fine and 100 * r.gci_fine, '{:.3g} %')} | {f(r.gci_medium and 100 * r.gci_medium, '{:.3g} %')} "
              f"| {f(r.asymptotic_ratio, '{:.3g}')} |")
    assert all(lv.criteria_met for lv in rec.levels), [lv.state_label for lv in rec.levels]
    assert rec.levels[0].cells < rec.levels[1].cells < rec.levels[2].cells
    assert (study_dir / "study.json").is_file() and not (folder / "case").exists()  # case/ never touched
    # the same absolute layer stack on every level
    from vortexcfd.foam.dictfile import read_foam_file

    stacks = set()
    for n in (1, 2, 3):
        layers = read_foam_file(study_dir / f"level_{n}" / "system" / "snappyHexMeshDict")["addLayersControls"]
        assert layers["relativeSizes"] is False
        stacks.add((layers["firstLayerThickness"], layers["expansionRatio"], layers["layers"]['"Sphere.*"']["nSurfaceLayers"]))
    assert len(stacks) == 1
