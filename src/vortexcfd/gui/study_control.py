"""Mesh study control for the main window (D-066).

``StudyWorker`` wraps a StudyRun (signals only, like SolverWorker); ``StudyControlMixin`` is mixed
into MainWindow: Run / Stop from the study node, the busy rules (one OpenFOAM job at a time:
meshing, a solver run or a mesh study), the state shown on the node and the results window.
"""

import logging

from PySide6.QtCore import QObject, Signal

from vortexcfd.foam.mesh_case import CaseDirectoryNotOursError
from vortexcfd.foam.mesh_study import StudyRun, export_csv as export_study_csv, read_record as read_study
from vortexcfd.gui import mesh_study
from vortexcfd.gui.meshing import MeshingNotReady
from vortexcfd.gui.study_rows import format_seconds
from vortexcfd.gui.study_windows import MeshStudyWindow

log = logging.getLogger("vortexcfd.gui")

LABELS = {"mesh": "mesh study"}


class StudyWorker(QObject):
    """Runs a StudyRun built by ``start(factory)``; the callbacks only emit signals."""

    line = Signal(str)
    progress = Signal(object)  # a LevelResult that just finished
    finished = Signal(object)  # the record

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._run = None

    def start(self, factory) -> None:
        """``factory(on_line, on_progress, on_done)`` returns an unstarted run."""
        if self.is_running():
            raise RuntimeError("a study is already running")
        self._run = factory(self.line.emit, self.progress.emit, self.finished.emit)
        self._run.start()

    def request_stop(self) -> None:
        if self._run is not None:
            self._run.request_stop()

    def is_running(self) -> bool:
        return self._run is not None and self._run.is_running()

    def wait(self, timeout: float | None = None):
        return self._run.wait(timeout) if self._run is not None else None


