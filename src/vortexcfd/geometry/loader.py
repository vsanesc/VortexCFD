"""Load surface files (STL, OBJ, PLY) as triangulated PyVista meshes in metres."""

import re
from pathlib import Path

import numpy as np
import pyvista as pv

SUPPORTED_EXTENSIONS = (".stl", ".obj", ".ply")

# Metres per one unit of the Part's `units`.
UNIT_TO_METRE: dict[str, float] = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048}

# Cell array of an STL surface: the index of the `solid` block each triangle came from (0 for
# binary STL and for single-solid files).
SOLID_ARRAY = "solid"

_cache: dict[tuple[Path, int, str], pv.PolyData] = {}
_clear_hooks: list = []  # callables run by clear_cache (e.g. the report cache)


def cache_key(path: Path, units: str) -> tuple[Path, int, str]:
    """Cache key: (resolved path, mtime in ns, units). The file must exist."""
    resolved = Path(path).resolve()
    return resolved, resolved.stat().st_mtime_ns, units


class SurfaceLoadError(Exception):
    """The file cannot be loaded as a surface (unsupported, unreadable or empty)."""


def clear_cache() -> None:
    _cache.clear()
    for hook in _clear_hooks:
        hook()


def load_surface(path: Path, units: str) -> pv.PolyData:
    """Load ``path`` as a triangulated surface scaled to metres.

    Coincident points are merged (STL stores every triangle's corners separately), so the
    mesh has real edge connectivity. The result is cached by (resolved path, mtime, units):
    treat it as read-only, copy it before modifying.

    Raises:
        FileNotFoundError: the file does not exist.
        SurfaceLoadError: unsupported extension, unknown units, unreadable or empty file.
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise SurfaceLoadError(
            f"Unsupported file type '{path.suffix}' ({path.name}); "
            f"supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    if units not in UNIT_TO_METRE:
        raise SurfaceLoadError(f"Unknown units '{units}'; expected one of {', '.join(UNIT_TO_METRE)}")
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    resolved = path.resolve()
    key = (resolved, resolved.stat().st_mtime_ns, units)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    try:
        mesh = _read_stl(resolved) if ext == ".stl" else pv.read(str(resolved))
    except Exception as exc:  # VTK readers raise assorted errors
        raise SurfaceLoadError(f"Cannot read {path.name}: {exc}") from exc
    if not isinstance(mesh, pv.PolyData):
        mesh = mesh.extract_surface()
    mesh = mesh.triangulate()
    if mesh.n_cells == 0 or mesh.n_points == 0:
        raise SurfaceLoadError(f"{path.name} contains no triangles")
    mesh = mesh.clean(tolerance=0.0, lines_to_points=False, polys_to_lines=False,
                      strips_to_polys=False, point_merging=True)
    mesh.points = mesh.points * UNIT_TO_METRE[units]
    _cache[key] = mesh
    return mesh


def _read_stl(path: Path) -> pv.PolyData:
    """Read an STL keeping the solid index of every triangle (cell array SOLID_ARRAY).

    pv.read reports VTK read errors as warnings; a multi-solid ASCII file is read a second time
    with the reader's scalar tags (one label per `solid` block, in file order)."""
    mesh = pv.read(str(path))
    labels = np.zeros(mesh.n_cells, dtype=np.int32)
    if mesh.n_cells and len(stl_solid_names(path)) > 1:
        reader = pv.get_reader(str(path))
        reader.reader.ScalarTagsOn()
        tagged = reader.read()
        if tagged.n_cells == mesh.n_cells and "STLSolidLabeling" in tagged.cell_data:
            labels = np.asarray(tagged.cell_data["STLSolidLabeling"]).astype(np.int32)
    mesh.cell_data.clear()
    mesh.cell_data[SOLID_ARRAY] = labels
    return mesh


_SOLID_RE = re.compile(rb"^[ \t]*solid(?:[ \t]+([^\r\n]*))?[ \t]*\r?$", re.MULTILINE)


def stl_solid_names(path: Path) -> list[str]:
    """Names of the `solid` blocks of an ASCII STL, in file order ([] for a binary STL).

    An unnamed block gets "solid_<n>" (n from 1); repeated names get a numeric suffix."""
    path = Path(path)
    with open(path, "rb") as fh:
        head = fh.read(512)
    if not head.lstrip().lower().startswith(b"solid") or b"facet" not in path.read_bytes()[:4096]:
        return []
    size = path.stat().st_size
    if len(head) >= 84 and 84 + 50 * int.from_bytes(head[80:84], "little") == size:
        return []  # a binary STL whose header happens to start with "solid"
    names: list[str] = []
    for n, match in enumerate(_SOLID_RE.finditer(path.read_bytes()), start=1):
        raw = (match.group(1) or b"").decode("utf-8", "replace").strip()
        base = raw or f"solid_{n}"
        name, k = base, 1
        while name in names:
            k += 1
            name = f"{base}_{k}"
        names.append(name)
    return names
