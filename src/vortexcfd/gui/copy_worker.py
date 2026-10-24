"""Save As's copy of the mesh and results on a background thread (D-174): progress and the end reach the window
through signals only (a ThreadGate, D-164); Cancel stops it between two blocks of a file."""

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from vortexcfd.gui.thread_gate import ThreadGate
from vortexcfd.workflow import duplicate as dup


class CopyWorker(QObject):
    progress = Signal(int, int)  # bytes copied, bytes in all
    finished = Signal(str)  # "done", "cancelled" or the error's text

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.gate = ThreadGate()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, plan: list, target: Path) -> None:
        if self.is_running():
            raise RuntimeError("a copy is already running")
        self._cancel.clear()
        gate = self.gate

        def work() -> None:
            try:
                dup.copy_files(plan, target, gate.emitter(self.progress), self._cancel.is_set)
                gate.emit(self.finished, "done")
            except dup.CopyCancelled:
                gate.emit(self.finished, "cancelled")
            except OSError as exc:
                gate.emit(self.finished, f"{type(exc).__name__}: {exc}")

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def shutdown(self) -> None:
        """Before the owner is deleted (D-164): a copy is cancelled and never reports."""
        self.cancel()
        self.gate.close()
