"""Qt wrapper that runs the meshing pipeline in the background and reports through signals.

``MeshRun`` calls its callbacks from worker and reader threads. They only emit signals here;
connect them to methods of a QObject living in the GUI thread so slots run there (queued).
"""

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from vortexcfd.foam.mesh_run import MeshRun, MeshRunResult


class MeshWorker(QObject):
    line = Signal(str)  # one line of tool output
    step = Signal(str)  # name of the step that starts
    finished = Signal(object)  # MeshRunResult

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._run: MeshRun | None = None

    def start(self, case_dir: Path, parts: tuple[str, ...] = ()) -> None:
        if self.is_running():
            raise RuntimeError("meshing is already running")
        self._run = MeshRun(
            case_dir, on_line=self.line.emit, on_step=self.step.emit, on_done=self._done, parts=parts
        )
        self._run.start()

    def _done(self, result: MeshRunResult) -> None:
        self.finished.emit(result)

    def request_stop(self) -> None:
        """Ask the running step to stop (not a clean stop)."""
        if self._run is not None:
            self._run.request_stop()

    def is_running(self) -> bool:
        return self._run is not None and self._run.is_running()
