"""Offscreen screenshots of a screen at three window sizes and three interface sizes (the owner's review rule):

    nice -n 15 .venv/bin/python scripts/gui_review_sizes.py run/gui_review/fix [screen ...]

Each screen is shown at its minimum size, its default size and 1920x1080, at each interface size (Small, Medium,
Large), and saved as <out>/<screen>/<window size>_<interface size>.png. Screens: ``new_sim``, ``start``, ``main``
(the main window: tree, viewer, properties, top bar), ``properties`` (the detached properties window), ``compare``
(the Compare tab), ``foam_file`` (the Show in OpenFOAM file viewer), ``monitors`` (the detached residual chart and
convergence criteria windows), ``report_chart`` (a report's chart window, D-170) and ``all``. ``main:<node>[@<setup>]`` is the main window on a tree node (e.g.
``main:inflow``, ``main:part:0``) after an optional named set-up of SETUPS (e.g. ``main:stopping@criteria_changed``),
saved as <out>/main_<node>[_<setup>]/.
"""

import logging
import sys
from pathlib import Path

from vortexcfd.core.display_guard import apply_display_guard

apply_display_guard()  # before Qt is imported

from vortexcfd.core.user_dirs import isolate_settings  # noqa: E402

isolate_settings("vortexcfd_gui_review_")  # never the user's settings (D-141)

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from vortexcfd.gui.teardown import dispose  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import gui_review as gr  # noqa: E402

LARGE = (1920, 1080)
SCREENS = ["new_sim", "start", "main", "properties", "compare", "foam_file", "monitors", "report_chart",
           "solution_menu", "save_as"]
log = logging.getLogger("gui_review_sizes")


def metrics_u() -> int:
    from vortexcfd.gui.theme import metrics

    return metrics().u


def _sizes(widget: QWidget, default: tuple[int, int]) -> dict[str, tuple[int, int]]:
    minimum = widget.minimumSizeHint().expandedTo(widget.minimumSize())
    return {"min": (minimum.width(), minimum.height()), "default": default, "large": LARGE}


def _shoot_sizes(app, widget: QWidget, out: Path, screen: str, interface: str, default: tuple[int, int],
                 grab_root: QWidget | None = None) -> None:
    for name, (w, h) in _sizes(widget, default).items():
        widget.resize(w, h)
        gr._settle(app, 12)
        gr._grab(app, grab_root or widget, out / screen / f"{name}_{interface.lower()}.png")
    widget.resize(*default)
    gr._settle(app)


def _main_window(app, vcfd: Path):
    window = gr._window(app, vcfd)
    item = window._items.get(("mesh", None))
    if item is not None:
        window.tree.setCurrentItem(item)
    gr._settle(app)
    return window


def _criteria_changed(window) -> None:
    """The project's criteria no longer those of the last run (D-165): the review copy's run record gets the run's
    criteria (as a run of this version records them), then the project's first criterion is removed."""
    from dataclasses import replace

    from vortexcfd.foam.run_record import read_run_record, write_run_record

    case = window.project.folder / "case"
    record = read_run_record(case)
    if record is not None and record.stopping is None:
        write_run_record(case, replace(record, stopping=window.project.sim.solvers.stopping.model_dump()))
        window._load_run_record(window.project)
    stop = window.project.sim.solvers.stopping.model_dump()
    stop["criteria"] = stop["criteria"][1:]
    window.project.update_solver(stopping=stop)


def _live(window) -> None:
    """The Results Scene during a run (D-172): a live sample made from the review copy's results (its walls and a y
    plane), shown as the running solver's; the scene on the Results tab."""
    from vortexcfd.foam.live_view import LIVE_VIEW, WALLS
    from vortexcfd.gui.results_scene import read_results

    case = window.project.folder / "case"
    time = window.results_time()
    data = read_results(case, time, window._mesh_patches)
    folder = case / "postProcessing" / LIVE_VIEW / "150"
    folder.mkdir(parents=True, exist_ok=True)
    import pyvista as pv

    walls = pv.merge(list(data.patches.values())).extract_surface()
    walls.save(str(folder / f"{WALLS}.vtp"))
    data.internal.slice(normal=(0, 1, 0)).extract_surface().save(str(folder / "section_y.vtp"))
    window.solver_worker.is_running = lambda: True  # shown as during a run
    window._live_case = case
    window._live_settled, window._live_shown, window._live_data = {}, None, None
    window._write_now_after, window._written_now, window._written_known = None, [], set()
    window.display_combo.setCurrentText("Both")
    window.poll_live()
    window.poll_live()
    window.results_tab.click()


# Named set-ups of a ``main:<node>@<setup>`` screen: what is changed in the project before the screenshots.
SETUPS = {"criteria_changed": _criteria_changed,
          "alpha4": lambda window: window.project.update_inflow(alpha_deg=4.0),
          "mach_high": lambda window: window.project.update_inflow(speed=150.0),
          "live": _live}


def _node_window(app, vcfd: Path, spec: str):
    """The main window on the node of ``spec`` ("<kind>[:<index>][@<setup>]"); returns (window, folder name)."""
    node, _, setup = spec.partition("@")
    window = gr._window(app, vcfd)
    if setup:
        SETUPS[setup](window)
    item = window._items.get(gr._key(node))
    if item is None:
        log.warning("no node %s", node)
    else:
        window.tree.setCurrentItem(item)
    gr._settle(app)
    return window, "main_" + node.replace(":", "_") + (f"_{setup}" if setup else "")


