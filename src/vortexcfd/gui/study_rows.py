"""Rows of the Mesh Study (D-066) and Polar Sweep (D-067) nodes for the properties panel.

``StudyRowsMixin`` is mixed into PropertiesPanel and uses its row helpers (_make_row, _ro_row,
_section, message); the panel owns the signals ``study_run_requested(str)`` and
``study_results_requested(str)`` ("mesh" or "polar"). The owner (MainWindow) pushes the state with
``set_study_state``.
"""

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QWidget

from vortexcfd.core.reports import available_reports, report_label
from vortexcfd.foam.mesh_study import CURRENT_AS, MIN_RATIO
from vortexcfd.foam.parallel import physical_cores

STUDY_TOOLTIPS = {
    "ratio": "Refinement ratio r in linear cell size between levels (at least 1.3; r = sqrt(2) gives "
             "2.83 times the cells per level)",
    "current_as": "fine: the current mesh settings are the finest level (two coarser levels are added); "
                  "medium: one coarser and one finer level",
    "quantities": "Reports judged with the grid convergence index (Celik et al. 2008)",
    "cores": "MPI ranks of each level's solver run",
    "mode": "range: start, start + step, ... up to end; list: the angles in the order given",
    "init": "Start each point from the latest solution of the last point that met its stopping criteria",
}


def parse_angles(text: str) -> list[float]:
    """"0, 2.5 5" -> [0.0, 2.5, 5.0] (commas, spaces or semicolons). Raises ValueError."""
    parts = [p for p in text.replace(",", " ").replace(";", " ").split() if p]
    return [float(p) for p in parts]


def format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "unknown (no timed run in case/)"
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


