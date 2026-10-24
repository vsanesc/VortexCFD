"""The user manual's images (docs/manual/images/), made with the app itself, offscreen (the display guard).

    nice -n 15 .venv/bin/python scripts/manual_images.py sphere   # the first-case project: import, mesh, solve
    nice -n 15 .venv/bin/python scripts/manual_images.py images   # every image, with the app's image export

``sphere`` drives the main window as a user would (New simulation with the "External flow" preset, Import Geometry
of benchmarks/geometries/sphere.stl, Generate Mesh, Run Solver) into run/manual/sphere (git-ignored). ``images``
opens that project, the NACA 0012 round 3 case at 15 degrees and the pipe validation case (copies under
run/manual/, without the processor directories), adds results objects, and writes each image with
gui/image_export.export_image (the viewer rendered offscreen, D-133) or the app's own chart exports (line plot,
report plots). Nothing here is drawn by hand.
"""

import json
import logging
import shutil
import sys
import time
from pathlib import Path

from vortexcfd.core.display_guard import apply_display_guard

apply_display_guard()  # before Qt is imported

from vortexcfd.core.user_dirs import isolate_settings  # noqa: E402

import numpy as np  # noqa: E402
import pyvista as pv  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vortexcfd.gui.teardown import dispose  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RUN = REPO / "run" / "manual"
OUT = REPO / "docs" / "manual" / "images"
SIZE = (1600, 900)
log = logging.getLogger("manual_images")


def _dialogs(import_path: Path | None = None):
    from vortexcfd.gui.dialogs import Dialogs

    class ScriptDialogs(Dialogs):
        """No modal dialog: the answers a user would give."""

        def ask_import_path(self):
            return import_path

        def ask_units(self):
            return "m"

        def ask_solids_mode(self, file_name, solids):
            return "regions"

        def confirm_discard(self):
            return "discard"

        def ask_report_sections(self, omit):
            return list(omit)

        def show_error(self, title, text):
            log.error("%s: %s", title, text)

        def show_warning(self, title, text):
            log.warning("%s: %s", title, text)

    return ScriptDialogs()


def _wait(app, done, timeout_s: float) -> None:
    end = time.monotonic() + timeout_s
    while not done():
        app.processEvents()
        if time.monotonic() > end:
            raise TimeoutError("timed out")
        time.sleep(0.05)


def _window(app, project, dialogs=None):
    from vortexcfd.gui.main_window import MainWindow

    w = MainWindow(project, dialogs or _dialogs(), with_viewer=True)
    w.resize(1600, 1000)
    w.show()
    app.processEvents()
    return w


def sphere(app) -> None:
    from vortexcfd.core.model import MeanStableCriterion, Simulation, StoppingCriteria
    from vortexcfd.core.presets import BUILTIN_PRESETS, apply_preset
    from vortexcfd.core.project import Project
    from vortexcfd.foam.run_record import read_run_record

    folder = RUN / "sphere"
    if folder.exists():
        shutil.rmtree(folder)
    RUN.mkdir(parents=True, exist_ok=True)
    preset = next(p for p in BUILTIN_PRESETS if p.name == "External flow")
    project = Project.create(RUN, "sphere", apply_preset(Simulation(name="sphere"), preset))
    w = _window(app, project, _dialogs(REPO / "benchmarks" / "geometries" / "sphere.stl"))
    w.import_surface()
    _wait(app, lambda: not w.geometry_busy, 120)
    project.update_mesh(cores=8)
    project.update_solver(iterations=800, cores=8, stopping=StoppingCriteria(
        criteria=[MeanStableCriterion(quantity="Cd", window=100, tolerance=0.005)]))
    w.save()
    start = time.monotonic()
    w.generate_mesh()
    _wait(app, lambda: not w.mesh_worker.is_running() and w.mesh_report is not None, 1800)
    log.info("mesh: %.0f s, %s", time.monotonic() - start, w.mesh_report and w.mesh_report.cells)
    start = time.monotonic()
    w.run_solver()
    _wait(app, lambda: w.solver_worker.is_running(), 60)
    _wait(app, lambda: not w.solver_worker.is_running() and read_run_record(project.folder / "case") is not None, 1800)
    log.info("solver: %.0f s", time.monotonic() - start)
    w.save()
    dispose(w)


def _copy_project(source: Path, name: str) -> Path:
    """A copy under run/manual/ without the processor directories (the reconstructed case is enough)."""
    target = RUN / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("processor*", "reports"))
    return target


def _open(app, path: Path, wall_patches: tuple[str, ...] = ()):
    """The project in a window; ``wall_patches``: the part patches when the case has no mesh record (the
    validation drivers meshed some cases outside the window)."""
    from vortexcfd.core.project import Project

    w = _window(app, Project.open(path))
    if wall_patches and not w._mesh_patches:
        w._mesh_patches = wall_patches
    return w


def _mesh(app, w) -> None:
    if not w.mesh_view.has_mesh:
        w._load_mesh_view()
    w._set_scene_mode("mesh")
    app.processEvents()
    if not w.mesh_view.has_mesh:
        raise RuntimeError("no mesh in the viewer")


def _results(app, w) -> None:
    w.results_tab.click()
    _wait(app, lambda: w.results_view is not None and w.results_view.has_results, 600)
    app.processEvents()


def _field(w, key: str) -> None:
    label = next(text for text, k in w._field_keys.items() if k == key)
    w.field_combo.setCurrentText(label)


def _camera(w, position, focal, up=(0.0, 0.0, 1.0), parallel_scale=None) -> None:
    cam = w.viewer.camera
    cam.position, cam.focal_point, cam.up = position, focal, up
    if parallel_scale is not None:
        cam.parallel_projection = True
        cam.parallel_scale = parallel_scale
    w.viewer.renderer.ResetCameraClippingRange()
    w.viewer.render()


