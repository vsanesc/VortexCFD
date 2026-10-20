"""Persisted result of the last meshing run: case/vortexcfd_mesh.json (no Qt)."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from vortexcfd.foam.mesh_report import FirstCell, LayerCoverage, MeshReport

RECORD_NAME = "vortexcfd_mesh.json"


@dataclass(frozen=True)
class MeshRecord:
    report: MeshReport
    inputs_hash: str  # hash of the meshing inputs the mesh was made from
    patches: tuple[str, ...]  # part patch names present in the mesh
    cores: int = 1  # snappyHexMesh ranks the mesh was made with (D-111; records before it: 1)


def write_mesh_record(case_dir: Path, record: MeshRecord) -> None:
    data = {
        "report": asdict(record.report),
        "inputs_hash": record.inputs_hash,
        "patches": list(record.patches),
        "cores": record.cores,
    }
    (Path(case_dir) / RECORD_NAME).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_mesh_record(case_dir: Path) -> MeshRecord | None:
    """The saved record, or None if it is missing or unreadable."""
    path = Path(case_dir) / RECORD_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        report = dict(data["report"])
        report["layers"] = tuple(LayerCoverage(**row) for row in report.get("layers", ()))
        report["lost_parts"] = tuple(report.get("lost_parts", ()))  # absent in records before D-052
        report["domain_errors"] = tuple(report.get("domain_errors", ()))  # absent before D-078
        report["failed_check_lines"] = tuple(report.get("failed_check_lines", ()))  # absent before D-096
        report["warning_lines"] = tuple(report.get("warning_lines", ()))  # absent before D-100
        first_cell = report.get("first_cell")  # absent before D-109
        report["first_cell"] = FirstCell(**first_cell) if isinstance(first_cell, dict) else None
        return MeshRecord(MeshReport(**report), str(data["inputs_hash"]), tuple(data["patches"]),
                          int(data.get("cores", 1)))
    except (OSError, ValueError, KeyError, TypeError):
        return None
