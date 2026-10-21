"""Project files, presets and the four records: written atomically with the umask's permissions
(docs/REVIEW.md R-04, R-05; D-114)."""

import math
import os
import stat
from pathlib import Path

import pytest

from vortexcfd.core import atomic_io
from vortexcfd.core.atomic_io import process_umask, write_text_atomic
from vortexcfd.core.model import Simulation
from vortexcfd.core.presets import PresetStore, preset_from_simulation
from vortexcfd.core.project_io import save_simulation
from vortexcfd.foam import mesh_study, polar_sweep
from vortexcfd.foam.mesh_record import RECORD_NAME, MeshRecord, write_mesh_record
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.foam.run_record import RUN_RECORD_NAME, RunRecord, write_run_record

REPORT = MeshReport(points=10, faces=40, cells=1234, max_non_orthogonality=30.5, avg_non_orthogonality=10.0,
                    max_skewness=0.5, failed_checks=0, mesh_ok=True)


@pytest.fixture
def umask():
    old = os.umask(0o022)
    os.umask(old)

    def set_mask(mask: int) -> None:
        os.umask(mask)

    yield set_mask
    os.umask(old)


def _project(folder: Path) -> Path:
    path = folder / "p.vcfd"
    save_simulation(Simulation(name="p"), path)
    return path


def _preset(folder: Path) -> Path:
    return PresetStore(folder / "presets").save(preset_from_simulation(Simulation(name="p"), "Mine"), overwrite=True)


def _mesh_record(folder: Path) -> Path:
    write_mesh_record(folder, MeshRecord(REPORT, "hash", ("Ball",)))
    return folder / RECORD_NAME


def _run_record(folder: Path) -> Path:
    write_run_record(folder, RunRecord("criteria_met", 3, {"p": 0.1}, "hash"))
    return folder / RUN_RECORD_NAME


def _study(folder: Path) -> Path:
    rec = mesh_study.StudyRecord(math.sqrt(2), "fine", ["Cd"], 1, 8.0,
                                 [mesh_study.LevelResult(0, "coarse", 1.0)])
    mesh_study.write_record(folder, rec)
    return folder / mesh_study.STUDY_JSON


def _sweep(folder: Path) -> Path:
    polar_sweep.write_record(folder, polar_sweep.new_record([0.0, 2.0], 1, True))
    return folder / polar_sweep.SWEEP_JSON


WRITERS = {"project": _project, "preset": _preset, "mesh record": _mesh_record, "run record": _run_record,
           "study record": _study, "sweep record": _sweep}


def test_the_umask_is_read_without_changing_it(umask) -> None:
    umask(0o027)
    assert process_umask() == 0o027
    assert process_umask() == 0o027


@pytest.mark.parametrize("mask, mode", [(0o022, 0o644), (0o027, 0o640), (0o077, 0o600)])
@pytest.mark.parametrize("kind", list(WRITERS))
def test_files_get_the_permissions_of_the_umask(tmp_path, umask, kind, mask, mode) -> None:
    umask(mask)
    path = WRITERS[kind](tmp_path)
    assert stat.S_IMODE(path.stat().st_mode) == mode
    plain = tmp_path / "plain.txt"  # what any other file the app writes gets
    plain.write_text("x")
    assert stat.S_IMODE(plain.stat().st_mode) == mode
    assert not list(path.parent.glob(".*.tmp"))


@pytest.mark.parametrize("kind", list(WRITERS))
def test_a_failed_write_leaves_the_old_file_whole(tmp_path, monkeypatch, kind) -> None:
    path = WRITERS[kind](tmp_path)
    before = path.read_bytes()

    def interrupted(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(atomic_io.os, "replace", interrupted)
    with pytest.raises(OSError):
        WRITERS[kind](tmp_path)
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".*.tmp"))


def test_write_text_atomic_replaces_the_content(tmp_path) -> None:
    path = tmp_path / "a.json"
    write_text_atomic(path, "one\n")
    write_text_atomic(path, "two\n")
    assert path.read_text(encoding="utf-8") == "two\n"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]
