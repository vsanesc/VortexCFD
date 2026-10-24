"""Offscreen screenshots of a screen at three window sizes and three interface sizes (the owner's review rule):

    nice -n 15 .venv/bin/python scripts/gui_review_sizes.py run/gui_review/fix [screen ...]

Each screen is shown at its minimum size, its default size and 1920x1080, at each interface size (Small, Medium,
Large), and saved as <out>/<screen>/<window size>_<interface size>.png. Screens: ``new_sim``, ``start``, ``main``
(the main window: tree, viewer, properties, top bar), ``properties`` (the detached properties window), ``compare``
(the Compare tab), ``foam_file`` (the Show in OpenFOAM file viewer), ``monitors`` (the detached residual chart and
convergence criteria windows) and ``all``.
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
SCREENS = ["new_sim", "start", "main", "properties", "compare", "foam_file", "monitors"]
log = logging.getLogger("gui_review_sizes")


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
