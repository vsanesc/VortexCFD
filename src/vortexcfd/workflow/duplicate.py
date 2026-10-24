"""Save As with the mesh and results (D-079 as amended by D-174, Qt-free): what a duplicate copies besides the
geometry, its size, and the copy itself (plain copies, cancellable, with progress).

Copied: the case (the mesh, the written times, postProcessing, the run and mesh records, the logs), the mesh study's
and the polar sweep's folders, the snapshots and the reports. Left out: the processor directories (a decomposed copy
of the mesh and fields, D-063; a parallel run reconstructs its latest time), case_preview/ (Show in OpenFOAM file's
scratch, D-150) and the live view's samples (D-172). The records hold no absolute path and the hashes do not depend
on the project's name or folder, so the duplicate's mesh and results stay current. Plain copies, never hard links: a
solver writes into its files, and the two projects must stay independent.
"""

import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

COPIED = ("case", "case_study", "case_sweep", "snapshots", "reports")
SKIPPED = ("case_preview",)  # top-level folders never copied (listed for the record; COPIED is what is copied)
_PROCESSOR = re.compile(r"^processor\d+$")
LIVE_VIEW = "liveView"  # postProcessing/liveView: the live view's samples (D-172)
CHUNK = 4 << 20  # bytes copied between two looks at the cancel flag


@dataclass(frozen=True)
class CopyItem:
    source: Path
    relative: str  # the path in the project folder
    size: int


def _skipped(path: Path) -> bool:
    return bool(_PROCESSOR.match(path.name)) or (path.name == LIVE_VIEW and path.parent.name == "postProcessing")


def copy_plan(folder: Path) -> list[CopyItem]:
    """Every file a duplicate copies from the project folder ``folder`` besides the geometry, in a stable order."""
    folder = Path(folder)
    items: list[CopyItem] = []
    for top in COPIED:
        root = folder / top
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames if not _skipped(here / d) and not (here / d).is_symlink())
            for name in sorted(filenames):
                path = here / name
                if path.is_symlink() or not path.is_file():
                    continue
                items.append(CopyItem(path, path.relative_to(folder).as_posix(), path.stat().st_size))
    return items


def plan_size(plan: list[CopyItem]) -> int:
    return sum(item.size for item in plan)


def format_size(size: int) -> str:
    """"2.3 GB", "640 MB", "12 kB"."""
    for unit, factor in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if size >= factor:
            value = size / factor
            return f"{value:.2g} {unit}" if value < 10 else f"{value:.0f} {unit}"
    return f"{size} bytes"


class CopyCancelled(Exception):
    """The copy was cancelled."""


def copy_files(plan: list[CopyItem], target: Path, progress: Callable[[int, int], None] | None = None,
               cancelled: Callable[[], bool] | None = None) -> None:
    """Copy ``plan`` into the project folder ``target`` (plain copies with their times kept), calling
    ``progress(done_bytes, total_bytes)`` as it goes.

    Raises:
        CopyCancelled: ``cancelled()`` became true.
        OSError: a file could not be copied.
    """
    total = plan_size(plan)
    done = 0
    for item in plan:
        if cancelled is not None and cancelled():
            raise CopyCancelled
        dest = Path(target) / item.relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(item.source, "rb") as src, open(dest, "wb") as out:
            while True:
                block = src.read(CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if progress is not None:
                    progress(done, total)
                if cancelled is not None and cancelled():
                    raise CopyCancelled
        shutil.copystat(item.source, dest)
    if progress is not None:
        progress(total, total)


def remove_partial(target: Path, existed: bool) -> None:
    """After a cancelled or failed copy: the duplicate's folder removed (emptied when it existed before, empty, as
    New simulation allows)."""
    target = Path(target)
    if not target.is_dir():
        return
    if existed:
        for child in list(target.iterdir()):
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    else:
        shutil.rmtree(target)
