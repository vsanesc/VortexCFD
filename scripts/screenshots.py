"""Render window screenshots into /tmp/vortexcfd_shots/.

Offscreen by default (the display guard): the tree and panels render, the viewer stays empty.
Only the owner runs it on the real display (WSLg), where the OpenGL viewer renders:
    VORTEXCFD_ALLOW_REAL_DISPLAY=1 .venv/bin/python scripts/screenshots.py
"""

import logging
import os
import sys
import tempfile
from pathlib import Path

from vortexcfd.core.display_guard import apply_display_guard

apply_display_guard()  # before Qt is imported

from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = Path("/tmp/vortexcfd_shots")


def main() -> int:
    # Never touch the user's real settings or Recent list (D-141).
    from vortexcfd.core.user_dirs import isolate_settings

    isolate_settings()

    from vortexcfd.core.model import Part
    from vortexcfd.core.project import Project
    from vortexcfd.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    import pyvista as pv

    # A saved project with one real part (so domain and mesh estimates have numbers) and two
    # placeholder parts without files.
    folder = Path(tempfile.mkdtemp(prefix="vortexcfd_shots_project_"))
    (folder / "geometry").mkdir()
    pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24).save(str(folder / "geometry" / "Wing.stl"))
    project = Project.new("Wing study")
    project.add_part(Part(name="Wing", source_file="geometry/Wing.stl", units="m"))
    for name, units in (("Fuselage", "m"), ("Tail", "cm")):
        project.add_part(Part(name=name, source_file="", units=units))
    project.save(folder / "wing.json")

    window = MainWindow(project, with_viewer=True)  # placeholder viewer shows a sphere
    window.resize(1600, 1000)
    window.show()
    OUT.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    def shot(name: str) -> None:
        window.viewer.render()
        for _ in range(5):
            app.processEvents()
        path = OUT / name
        window.grab().save(str(path))
        paths.append(path)
        plotter_path = OUT / f"plotter_{name}"
        window.plotter.screenshot(str(plotter_path))
        paths.append(plotter_path)

    logging.getLogger("vortexcfd.screenshots").info("Loaded %d parts", len(project.sim.geometry.parts))
    logging.getLogger("vortexcfd.screenshots").warning("Example warning line")
    window.set_point_size(11)
    window.tree.setCurrentItem(window._items[("part", 0)])
    shot("v2.png")

    # Mesh and Fluid Domain properties at two font sizes (readability check).
    from vortexcfd.foam.mesh_report import LayerCoverage, MeshReport

    report = MeshReport(
        points=222040, faces=603889, cells=192220, max_non_orthogonality=40.23,
        avg_non_orthogonality=7.2, max_skewness=0.595, failed_checks=0, mesh_ok=True,
        layers=(LayerCoverage("Wing", 9460, 3, 2.4, 0.0211, 72.5),), extruded_percent=96.0,
    )
    window.properties.set_mesh_report(report)
    for size in (11, 14):
        window.set_point_size(size)
        window.tree.setCurrentItem(window._items[("mesh", None)])
        shot(f"v3_mesh_font{size}.png")
        # Widen the left column to 24u: the property rows go side by side (>= 20u).
        from vortexcfd.gui.theme import metrics as _metrics

        u = _metrics().u
        window._outer.setSizes([24 * u, window._outer.width() - 24 * u])
        for _ in range(5):
            app.processEvents()
        shot(f"v5_mesh_side_by_side_font{size}.png")
        window._apply_initial_sizes()
        window.tree.setCurrentItem(window._items[("fluid_domain", None)])
        shot(f"v3_domain_font{size}.png")
    # Real meshing of the sphere part with the default settings, then the Mesh Scene section.
    import time

    window.set_point_size(11)
    window.properties.set_mesh_report(None)
    for index in (2, 1):  # drop the placeholder parts: meshing needs real files
        window.project.remove_part(index)
    window.top_bar.mesh_button.click()
    deadline = time.monotonic() + 150
    while window.mesh_report is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)
    if window.mesh_report is not None:
        window.mesh_tab.click()
        for _ in range(10):
            app.processEvents()
        shot("v4_mesh_section.png")
        window.boundary_toggle.click()
        shot("v4_mesh_section_boundaries.png")
        window.axis_buttons[2].click()
        shot("v4_mesh_section_z.png")
    else:
        print("meshing did not finish in time")
    for p in paths:
        print(p)
    sys.stdout.flush()
    # Skip teardown: closing the OpenGL viewer can hang on WSLg/Mesa; the PNGs are saved.
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