def _export(w, name: str) -> None:
    from vortexcfd.gui.image_export import export_image

    image = export_image(w.viewer, OUT / name, SIZE)
    log.info("%s: %d actors, %d scalar bars", name, image.actors, image.scalar_bars)


def images(app) -> None:
    from vortexcfd.foam import polar_sweep
    from vortexcfd.foam.physics_case import flow_direction
    from vortexcfd.workflow import line_plot, report
    from vortexcfd.workflow.meshing import flow_speed

    OUT.mkdir(parents=True, exist_ok=True)
    # -- the sphere: geometry, mesh, results, streamlines, a line plot, the residuals ------------------------------
    w = _open(app, RUN / "sphere" / "sphere.vcfd")
    w._set_scene_mode("geometry")
    _camera(w, (-60.0, -75.0, 40.0), (8.0, 0.0, 0.0))
    _export(w, "sphere_domain.png")
    w.mesh_tab.click()
    _mesh(app, w)
    _camera(w, (0.0, -6.0, 0.0), (0.4, 0.0, 0.0))
    _export(w, "sphere_mesh_section.png")
    _results(app, w)
    w.display_combo.setCurrentText("Both")
    _field(w, "U_mag")
    _camera(w, (0.8, -9.0, 2.5), (1.2, 0.0, 0.0))
    _export(w, "sphere_velocity.png")
    w.display_combo.setCurrentText("Walls")
    _field(w, "Cp")
    project = w.project
    project.add_scene_object("streamlines", seed="plane", point1=(-1.0, 0.0, 0.0), normal=(1.0, 0.0, 0.0), size=0.9,
                             n_seeds=144, max_length=12.0, direction="forward", color_field="U_mag")
    _camera(w, (-2.0, -7.0, 3.5), (1.5, 0.0, 0.0))
    _export(w, "sphere_streamlines.png")
    line_id = project.add_scene_object("line_plot", point1=(-2.0, 0.0, 0.0), point2=(8.0, 0.0, 0.0), n_samples=400,
                                       fields=["U_x", "Cp"])
    samples = w.results_view.line_samples[line_id]
    line_plot.write_png(samples, OUT / "sphere_line_plot.png", "Line plot 1")
    case = project.folder / "case"
    png = report.residual_png((case / "log.simpleFoam").read_text())
    (OUT / "sphere_residuals.png").write_bytes(png)
    dispose(w)
    # -- the NACA 0012 at 15 degrees: the near field, the wall-resolved layers ------------------------------------
    naca = _copy_project(REPO / "run" / "validation" / "naca0012" / "r3_alpha_15", "naca0012_15")
    w = _open(app, naca / "naca0012.json", ("naca0012",))
    w.mesh_tab.click()
    _mesh(app, w)
    points = np.asarray(pv.read(str(naca / "case" / "constant" / "triSurface" / "naca0012.stl")).points)  # rotated
    te = points[np.argmax(points[:, 0])]  # the rotated trailing edge
    log.info("trailing edge at %s", te)
    _camera(w, (te[0] - 0.01, -5.0, te[2]), (te[0] - 0.01, 0.0, te[2]), parallel_scale=0.02)
    _export(w, "naca_trailing_edge_layers.png")
    _results(app, w)
    w.display_combo.setCurrentText("Section")
    _field(w, "U_mag")
    _camera(w, (0.5, -5.0, 0.0), (0.5, 0.0, 0.0), parallel_scale=0.6)
    _export(w, "naca_velocity_15deg.png")
    dispose(w)
    sweep = json.loads((REPO / "tests" / "data" / "sweep_naca0012_r3.json").read_text())
    points = [polar_sweep.SweepPoint(**p) for p in sweep["points"]]  # the round 3 results (tests/data/README.md)
    (OUT / "naca_polar.png").write_bytes(report.polar_png(points))
    # -- the pipe: the velocity on a section, the pressure along the axis ------------------------------------------
    pipe = _copy_project(REPO / "run" / "validation" / "pipe" / "massflow" / "pipe", "pipe")
    w = _open(app, pipe / "pipe.vcfd")
    _results(app, w)
    b = w.results_view.volume_bounds()
    w.display_combo.setCurrentText("Section")
    _field(w, "U_mag")
    centre_y, centre_z = (b[2] + b[3]) / 2, (b[4] + b[5]) / 2
    x60 = b[0] + 0.75 * (b[1] - b[0])  # 60 D of the 80 D pipe: the developed region
    w.results_view.set_section(axis=0, position=x60)
    _camera(w, (x60 - 2.0, centre_y, centre_z), (x60, centre_y, centre_z), up=(0.0, 0.0, 1.0),
            parallel_scale=0.6 * (b[5] - b[4]))
    _export(w, "pipe_velocity_section.png")
    line_id = w.project.add_scene_object("line_plot", point1=(b[0], centre_y, centre_z), point2=(b[1], centre_y, centre_z),
                                         n_samples=500, fields=["p", "U_mag"])
    samples = w.results_view.line_samples[line_id]
    line_plot.write_png(samples, OUT / "pipe_axis_line_plot.png", "Pipe axis")
    log.info("pipe u_ref %.4g, direction %s", flow_speed(w.project), flow_direction())
    dispose(w)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    isolate_settings("vortexcfd_manual_settings_")  # never the user's settings (D-141)
    app = QApplication.instance() or QApplication(sys.argv)
    what = sys.argv[1] if len(sys.argv) > 1 else "images"
    {"sphere": sphere, "images": images}[what](app)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        from vortexcfd.gui.teardown import finish

        finish()  # every window and plotter ended while the application exists (D-164)
    sys.exit(code)
