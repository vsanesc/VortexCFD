"""Load surface files (STL, OBJ, PLY) as triangulated PyVista meshes in metres."""

from pathlib import Path

import pyvista as pv

SUPPORTED_EXTENSIONS = (".stl", ".obj", ".ply")

# Metres per one unit of the Part's `units`.
UNIT_TO_METRE: dict[str, float] = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048}

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
        mesh = pv.read(str(resolved))
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
