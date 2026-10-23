"""Offscreen screenshots of the GUI for the owner's visual review (run/gui_review/, git-ignored).

    nice -n 15 .venv/bin/python scripts/gui_review.py run/gui_review/<part>/<before|after> [screen ...]

The same project (a copy of run/manual/sphere, made by scripts/manual_images.py, meshed and solved) and the same
window size every time, so before and after images compare. Screens: ``start``, ``new_sim``, ``node:<kind>`` or
``node:<kind>:<index>`` (the main window with that tree node selected), ``menu:<kind>[:<index>]`` (the tree's
context menu of that node), ``results`` (the Results Scene), ``compare`` (the Compare tab, when it exists) and
``all`` (every one of them). The viewer is rendered offscreen and pasted into the window image.
"""

import logging
import shutil
import sys
from pathlib import Path

from vortexcfd.core.display_guard import apply_display_guard

apply_display_guard()  # before Qt is imported

from vortexcfd.core.user_dirs import isolate_settings  # noqa: E402

isolate_settings("vortexcfd_gui_review_")  # never the user's settings (D-141)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "run" / "manual" / "sphere"
WORK = REPO / "run" / "gui_review" / "projects"
SIZE = (1600, 1000)
NODES = ["root", "geometry", "part:0", "surface_prep", "mesh", "refinement_volumes", "physics", "inflow",
         "fluid_domain", "boundary_inlet", "wall:0", "solvers", "stopping", "reference_values", "probes",
         "mesh_study", "polar_sweep", "results"]
MENUS = ["geometry", "part:0", "fluid_domain", "boundary_inlet", "mesh", "refinement_volumes", "results"]
log = logging.getLogger("gui_review")


def _project_copy(name: str = "sphere") -> Path:
    """A fresh copy of the manual's sphere project (no processor folders)."""
    target = WORK / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns("processor*"))
    vcfd = target / "sphere.vcfd"
    if name != "sphere":
        vcfd = vcfd.rename(target / f"{name}.vcfd")
    return vcfd


def _settle(app, n: int = 8) -> None:
    for _ in range(n):
        app.processEvents()


def _grab(app, window, path: Path) -> None:
    """The window image with the offscreen-rendered viewer pasted where the viewer widget is."""
    _settle(app)
    image = window.grab().toImage()
    viewer = getattr(window, "viewer", None)
    if viewer is not None and viewer.isVisible():
        try:
            from vortexcfd.gui.image_export import render_image

            ratio = image.devicePixelRatio() or 1.0
            size = (max(1, int(viewer.width() * ratio)), max(1, int(viewer.height() * ratio)))
            shot = render_image(viewer, size).pixels[:, :, :3].copy()
            h, w = shot.shape[:2]
            frame = QImage(shot.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888).copy()
            origin = viewer.mapTo(window, QPoint(0, 0))
            painter = QPainter(image)
            painter.drawImage(QPoint(int(origin.x() * ratio), int(origin.y() * ratio)), frame)
            painter.end()
        except Exception:  # the window image alone is still useful
            log.exception("viewer not rendered")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))
    print(path)


def _key(spec: str):
    kind, _, index = spec.partition(":")
    return kind, (int(index) if index else None)


def _window(app, vcfd: Path):
    from tests.fakes import FakeDialogs
    from vortexcfd.core.project import Project
    from vortexcfd.gui.main_window import MainWindow

    window = MainWindow(Project.open(vcfd), FakeDialogs(), with_viewer=True)
    window.resize(*SIZE)
    window.show()
    _settle(app, 20)
    return window


def shoot(out: Path, screens: list[str]) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    from vortexcfd.gui.theme import apply_theme, load_appearance

    apply_theme(*load_appearance())  # the dialogs as the app shows them (the main window applies it too)
    if "all" in screens:
        screens = (["start", "new_sim"] + [f"node:{n}" for n in NODES] + [f"menu:{n}" for n in MENUS]
                   + ["results", "compare"])
    vcfd = _project_copy()
    other = _project_copy("sphere_finer")
    window = None
    for screen in screens:
        if screen == "start":
            from vortexcfd.gui.recent import RecentProjects
            from vortexcfd.gui.start_dialogs import StartDialog

            recent = RecentProjects()
            recent.clear()
            for path in (other, vcfd, REPO / "run" / "gui_review" / "projects" / "gone" / "gone.vcfd"):
                recent.add(path)
            dialog = StartDialog(recent)
            dialog.show()
            _grab(app, dialog, out / "start.png")
            if hasattr(dialog, "show_open_panel"):  # the welcome screen's second page (Part B)
                dialog.show_open_panel()
                _grab(app, dialog, out / "start_open.png")
            dialog.close()
        elif screen == "new_sim":
            from vortexcfd.core.presets import PresetStore
            from vortexcfd.gui.settings_store import presets_dir
            from vortexcfd.gui.start_dialogs import NewSimulationDialog

            dialog = NewSimulationDialog(PresetStore(presets_dir()), physical=12)
            dialog.name_edit.setText("wing_study")
            dialog.parent_edit.setText(str(WORK))
            dialog.show()
            _settle(app)
            dialog.resize(max(dialog.width(), 640), dialog.height())
            _grab(app, dialog, out / "new_simulation.png")
            dialog.name_edit.setText("")
            _grab(app, dialog, out / "new_simulation_empty_name.png")
            dialog.close()
        elif screen.startswith("node:") or screen.startswith("menu:"):
            window = window or _window(app, vcfd)
            what, spec = screen.split(":", 1)
            key = _key(spec)
            item = window._items.get(key)
            if item is None:
                log.warning("no tree node %s", key)
                continue
            window.tree.setCurrentItem(item)
            _settle(app)
            name = spec.replace(":", "_")
            if what == "node":
                _grab(app, window, out / f"node_{name}.png")
            else:
                rect = window.tree.visualItemRect(item)
                if hasattr(window, "tree_menu_for"):
                    menu = window.tree_menu_for(key)
                    if menu is not None:
                        menu.popup(window.tree.viewport().mapToGlobal(rect.center()))
                else:  # before Part E: the menu the right click pops up, if any
                    from PySide6.QtWidgets import QMenu

                    before = set(window.tree.findChildren(QMenu))
                    window._tree_context_menu(rect.center())
                    menu = next((m for m in window.tree.findChildren(QMenu) if m not in before), None)
                if menu is None:
                    log.warning("no context menu for %s", key)
                    continue
                _settle(app)
                image = window.grab().toImage()
                painter = QPainter(image)
                painter.drawPixmap(window.mapFromGlobal(menu.pos()), menu.grab())
                painter.end()
                path = out / f"menu_{name}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                image.save(str(path))
                print(path)
                menu.close()
        elif screen == "results":
            window = window or _window(app, vcfd)
            window.results_tab.click()
            for _ in range(200):
                _settle(app, 2)
                if window.results_view is not None and window.results_view.data is not None:
                    break
                import time

                time.sleep(0.05)
            _grab(app, window, out / "results_scene.png")
            window.scene_tab.click()
        elif screen == "compare":
            window = window or _window(app, vcfd)
            tab = getattr(window, "compare_tab", None)
            if tab is None:
                log.warning("no Compare tab")
                continue
            tab.click()
            _grab(app, window, out / "compare.png")
            window.scene_tab.click()
    if window is not None:
        window.close()


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    sys.path.insert(0, str(REPO))  # tests.fakes: the dialogs answer without opening
    shoot(Path(sys.argv[1]), sys.argv[2:] or ["all"])
    sys.stdout.flush()
    import os

    os._exit(0)  # skip the VTK teardown


if __name__ == "__main__":
    sys.exit(main())
