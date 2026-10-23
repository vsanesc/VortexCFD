"""Mesh study and polar sweep control for the main window (D-066, D-067).

``StudyWorker`` wraps a StudyRun / SweepRun (signals only, like SolverWorker); ``StudyControlMixin``
is mixed into MainWindow: Run / Stop from the study nodes, the busy rules (one OpenFOAM job at a
time: meshing, a solver run, a mesh study or a polar sweep), the state shown on the nodes and the
results windows.
"""

import logging

from PySide6.QtCore import QObject, Qt, Signal

from vortexcfd.foam.mesh_case import CaseDirectoryNotOursError
from vortexcfd.foam.mesh_study import StudyRun, export_csv as export_study_csv, read_record as read_study
from vortexcfd.foam.polar_sweep import SweepRun, export_csv as export_sweep_csv, read_record as read_sweep
from vortexcfd.workflow import internal, mesh_study, meshing, polar_sweep
from vortexcfd.workflow.meshing import MeshingNotReady
from vortexcfd.gui.study_rows import format_seconds
from vortexcfd.gui.study_windows import MeshStudyWindow, PolarSweepWindow

log = logging.getLogger("vortexcfd.gui")

LABELS = {"mesh": "mesh study", "polar": "polar sweep"}


DONE_JOIN_S = 10.0  # the longest wait for a finished run's thread to end (it only returns from on_done)


