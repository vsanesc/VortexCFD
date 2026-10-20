"""constant/polyMesh read into numpy arrays (ascii files; no Qt, no pyvista)."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vortexcfd.foam.dictfile import read_foam_file


def _body(text: str) -> str:
    """The data after a FoamFile header (and its closing brace)."""
    start = text.find("FoamFile")
    if start >= 0:
        text = text[text.find("}", start) + 1:]
    return text


def _numbers(text: str, dtype) -> np.ndarray:
    body = _body(text)
    lines = [ln for ln in body.splitlines() if not ln.lstrip().startswith("//")]
    flat = " ".join(lines).replace("(", " ").replace(")", " ")
    return np.array(flat.split(), dtype=dtype)


def read_points(path: Path) -> np.ndarray:
    values = _numbers(Path(path).read_text(encoding="utf-8", errors="replace"), float)
    n = int(values[0])
    return values[1:1 + 3 * n].reshape(n, 3)


def read_labels(path: Path) -> np.ndarray:
    values = _numbers(Path(path).read_text(encoding="utf-8", errors="replace"), np.int64)
    n = int(values[0])
    return values[1:1 + n]


def read_faces(path: Path) -> np.ndarray:
    """(n, k) point ids of every face, -1 padded (an ascii faceList)."""
    flat = _numbers(Path(path).read_text(encoding="utf-8", errors="replace"), np.int64)
    n = int(flat[0])
    sizes, starts, i = np.empty(n, dtype=np.int64), np.empty(n, dtype=np.int64), 1
    for k in range(n):
        s = int(flat[i])
        sizes[k], starts[k] = s, i + 1
        i += s + 1
    width = int(sizes.max()) if n else 3
    out = np.full((n, width), -1, dtype=np.int64)
    for s in np.unique(sizes):
        rows = np.flatnonzero(sizes == s)
        out[rows, :s] = flat[starts[rows][:, None] + np.arange(s)]
    return out


def read_boundary(case_dir: Path) -> dict[str, tuple[int, int]]:
    """{patch: (startFace, nFaces)} from constant/polyMesh/boundary."""
    data = read_foam_file(Path(case_dir) / "constant" / "polyMesh" / "boundary")
    entries = data.get(None, []) if isinstance(data, dict) else []
    out = {}
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and isinstance(entry[1], dict):
            out[str(entry[0])] = (int(entry[1]["startFace"]), int(entry[1]["nFaces"]))
    return out


@dataclass
class PolyMesh:
    points: np.ndarray
    faces: np.ndarray  # (n, k) -1 padded
    owner: np.ndarray
    neighbour: np.ndarray
    boundary: dict[str, tuple[int, int]]

    @classmethod
    def read(cls, case_dir: Path) -> "PolyMesh":
        d = Path(case_dir) / "constant" / "polyMesh"
        return cls(read_points(d / "points"), read_faces(d / "faces"), read_labels(d / "owner"),
                   read_labels(d / "neighbour"), read_boundary(case_dir))


def face_geometry(points: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(centres = vertex means, area vectors (fan triangulation about the vertex mean), areas)."""
    valid = faces >= 0
    count = valid.sum(axis=1)
    p = points[np.where(valid, faces, 0)]
    p = np.where(valid[..., None], p, 0.0)
    centre = p.sum(axis=1) / count[:, None]
    nxt = np.roll(faces, -1, axis=1)
    # the vertex after the last valid one is the first
    last = count - 1
    nxt[np.arange(len(faces)), last] = faces[:, 0]
    q = points[np.where(valid, nxt, 0)]
    cross = np.cross(p - centre[:, None, :], q - centre[:, None, :])
    vec = 0.5 * np.where(valid[..., None], cross, 0.0).sum(axis=1)
    return centre, vec, np.linalg.norm(vec, axis=1)