class StudyRowsMixin:
    """Builds and refreshes the two study nodes' rows (see the module docstring)."""

    def _build_study_rows(self, dspin, spin, combo) -> None:
        cores = physical_cores()
        self._study_state: dict[str, dict] = {"mesh": {}, "polar": {}}
        # Mesh Study
        self.ms_ratio = dspin(MIN_RATIO, 4.0, 4)
        self.ms_current = combo(CURRENT_AS)
        self.ms_quantities = QPushButton()
        self.ms_quantities.setObjectName("tbBtn")
        self.ms_menu = QMenu(self.ms_quantities)
        self.ms_quantities.setMenu(self.ms_menu)
        self.ms_cores = spin(1, cores)
        for key, text, widget in (("ratio", "Refinement ratio r", self.ms_ratio),
                                  ("current_as", "Current settings are", self.ms_current),
                                  ("quantities", "Quantities", self.ms_quantities),
                                  ("cores", f"Cores ({cores} physical)", self.ms_cores)):
            widget.setToolTip(STUDY_TOOLTIPS[key])
            self._layout.addWidget(self._make_row(f"ms_{key}", text, widget))
        self.ms_ratio.editingFinished.connect(lambda: self._commit_study("mesh", "ratio", self.ms_ratio.value()))
        self.ms_current.currentTextChanged.connect(lambda t: self._commit_study("mesh", "current_as", t))
        self.ms_cores.editingFinished.connect(lambda: self._commit_study("mesh", "cores", self.ms_cores.value()))
        self._section("ms_estimate", "Levels (estimate)")
        self.ms_levels = [self._ro_row(f"ms_level_{i}", name) for i, name in enumerate(("Coarse", "Medium", "Fine"))]
        self.ms_layers = self._ro_row("ms_layers", "Prism layers (all levels)")
        self.ms_status = self._ro_row("ms_status", "Status")
        self.ms_run, self.ms_results, self._ms_buttons = self._study_buttons("mesh", "Run mesh study")
        # Polar Sweep
        self.ps_mode = combo(("range", "list"))
        self.ps_start = dspin(-90.0, 90.0, 3, "°")
        self.ps_end = dspin(-90.0, 90.0, 3, "°")
        self.ps_step = dspin(0.001, 180.0, 3, "°")
        self.ps_values = QLineEdit()
        self.ps_values.setPlaceholderText("e.g. 0 2 4 6 8")
        self.ps_cores = spin(1, cores)
        self.ps_init = QCheckBox("from the previous converged point")
        self.ps_mode.setToolTip(STUDY_TOOLTIPS["mode"])
        self.ps_init.setToolTip(STUDY_TOOLTIPS["init"])
        self.ps_cores.setToolTip("MPI ranks of each point's solver run")
        for key, text, widget in (("mode", "Angles", self.ps_mode), ("start", "Start", self.ps_start),
                                  ("end", "End", self.ps_end), ("step", "Step", self.ps_step),
                                  ("values", "Values", self.ps_values),
                                  ("cores", f"Cores ({cores} physical)", self.ps_cores),
                                  ("init", "Initialise", self.ps_init)):
            self._layout.addWidget(self._make_row(f"ps_{key}", text, widget))
        self.ps_mode.currentTextChanged.connect(lambda t: self._commit_study("polar", "mode", t))
        for key, w in (("start", self.ps_start), ("end", self.ps_end), ("step", self.ps_step)):
            w.editingFinished.connect(lambda k=key, w=w: self._commit_study("polar", k, w.value()))
        self.ps_cores.editingFinished.connect(lambda: self._commit_study("polar", "cores", self.ps_cores.value()))
        self.ps_values.editingFinished.connect(self._commit_angles)
        self.ps_init.toggled.connect(lambda on: self._commit_study("polar", "init_from_previous", on))
        self.ps_alphas = self._ro_row("ps_alphas", "Points")
        self.ps_status = self._ro_row("ps_status", "Status")
        self.ps_run, self.ps_results, self._ps_buttons = self._study_buttons("polar", "Run polar sweep")

    def _study_buttons(self, study: str, text: str):
        host = QWidget()
        row = QHBoxLayout(host)
        run = QPushButton(text)
        results = QPushButton("Results")
        for b in (run, results):
            b.setObjectName("tbBtn")
            row.addWidget(b, 1)
        run.clicked.connect(lambda: self.study_run_requested.emit(study))
        results.clicked.connect(lambda: self.study_results_requested.emit(study))
        self._layout.addWidget(host)
        return run, results, (host, row)

    # -- commits -------------------------------------------------------------------------------

    def _commit_study(self, study: str, key: str, value) -> None:
        if self._kind != {"mesh": "mesh_study", "polar": "polar_sweep"}[study]:
            return
        if getattr(self._project.sim.studies, study).model_dump()[key] == value:
            return
        try:
            self._project.update_study(study, **{key: value})
        except (ValueError, TypeError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()

    def _commit_angles(self) -> None:
        try:
            values = parse_angles(self.ps_values.text())
        except ValueError:
            self.message.emit(f"Angles: expected numbers separated by spaces or commas, got '{self.ps_values.text()}'")
            self.refresh()
            return
        self._commit_study("polar", "values", values)

    def _toggle_quantity(self, report_id: str, on: bool) -> None:
        current = list(self._project.sim.studies.mesh.quantities)
        if on and report_id not in current:
            current.append(report_id)
        elif not on and report_id in current:
            current.remove(report_id)
        self._commit_study("mesh", "quantities", current)

    # -- state -----------------------------------------------------------------------------------

    def set_study_state(self, study: str, **state) -> None:
        """``state``: running (bool), reason (why it cannot start, or None), levels (three texts) /
        alphas (text), layers (text), status (text, warn flag)."""
        self._study_state[study] = state
        self.refresh()

    def _refresh_mesh_study(self, show: bool, patches: list[str], probes: list[str]) -> None:
        keys = ["ms_ratio", "ms_current_as", "ms_quantities", "ms_cores", "ms_level_0", "ms_level_1", "ms_level_2",
                "ms_layers", "ms_status"]
        for k in keys:
            self._rows[k].setVisible(show)
        self._sections["ms_estimate"].setVisible(show)
        self._ms_buttons[0].setVisible(show)
        if not show:
            return
        s = self._project.sim.studies.mesh
        state = self._study_state["mesh"]
        for w in (self.ms_ratio, self.ms_current, self.ms_cores):
            w.blockSignals(True)
        try:
            self.ms_ratio.setValue(s.ratio)
            self.ms_current.setCurrentText(s.current_as)
            self.ms_cores.setValue(s.cores)
        finally:
            for w in (self.ms_ratio, self.ms_current, self.ms_cores):
                w.blockSignals(False)
        self.ms_menu.clear()
        for report_id in available_reports(patches, probes):
            action = self.ms_menu.addAction(report_label(report_id))
            action.setCheckable(True)
            action.setChecked(report_id in s.quantities)
            action.toggled.connect(lambda on, r=report_id: self._toggle_quantity(r, on))
        self.ms_quantities.setText(", ".join(report_label(q) for q in s.quantities) or "none")
        levels = state.get("levels") or ("—", "—", "—")
        for label, text in zip(self.ms_levels, levels):
            label.setText(text)
        self.ms_layers.setText(state.get("layers", "—"))
        self._fill_status(self.ms_status, self.ms_run, self.ms_results, state, "Run mesh study")

    def _refresh_polar(self, show: bool) -> None:
        keys = ["ps_mode", "ps_start", "ps_end", "ps_step", "ps_values", "ps_cores", "ps_init", "ps_alphas",
                "ps_status"]
        s = self._project.sim.studies.polar
        for k in keys:
            visible = show
            if k in ("ps_start", "ps_end", "ps_step"):
                visible = show and s.mode == "range"
            elif k == "ps_values":
                visible = show and s.mode == "list"
            self._rows[k].setVisible(visible)
        self._ps_buttons[0].setVisible(show)
        if not show:
            return
        state = self._study_state["polar"]
        widgets = (self.ps_mode, self.ps_start, self.ps_end, self.ps_step, self.ps_cores, self.ps_init, self.ps_values)
        for w in widgets:
            w.blockSignals(True)
        try:
            self.ps_mode.setCurrentText(s.mode)
            self.ps_start.setValue(s.start)
            self.ps_end.setValue(s.end)
            self.ps_step.setValue(s.step)
            self.ps_cores.setValue(s.cores)
            self.ps_init.setChecked(s.init_from_previous)
            self.ps_values.setText(" ".join(f"{v:g}" for v in s.values))
        finally:
            for w in widgets:
                w.blockSignals(False)
        alphas = s.alphas()
        self.ps_alphas.setText(f"{len(alphas)}: " + ", ".join(f"{a:g}°" for a in alphas) if alphas else "none")
        self._fill_status(self.ps_status, self.ps_run, self.ps_results, state, "Run polar sweep")

    def _fill_status(self, label: QLabel, run: QPushButton, results: QPushButton, state: dict, run_text: str) -> None:
        running = bool(state.get("running"))
        reason = state.get("reason")
        label.setText(state.get("status", "Not run"))
        self._set_warn(label, bool(state.get("warn")))
        run.setText("Stop" if running else run_text)
        run.setEnabled(running or reason is None)
        run.setToolTip("" if running or reason is None else reason)
        results.setEnabled(bool(state.get("has_results")))