def shoot(out: Path, screens: list[str]) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    from vortexcfd.gui.theme import DARK, INTERFACE_SIZES, apply_theme, save_appearance

    if "all" in screens:
        screens = SCREENS
    vcfd = gr._project_copy()
    for interface, points in INTERFACE_SIZES.items():
        save_appearance(DARK, points)  # the main window reads it
        apply_theme(DARK, points)
        for screen in screens:
            if screen == "new_sim":
                from vortexcfd.core.presets import PresetStore
                from vortexcfd.gui.settings_store import presets_dir
                from vortexcfd.gui.start_dialogs import NewSimulationDialog

                dialog = NewSimulationDialog(PresetStore(presets_dir()), physical=12)
                dialog.parent_edit.setText(str(gr.WORK))
                dialog.show()
                gr._settle(app)
                _shoot_sizes(app, dialog, out, screen, interface, (dialog.width(), dialog.height()))
                dispose(dialog)
            elif screen == "start":
                from vortexcfd.gui.recent import RecentProjects
                from vortexcfd.gui.start_dialogs import StartDialog

                recent = RecentProjects()
                recent.clear()
                recent.add(vcfd)
                dialog = StartDialog(recent)
                dialog.show()
                gr._settle(app)
                _shoot_sizes(app, dialog, out, screen, interface, (dialog.width(), dialog.height()))
                dialog.show_open_panel()
                _shoot_sizes(app, dialog, out, "start_open", interface, (dialog.width(), dialog.height()))
                dispose(dialog)
            elif screen.startswith("main:"):
                window, folder = _node_window(app, vcfd, screen.removeprefix("main:"))
                _shoot_sizes(app, window, out, folder, interface, gr.SIZE)
                dispose(window)
            elif screen == "main":
                window = _main_window(app, vcfd)
                _shoot_sizes(app, window, out, screen, interface, gr.SIZE)
                dispose(window)
            elif screen == "properties":
                window = _main_window(app, vcfd)
                window.detach_properties()
                gr._settle(app)
                panel = window.properties_window
                _shoot_sizes(app, panel, out, screen, interface, (panel.width(), panel.height()))
                window.dock_properties()
                dispose(window)
            elif screen == "compare":
                window = _main_window(app, vcfd)
                from vortexcfd.workflow import snapshots

                for name in ("run A", "run B (curvature 1)"):
                    if name.startswith("run B"):
                        window.project.update_mesh(curvature_levels=1)
                    snapshots.save(window.project, snapshots.capture(window.project, name), overwrite=True)
                window.project.undo()
                window.compare_tab.click()
                window.compare_view.check(window.compare_view.keys()[1:3])
                _shoot_sizes(app, window, out, screen, interface, gr.SIZE)
                dispose(window)
            elif screen == "foam_file":
                window = _main_window(app, vcfd)
                window.dialogs.foam_files = []
                from vortexcfd.gui.foam_file_viewer import FoamFileViewer
                from vortexcfd.workflow import foam_entries as fe

                entries = fe.entries_for(window.project, "mset_feature_angle")
                viewer = FoamFileViewer("mset_feature_angle", entries,
                                        {e: fe.case_file(window.project, e) for e in entries})
                viewer.show()
                gr._settle(app)
                _shoot_sizes(app, viewer, out, screen, interface, (viewer.width(), viewer.height()))
                dispose(viewer)
                dispose(window)
            elif screen == "save_as":  # the Save As dialog with "Copy mesh and results" (D-174)
                from vortexcfd.gui.start_dialogs import DuplicateProjectDialog
                from vortexcfd.workflow import duplicate as dup

                size = dup.plan_size(dup.copy_plan(vcfd.parent))
                dialog = DuplicateProjectDialog("sphere", gr.WORK, None, size)
                dialog.show()
                gr._settle(app)
                _shoot_sizes(app, dialog, out, screen, interface, (dialog.width(), dialog.height()))
                dispose(dialog)
            elif screen == "solution_menu":  # the Solution menu (D-173), open, with its tooltips on
                window = _main_window(app, vcfd)
                menu = window.solution_menu
                menu.aboutToShow.emit()
                menu.popup(window.mapToGlobal(window.rect().center()))
                gr._settle(app)
                gr._grab(app, menu, out / screen / f"menu_{interface.lower()}.png")
                menu.hide()
                _shoot_sizes(app, window, out, "main_solution", interface, gr.SIZE)
                dispose(window)
            elif screen == "report_chart":  # a report chart's window (D-170) and the slots with their buttons
                window = _main_window(app, vcfd)
                window.project.update_reports(slots=["Cd", "Cl", "yplus_avg"])
                gr._settle(app)
                _shoot_sizes(app, window, out, "main_slots", interface, gr.SIZE)
                chart = window.monitors.open_chart("Cd")
                chart.resize(48 * metrics_u(), 30 * metrics_u())
                gr._settle(app)
                _shoot_sizes(app, chart, out, screen, interface, (chart.width(), chart.height()))
                window.monitors.close_chart("Cd")
                dispose(window)
            elif screen == "monitors":
                window = _main_window(app, vcfd)
                for key in ("residuals", "criteria"):
                    detach = getattr(window, "detach_monitor", None)
                    if detach is None:
                        log.warning("no detachable monitors")
                        break
                    panel = detach(key)
                    gr._settle(app)
                    _shoot_sizes(app, panel, out, f"monitor_{key}", interface, (panel.width(), panel.height()))
                    window.dock_monitor(key)
                dispose(window)
            else:
                log.warning("unknown screen %s", screen)


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    shoot(Path(sys.argv[1]), sys.argv[2:] or ["all"])
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        from vortexcfd.gui.teardown import finish

        finish()  # every window and plotter ended while the application exists (D-164)
    sys.exit(code)
