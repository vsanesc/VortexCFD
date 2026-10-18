"""Background geometry work: CAD reading and tessellation, repair, self-intersection checks (D-073).

The jobs run on Python threads and report only through signals; the slots run in the GUI thread
(queued), which applies the results through the Project API. A job never touches the Project:
it receives plain data or a snapshot (``snapshot``) taken on the GUI thread.
"""

import logging
import queue
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from vortexcfd.core.project import Project
from vortexcfd.geometry.checks import cached_report, surface_report

log = logging.getLogger(__name__)


def snapshot(project: Project) -> Project:
    """An independent copy of the project's state for a worker thread (same path, no history)."""
    return Project(project.sim, project.path, workspace=project.workspace)


class GeometryWorker(QObject):
    """Runs one geometry job at a time on a background thread."""

    started = Signal(str)  # the job's label
    finished = Signal(int, object)  # job id, the function's result
    failed = Signal(int, object)  # job id, the exception

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._next = 0
        self.label = ""

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, label: str, function: Callable[[], object]) -> int:
        """Start ``function`` on a new thread; returns the job id. RuntimeError if one is running."""
        with self._lock:
            if self.is_running():
                raise RuntimeError(f"{self.label} is still running")
            self._next += 1
            job, self.label = self._next, label
            self._thread = threading.Thread(target=self._run, args=(job, function), daemon=True,
                                            name=f"geometry-{job}")
            self._thread.start()
        self.started.emit(label)
        return job

    def _run(self, job: int, function: Callable[[], object]) -> None:
        try:
            result = function()
        except Exception as exc:  # reported to the GUI thread
            self._emit(self.failed, job, exc)
            return
        self._emit(self.finished, job, result)

    @staticmethod
    def _emit(signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:  # the window (and this QObject) was deleted meanwhile
            pass

    def wait(self, timeout: float | None = None) -> bool:
        """Join the running job's thread (tests); True when no job is left running."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return not self.is_running()


class IntersectionChecker(QObject):
    """Computes full surface reports (self-intersections) one after another on a background
    thread; ``checked`` carries the (path, units) whose report is now cached."""

    checked = Signal(str, str)  # resolved path, units
    check_failed = Signal(str, str, str)  # resolved path, units, message
    _done = Signal(str, str, object)  # worker -> GUI thread: path, units, error message or None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue()
        self._pending: set[tuple[str, str]] = set()  # until the GUI thread has handled the result
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._done.connect(self._deliver)

    def _deliver(self, path: str, units: str, error) -> None:
        """GUI thread: the check is no longer pending once the public signal has been handled."""
        try:
            if error is None:
                self.checked.emit(path, units)
            else:
                self.check_failed.emit(path, units, error)
        finally:
            with self._lock:
                self._pending.discard((path, units))

    def request(self, path: Path, units: str) -> bool:
        """Queue the check of a surface; False when its report is already cached or queued."""
        key = (str(Path(path).resolve()), units)
        if cached_report(path, units) is not None:
            return False
        with self._lock:
            if key in self._pending:
                return False
            self._pending.add(key)
            self._queue.put(key)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, daemon=True, name="intersections")
                self._thread.start()
        return True

    def is_pending(self, path: Path, units: str) -> bool:
        with self._lock:
            return (str(Path(path).resolve()), units) in self._pending

    def busy(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def _loop(self) -> None:
        while True:
            try:
                key = self._queue.get(timeout=0.5)
            except queue.Empty:
                with self._lock:
                    if self._queue.empty():
                        self._thread = None
                        return
                continue
            path, units = key
            try:
                surface_report(Path(path), units)
            except Exception as exc:  # unreadable or vanished file
                GeometryWorker._emit(self._done, path, units, str(exc))
                continue
            GeometryWorker._emit(self._done, path, units, None)
