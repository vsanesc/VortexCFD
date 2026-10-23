"""The Compare tab's actions (D-149), mixed into MainWindow: save a results snapshot of the current run, load the
snapshots of another project, delete one, export the overlay as PNG and the tables as CSV."""

import logging
from pathlib import Path

from vortexcfd.gui.compare_view import CompareView
from vortexcfd.workflow import snapshots as snapshot_module

log = logging.getLogger(__name__)


class CompareControlMixin:
    """Needs ``self._project``, ``self.dialogs``, ``self.show_message``, ``self.results_view`` (MainWindow)."""

    def _init_compare(self) -> None:
        self.compare_view = CompareView()
        self.compare_view.action.connect(self._on_compare_action)
        self._external_snapshots: list[snapshot_module.Snapshot] = []

    def show_compare(self) -> None:
        """The Compare tab in place of the viewer."""
        self._center_stack.setCurrentWidget(self.compare_view)
        for tab in (self.scene_tab, self.mesh_tab, self.results_tab):
            tab.setChecked(False)
        self.compare_tab.setChecked(True)
        self.results_controls.setVisible(False)
        self.section_controls.setVisible(False)
        self.refresh_compare()

    def compare_shown(self) -> bool:
        return self._center_stack.currentWidget() is self.compare_view

    def _current_run_snapshot(self):
        if not self.has_project or self._project.path is None:
            return None
        try:
            return snapshot_module.capture(self._project, snapshot_module.CURRENT_RUN, self._line_samples())
        except (snapshot_module.SnapshotError, OSError, ValueError):
            return None

    def _line_samples(self) -> dict:
        """The line plots' samples the Results Scene computed, by line plot name (none before results are shown)."""
        view = getattr(self, "results_view", None)
        if view is None:
            return {}
        names = {o.id: o.name for o in self._project.sim.results.objects}
        return {names[i]: s for i, s in view.line_samples.items() if i in names}

    def refresh_compare(self) -> None:
        folder = self._project.folder if self.has_project and self._project.path is not None else None
        self.compare_view.set_snapshots(self._current_run_snapshot(), snapshot_module.saved(folder),
                                        self._external_snapshots)

    def _on_compare_action(self, key: str) -> None:
        {"save": self.save_snapshot, "load": self.load_snapshots_from_project, "delete": self.delete_snapshot,
         "png": self.export_compare_png, "csv_values": lambda: self.export_compare_csv("values"),
         "csv_setup": lambda: self.export_compare_csv("setup")}[key]()

    def save_snapshot(self) -> Path | None:
        """Save results snapshot: the current run kept under a name in <project>/snapshots/ (D-149)."""
        if not self.has_project:
            return None
        suggested = f"run {len(snapshot_module.saved(self._project.folder)) + 1}" if self._project.path else "run 1"
        name = self.dialogs.ask_snapshot_name(suggested)
        if not name:
            return None
        try:
            snap = snapshot_module.capture(self._project, name.strip(), self._line_samples())
            path = snapshot_module.save(self._project, snap)
        except (snapshot_module.SnapshotError, OSError) as exc:
            self.show_message(f"Snapshot not saved: {exc}", "error")
            return None
        log.info("Saved the results snapshot '%s' to %s", snap.name, path)
        self.show_message(f"Saved the results snapshot '{snap.name}'", "success", log_it=False)
        self.refresh_compare()
        return path

    def load_snapshots_from_project(self) -> int:
        """Load from project: another project's snapshots, read-only (D-149); returns how many were added."""
        path = self.dialogs.ask_open_path()
        if path is None:
            return 0
        loaded = snapshot_module.from_project(path)
        known = {s.path for s in self._external_snapshots}
        new = [s for s in loaded if s.path not in known]
        self._external_snapshots += new
        if not loaded:
            self.show_message(f"{Path(path).name} has no results snapshots.", "warning")
        else:
            self.show_message(f"Loaded {len(new)} snapshot(s) of {Path(path).name} (read-only)", "success")
        self.refresh_compare()
        return len(new)

    def delete_snapshot(self) -> None:
        snap = self.compare_view.current_snapshot()
        if snap is None or snap.read_only or snap.path is None:
            return
        if not self.dialogs.confirm("Delete snapshot", f"Delete the results snapshot '{snap.name}'?"):
            return
        snapshot_module.delete(snap)
        self.refresh_compare()

    def export_compare_png(self) -> Path | None:
        snaps, key = self.compare_view.selected_snapshots(), self.compare_view.plot_key()
        if len(snaps) < 2 or key is None:
            return None
        path = self.dialogs.ask_line_export(Path(self._project.folder or Path.home()) / "comparison.png", "png")
        if path is None:
            return None
        path.write_bytes(snapshot_module.png_bytes(snaps, key, dpi=150))
        self.show_message(f"Comparison plot written to {path}", "success")
        return path

    def export_compare_csv(self, which: str) -> Path | None:
        snaps = self.compare_view.selected_snapshots()
        if len(snaps) < 2:
            return None
        name = "comparison_values.csv" if which == "values" else "comparison_setup.csv"
        path = self.dialogs.ask_line_export(Path(self._project.folder or Path.home()) / name, "csv")
        if path is None:
            return None
        (snapshot_module.write_values_csv if which == "values" else snapshot_module.write_setup_csv)(snaps, path)
        self.show_message(f"Comparison table written to {path}", "success")
        return path