class StudyControlMixin:
    """See the module docstring. Needs MainWindow's _project, properties, console, show_message,
    dialogs, mesh_worker, solver_worker, mesh_report, mesh_stale and _flush_edits."""

    study_timeout_s: float | None = None  # per solver run (tests shorten it)
    # Process runners of the studies (tests replace them with fakes): MeshRun / SolverRun when None.
    study_mesh_run_factory = None
    study_solver_run_factory = None

    def _init_studies(self) -> None:
        self.study_worker = StudyWorker(self)
        self.study_record = None
        self.study_window: MeshStudyWindow | None = None
        for worker, kind in ((self.study_worker, "mesh"),):
            worker.line.connect(self.console.append_output)
            worker.progress.connect(lambda _item, k=kind: self._on_study_progress(k))
            worker.finished.connect(lambda record, k=kind: self._on_study_done(k, record))
        self.properties.study_run_requested.connect(self.toggle_study)
        self.properties.study_results_requested.connect(self.show_study_results)

    # -- busy rules ------------------------------------------------------------------------------

    def study_running(self) -> str | None:
        """"A mesh study is running: stop it first." or None."""
        if not hasattr(self, "study_worker"):  # during the window's construction
            return None
        if self.study_worker.is_running():
            return "A mesh study is running: stop it first."
        return None

    def _busy_for_study(self, kind: str) -> str | None:
        if self.mesh_worker.is_running():
            return "Meshing is running."
        if self.solver_worker.is_running():
            return "The solver is running: stop it first."
        return None

    # -- state on the nodes -----------------------------------------------------------------------

    def _load_study_records(self) -> None:
        study = mesh_study.study_dir_for(self._project)
        self.study_record = read_study(study) if study is not None else None

    def _update_study_state(self) -> None:
        """Fill the Mesh Study node when it is shown (the plan reads the surfaces)."""
        if not hasattr(self, "study_worker"):
            return
        kind = (self._selection or ("root", None))[0]
        if kind == "mesh_study":
            self._update_mesh_study_state()

    def _update_mesh_study_state(self) -> None:
        running = self.study_worker.is_running()
        levels, layers = None, "—"
        reason = None if running else (self._busy_for_study("mesh") or mesh_study.study_readiness(self._project))
        try:
            plan = mesh_study.plan_study(self._project)
            basis = "" if plan.measured else ", assumed"
            levels = [f"{lp.estimated_cells:,} cells ({lp.estimate.total_cells:,} background{basis}), "
                      f"up to {format_seconds(lp.estimated_seconds)}" for lp in plan.levels]
            if plan.layers is not None:
                layers = (f"{plan.layers.count} × first {plan.layers.first:.3g} m, ratio "
                          f"{plan.layers.expansion:g} (same on every level)")
            else:
                layers = "none"
        except MeshingNotReady as exc:
            reason = reason or str(exc)
        record = self.study_record
        status = "Running" if running else ("Not run" if record is None else f"Last study {record.status}")
        warn = False
        if record is not None and not running:
            flagged = [lv.name for lv in record.levels if lv.state is not None and not lv.reliable]
            if flagged:
                status += f"; {', '.join(flagged)} did not meet the stopping criteria (GCI unreliable)"
                warn = True
        if record is not None and running:
            done = sum(1 for lv in record.levels if lv.state is not None)
            status = f"Running: {done} of 3 levels done"
        self.properties.set_study_state("mesh", running=running, reason=reason, levels=levels, layers=layers,
                                        status=status, warn=warn,
                                        has_results=record is not None and any(lv.values for lv in record.levels))

    # -- run / stop --------------------------------------------------------------------------------

    def toggle_study(self, kind: str) -> None:
        worker = self.study_worker
        if worker.is_running():
            log.warning("Stopping the %s at the user's request", LABELS[kind])
            self.show_message(f"Stopping the {LABELS[kind]}...", "warning", log_it=False)
            worker.request_stop()
            return
        self._flush_edits()
        self._start_mesh_study()
        self._after_study_change()

    def _start_mesh_study(self) -> None:
        reason = self._busy_for_study("mesh") or mesh_study.study_readiness(self._project)
        if reason is not None:
            self.show_message(reason, "error")
            return
        try:
            study_dir, record, inputs = mesh_study.prepare_study(self._project)
            writer = mesh_study.solver_writer(self._project)
        except (MeshingNotReady, CaseDirectoryNotOursError, OSError, ValueError) as exc:
            self.show_message(f"Could not prepare the mesh study: {exc}", "error")
            return
        self.study_record = record
        stopping = self._project.sim.solvers.stopping.model_copy(deep=True)
        log.info("Mesh study: 3 levels, ratio %.4g, current settings = %s level, in %s",
                 record.ratio, record.current_as, study_dir)
        self.study_worker.start(lambda on_line, on_progress, on_done: StudyRun(
            study_dir, record, writer, stopping=stopping, parts=inputs.parts, on_line=on_line,
            on_level=on_progress, on_done=on_done, solver_timeout_s=self.study_timeout_s,
            mesh_run_factory=self.study_mesh_run_factory, solver_run_factory=self.study_solver_run_factory))

    def _after_study_change(self) -> None:
        self._update_study_state()
        self._update_run_button()
        self._update_mesh_button()
        if self.study_window is not None:
            self.study_window.set_record(self.study_record)

    def _on_study_progress(self, kind: str) -> None:
        self._after_study_change()

    def _on_study_done(self, kind: str, record) -> None:
        self.study_record = record
        flagged = [lv.name for lv in record.levels if lv.state is not None and not lv.reliable]
        text = f"Mesh study {record.status}"
        if flagged:
            text += f": {', '.join(flagged)} did not meet the stopping criteria (GCI unreliable)"
        level = "success" if record.status == "finished" and not flagged else "warning"
        if record.status == "failed":
            level = "error"
        self.show_message(text, level)
        self._after_study_change()

    # -- results ------------------------------------------------------------------------------------

    def show_study_results(self, kind: str) -> None:
        if self.study_window is None:
            self.study_window = MeshStudyWindow(self)
            self.study_window.export_requested.connect(lambda: self._export_study_csv("mesh"))
        window, record = self.study_window, self.study_record
        window.configure(self._theme)
        window.set_record(record)
        window.show()
        window.raise_()

    def _export_study_csv(self, kind: str) -> None:
        folder = mesh_study.study_dir_for(self._project)
        path = self.dialogs.ask_csv_path(folder / "mesh_study.csv" if folder is not None else None)
        if path is None:
            return
        try:
            export_study_csv(self.study_record, path)
        except OSError as exc:
            self.show_message(f"Could not write {path}: {exc}", "error")
            return
        self.show_message(f"Exported {path}")