class StudyWorker(QObject):
    """Runs a StudyRun or SweepRun built by ``start(factory)``; the callbacks only emit signals.

    The run calls its ``on_done`` from its own thread, which is still alive at that moment. ``finished`` is therefore
    emitted from the GUI thread once that thread has ended (D-163): its receivers see ``is_running()`` False and show
    the final state, never a stale "Running" with a Stop button."""

    line = Signal(str)
    progress = Signal(object)  # a LevelResult or SweepPoint that just finished
    finished = Signal(object)  # the record, the run's thread ended
    _done = Signal(object)  # from the run's thread: queued to _on_done in the GUI thread

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._run = None
        self._done.connect(self._on_done, Qt.ConnectionType.QueuedConnection)

    def start(self, factory) -> None:
        """``factory(on_line, on_progress, on_done)`` returns an unstarted run."""
        if self.is_running():
            raise RuntimeError("a study is already running")
        self._run = factory(self.line.emit, self.progress.emit, self._done.emit)
        self._run.start()

    def _on_done(self, record) -> None:
        if self._run is not None:
            self._run.wait(DONE_JOIN_S)  # the thread returns right after on_done
        self.finished.emit(record)

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
        self.sweep_worker = StudyWorker(self)
        self.study_record = None
        self.sweep_record = None
        self.study_window: MeshStudyWindow | None = None
        self.sweep_window: PolarSweepWindow | None = None
        for worker, kind in ((self.study_worker, "mesh"), (self.sweep_worker, "polar")):
            worker.line.connect(self.console.append_output)
            worker.progress.connect(lambda _item, k=kind: self._on_study_progress(k))
            worker.finished.connect(lambda record, k=kind: self._on_study_done(k, record))
        self.properties.study_run_requested.connect(self.toggle_study)
        self.properties.study_results_requested.connect(self.show_study_results)

    # -- busy rules ------------------------------------------------------------------------------

    def study_running(self) -> str | None:
        """"A mesh study is running." / "A polar sweep is running." or None."""
        if not hasattr(self, "study_worker"):  # during the window's construction
            return None
        if self.study_worker.is_running():
            return "A mesh study is running: stop it first."
        if self.sweep_worker.is_running():
            return "A polar sweep is running: stop it first."
        return None

    def _busy_for_study(self, kind: str) -> str | None:
        if self.openfoam.problem():  # D-137: a study meshes and solves
            return self.openfoam.problem()
        if self.mesh_worker.is_running():
            return "Meshing is running."
        if self.solver_worker.is_running():
            return "The solver is running: stop it first."
        other = self.sweep_worker if kind == "mesh" else self.study_worker
        if other.is_running():
            return f"A {LABELS['polar' if kind == 'mesh' else 'mesh']} is running: stop it first."
        return None

    # -- state on the nodes -----------------------------------------------------------------------

    def _load_study_records(self) -> None:
        study, sweep = mesh_study.study_dir_for(self._project), polar_sweep.sweep_dir_for(self._project)
        self.study_record = read_study(study) if study is not None else None
        self.sweep_record = read_sweep(sweep) if sweep is not None else None

    def _update_study_state(self) -> None:
        """Fill the Mesh Study / Polar Sweep node (only the one shown: the plan reads the surfaces)."""
        if not hasattr(self, "study_worker"):
            return
        kind = (self._selection or ("root", None))[0]
        if kind == "mesh_study":
            self._update_mesh_study_state()
        elif kind == "polar_sweep":
            self._update_sweep_state()

    def _update_mesh_study_state(self) -> None:
        running = self.study_worker.is_running()
        levels, layers, current_as, current_note = None, "—", None, None
        reason = None if running else (self._busy_for_study("mesh") or mesh_study.study_readiness(self._project))
        try:
            plan = mesh_study.plan_study(self._project)
            current_as, current_note = plan.current_as, plan.current_as_note  # D-128
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
                                        current_as=current_as, current_note=current_note,
                                        status=status, warn=warn,
                                        has_results=record is not None and any(lv.values for lv in record.levels))

    def _update_sweep_state(self) -> None:
        running = self.sweep_worker.is_running()
        reason = None
        if not running:
            reason = polar_sweep.sweep_readiness(self._project, busy=self._busy_for_study("polar"))
        record = self.sweep_record
        status, warn = ("Running" if running else "Not run"), False
        if record is not None:
            done = sum(1 for p in record.points if p.finished)
            flagged = sum(1 for p in record.points if p.flagged)
            status = (f"Running: {done} of {len(record.points)} angles done" if running
                      else f"Last sweep {record.status}: {done} of {len(record.points)} angles")
            if not running and record.status == "stopped" and done < len(record.points):
                status += " (Run resumes it)"
            if flagged:
                status += f", {flagged} without meeting the stopping criteria"
                warn = True
        self.properties.set_study_state("polar", running=running, reason=reason, status=status, warn=warn,
                                        has_results=record is not None and any(p.state for p in record.points))

    # -- run / stop --------------------------------------------------------------------------------

    def toggle_study(self, kind: str) -> None:
        worker = self.study_worker if kind == "mesh" else self.sweep_worker
        if worker.is_running():
            log.warning("Stopping the %s at the user's request", LABELS[kind])
            self.show_message(f"Stopping the {LABELS[kind]}...", "warning", log_it=False)
            worker.request_stop()
            return
        self._flush_edits()
        if kind == "mesh":
            self._start_mesh_study()
        else:
            self._start_sweep()
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
            study_dir, record, writer, stopping=stopping, parts=inputs.patches, on_line=on_line,
            on_level=on_progress, on_done=on_done, solver_timeout_s=self.study_timeout_s,
            mesh_run_factory=self.study_mesh_run_factory, solver_run_factory=self.study_solver_run_factory,
            walls=internal.wall_patches(self._project) if inputs.internal else None))  # layers on walls (D-129)

    def _start_sweep(self) -> None:
        reason = polar_sweep.sweep_readiness(self._project, busy=self._busy_for_study("polar"))
        if reason is not None:
            self.show_message(reason, "error")
            return
        try:
            sweep_dir, record = polar_sweep.prepare_sweep(self._project)
            preparer = polar_sweep.point_preparer(self._project)
            writer = polar_sweep.point_writer(self._project)
            parts = meshing.mesh_inputs(self._project)[0].patches
        except (MeshingNotReady, OSError, ValueError) as exc:
            self.show_message(f"Could not prepare the polar sweep: {exc}", "error")
            return
        self.sweep_record = record
        stopping = self._project.sim.solvers.stopping.model_copy(deep=True)
        kept = sum(1 for p in record.points if p.finished)
        log.info("Polar sweep: %d angles (%s deg) in %s, one mesh per angle on %d cores%s", len(record.points),
                 ", ".join(f"{a:g}" for a in record.alphas), sweep_dir, record.mesh_cores,
                 f"; resuming: {kept} finished angles kept" if kept else "")
        self.sweep_worker.start(lambda on_line, on_progress, on_done: SweepRun(
            sweep_dir, record, preparer, writer, stopping=stopping, parts=parts, on_line=on_line,
            on_point=on_progress, on_done=on_done, solver_timeout_s=self.study_timeout_s,
            mesh_run_factory=self.study_mesh_run_factory, solver_run_factory=self.study_solver_run_factory))

    def _after_study_change(self) -> None:
        self._update_study_state()
        self._update_run_button()
        self._update_mesh_button()
        for window, record in ((self.study_window, self.study_record), (self.sweep_window, self.sweep_record)):
            if window is not None:
                window.set_record(record)

    def _on_study_progress(self, kind: str) -> None:
        self._after_study_change()

    def _on_study_done(self, kind: str, record) -> None:
        if kind == "mesh":
            self.study_record = record
            flagged = [lv.name for lv in record.levels if lv.state is not None and not lv.reliable]
            text = f"Mesh study {record.status}"
            if flagged:
                text += f": {', '.join(flagged)} did not meet the stopping criteria (GCI unreliable)"
        else:
            self.sweep_record = record
            flagged = [f"{p.alpha:g}" for p in record.points if p.flagged]
            text = f"Polar sweep {record.status}"
            if flagged:
                text += f": alpha {', '.join(flagged)} deg did not meet the stopping criteria"
        level = "success" if record.status == "finished" and not flagged else "warning"
        if record.status == "failed":
            level = "error"
        self.show_message(text, level)
        self._after_study_change()

    # -- results ------------------------------------------------------------------------------------

    def show_study_results(self, kind: str) -> None:
        if kind == "mesh":
            if self.study_window is None:
                self.study_window = MeshStudyWindow(self)
                self.study_window.export_requested.connect(lambda: self._export_study_csv("mesh"))
            window, record = self.study_window, self.study_record
        else:
            if self.sweep_window is None:
                self.sweep_window = PolarSweepWindow(self)
                self.sweep_window.export_requested.connect(lambda: self._export_study_csv("polar"))
            window, record = self.sweep_window, self.sweep_record
        window.configure(self._theme)
        window.set_record(record)
        window.show()
        window.raise_()

    def _export_study_csv(self, kind: str) -> None:
        folder = (mesh_study.study_dir_for if kind == "mesh" else polar_sweep.sweep_dir_for)(self._project)
        name = "mesh_study.csv" if kind == "mesh" else "polar.csv"
        path = self.dialogs.ask_csv_path(folder / name if folder is not None else None)
        if path is None:
            return
        try:
            if kind == "mesh":
                export_study_csv(self.study_record, path)
            else:
                export_sweep_csv(self.sweep_record, path)
        except OSError as exc:
            self.show_message(f"Could not write {path}: {exc}", "error")
            return
        self.show_message(f"Exported {path}")

