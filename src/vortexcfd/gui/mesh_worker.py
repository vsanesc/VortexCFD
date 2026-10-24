"""Qt wrapper that runs the meshing pipeline in the background and reports through signals.

``MeshRun`` calls its callbacks from worker and reader threads. They only emit signals here;
connect them to methods of a QObject living in the GUI thread so slots run there (queued).
"""

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from vortexcfd.foam.mesh_run import MeshRun, MeshRunResult
from vortexcfd.gui.thread_gate import ThreadGate


class MeshWorker(QObject):
    line = Signal(str)  # one line of tool output
    step = Signal(str)  # name of the step that starts
    finished = Signal(object)  # MeshRunResult

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._run: MeshRun | None = None
        self.gate = ThreadGate()  # the run's threads emit through it (D-164)

    def start(self, case_dir: Path, parts: tuple[str, ...] = (), first_layer: tuple[float, int] | None = None,
              cores: int = 1, walls: tuple[str, ...] | None = None) -> None:
        """``first_layer``: (planned first layer in metres, layer count) of absolute (y+) layers, for the
        achieved first-cell measurement after checkMesh (D-109); None: not measured. ``cores``:
        snappyHexMesh ranks (1: serial; D-111)."""
        if self.is_running():
            raise RuntimeError("meshing is already running")
        self._run = MeshRun(
            case_dir, on_line=self.gate.emitter(self.line), on_step=self.gate.emitter(self.step), on_done=self._done,
            parts=parts,
            first_layer=first_layer, cores=cores, walls=walls,
        )
        self._run.start()

    def _done(self, result: MeshRunResult) -> None:
        self.gate.emit(self.finished, result)

    def shutdown(self) -> None:
        """Before the owner is deleted: stop a run and never emit again (D-164)."""
        self.request_stop()
        self.gate.close()

    def request_stop(self) -> None:
        """Ask the running step to stop (not a clean stop)."""
        if self._run is not None:
            self._run.request_stop()

    def is_running(self) -> bool:
        return self._run is not None and self._run.is_running()
