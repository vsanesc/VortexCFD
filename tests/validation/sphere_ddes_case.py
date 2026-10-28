"""The DDES functional run (task 1.1-transient Part 2, Part B 3b; docs/validation/ddes_sphere/SETUP.md): a sphere
of diameter D = 1 m at Re = U D / nu = 10,000, k-omega SST DDES, 3D, set up through the app. No Qt. A functional run
(no verdict): the vault note's DDES cases with a published reference (the wall-mounted hump, the Ahmed body, the
cylinder at Re 3900) do not fit the machine time of this part.
"""

from pathlib import Path

DIAMETER = 1.0
SPEED = 1.0
NU = 1e-4  # Re = 10,000

# The focus region (D-191; Spalart 2001): a box around the sphere and its near wake, cells of FOCUS_SIZE (D / 20,
# finer than the 0.068 D of the guide's coarser cylinder grid), 40 cells across its smallest extent (at least 32).
FOCUS_SIZE = 0.05
FOCUS_BOX = ((1.375, 0.0, 0.0), (3.75, 2.0, 2.0))  # centre and size: x from -0.5 D to 3.25 D (centre at 0.5 D)

END_TIME = 40.0  # t_c
SAMPLING_START = 15.0  # t_c: after the 10 t_c perturbation and a few t_c of development (set, not detected)
CORES = 8


def write_sphere(path: Path) -> Path:
    import pyvista as pv

    sphere = pv.Sphere(radius=0.5 * DIAMETER, center=(0.5 * DIAMETER, 0.0, 0.0), theta_resolution=180,
                       phi_resolution=90)
    sphere.save(str(path))
    return path


def build_project(folder: Path, end_time: float = END_TIME, cores: int = CORES, **transient_settings):
    """The project in ``folder``: the "External flow" preset, transient k-omega SST DDES at Re 10,000, the sphere,
    the default domain and mesh with the focus box."""
    from vortexcfd.core.model import BoxShape, Part, RefinementVolume
    from vortexcfd.core.presets import BUILTIN_PRESETS, apply_preset
    from vortexcfd.core.project import Project

    folder = Path(folder)
    (folder / "geometry").mkdir(parents=True, exist_ok=True)
    project = Project.new("sphere_ddes")
    project._sim = apply_preset(project.sim, next(p for p in BUILTIN_PRESETS if p.name == "External flow"))
    project.update_physics(nu=NU, flow="incompressible_transient")
    project.update_physics(turbulence_model="kOmegaSSTDDES")
    project.update_inflow(speed=SPEED)
    project.update_reports(reference_length=DIAMETER)
    project.update_solver(cores=cores, live_view=False)
    project.update_transient(end_time=end_time, write_interval=end_time, sampling_start=SAMPLING_START,
                             **{"perturb": True, **transient_settings})  # the run used the inflow swing (D-198)
    centre, size = FOCUS_BOX
    project._sim = project.sim.model_copy(update={"refinement_volumes": [RefinementVolume(
        id="focus", name="Focus", shape=BoxShape(centre=centre, size=size), target_size=FOCUS_SIZE,
        frame="wind")]})
    project.save(folder / "sphere.json")
    write_sphere(folder / "geometry" / "sphere.stl")
    project.add_part(Part(name="sphere", source_file="geometry/sphere.stl", units="m"))
    project.save()
    return project
