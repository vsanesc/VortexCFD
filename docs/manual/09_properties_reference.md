# 9. Properties reference

What each section of the Properties panel does, with its defaults and why. The "?" next to a section title opens
the matching heading here. Every numeric field shows its unit; a field with an **Auto** box shows the value in use,
greyed, while Auto is ticked (untick it to set your own, starting from that value). Hover over any field for its
tooltip: what it does, its default and why. Right-click a field written to the case for **Show in OpenFOAM file**.

## Mesh sizing

- **Background cells** (default 100,000): the uniform background mesh over the whole domain, before any refinement.
  It sets the background cell size; the refinement levels do the rest.
- **Surface cell size** (default 0.01 x l_ref): the cell size wanted on the part surfaces, as a fraction of the
  length under **Relative to**: l_ref (Reference Values; the default) or L, the parts' largest extent (projects made
  before v10). The line under the field gives the size in metres and the length's value. The first refinement level
  at or below it is used ("Surface cell (achieved)" in the cell estimate).
- **Background cell size** (Auto): computed from the background cells and the domain volume; set it to fix it.

## Surface refinement and curvature

- **Surface level min / max** (Auto): the refinement levels of the surfaces (each level halves the background
  cell); the maximum applies along sharp edges (**Feature angle**, default 30°). A part can override them in its own
  properties.
- **Curvature levels** (default 2, at most 4): where a surface bends (leading edges, small radii) snappyHexMesh adds
  up to this many levels beyond the maximum surface level, so a radius keeps about four cells. Each extra level can
  multiply the cells near curved surfaces several times; the cell estimate follows the field as you change it.

## Prism layers

Prism layers are thin cells stacked on the part walls to resolve the boundary layer.

- **Sized from a target y+** (default): the first cell's height gives the **Target y+** (default 50, the wall
  function range 30-300; about 1 resolves the viscous sublayer and is meshed wall-resolved) at the free-stream speed;
  the count follows from the surface cell. The panel shows the **first-layer height**, the **layer count**, the
  **expansion** used and the **total / final** thickness, all in metres; "Planned / achievable" warns when the layer
  cap makes the stack thinner than planned (D-106).
- **Thickness relative to the surface cell size**: the outermost layer is **Final layer thickness** (default 0.5)
  of the local surface cell; the **Layer count** (default 3) and **Expansion ratio** (default 1.2) are yours. The
  computed heights are shown as approximations (the surface cell varies with the level).
- **Minimum layer thickness** (default 0.1 x cell): thinner layers are not added.
- **Layer controls**: Robust (default; at most 30 layers, the expansion raised up to 1.3 to keep the stack),
  Wall-resolved (chosen automatically below y+ 5), Legacy (projects saved before v13).

## Parallel meshing

**Meshing cores** (Auto): the recommendation from the estimated cells (12,500 per core, at most 8); untick Auto to
set it. The tooltip says what is in use and why. The mesh is reconstructed into one serial mesh (chapter 6.4).

## The cell estimate

The background cells (nx x ny x nz), the extra cells of the refinement volumes, the achieved surface cell and the
finest curvature level. The background is capped at 2,000,000 cells; Generate Mesh says so when the settings go
beyond it.

## Free stream

- **Free-stream speed** (default 20 m/s): the undisturbed flow along +x at the inlet; the reference speed of the
  coefficients and of the y+ layer sizing.
- **Turbulence intensity** (default 1 %): the inlet's velocity fluctuations, k = 1.5 (I U)². A wind tunnel is about
  0.1-1 %, open air 1-5 %.
- **Viscosity ratio** (default 10): the inlet's turbulent to molecular viscosity, which sets ω.
- **Angle of attack**: read-only here; it is set in Geometry > Body attitude (the link selects it).
- **Computed**: the Reynolds number Re = U∞ l_ref / ν and the Mach number Ma = U∞ / a, each with the speed and the
  length it uses (a warning above Ma 0.3: the app is incompressible), and the inlet k and ω. Internal flow has no
  Free stream: each inlet shows its Re on its hydraulic diameter with its bulk velocity (a velocity inlet's speed,
  ṁ / (ρ A) for a mass flow; a total-pressure inlet's is known after the run, from its mass-flow report), and the
  Physics node the first inlet's. The **speed of sound** a (Physics, default 343 m/s) only gives the Mach number.

## Body attitude

All the parts rotate together, as one rigid body, about the centre of rotation.
**Angle of attack α** (Geometry or Parts node; external flow only): the rotation of the parts about the y axis,
nose up positive, relative to the free stream, which always blows along +x (lift is +z, drag +x). The **rotation
centre** is shown below it: Reference Values > Centre of rotation, Auto the centre of the parts' box. A change puts
the mesh out of date; the geometry files are not changed.

## Domain size

**Reference length L**: the largest extent of the box around the parts the domain is sized around; every extent is
a multiple of it, so the domain follows the parts. Each extent (upstream, downstream, lateral or half-width,
vertical, radius) can be entered in **L**, **m** or **mm**: the button beside the field switches the unit, converting
the value to the same length, and the other form is shown under it. The project stores each extent in its own unit:
an extent in L follows the parts when they change, one in m or mm stays that length. **Dimensions** gives the
domain's size in metres. Defaults: 5 L upstream, 10 L downstream, 5 L to each side and
above and below (the 2D airfoil preset: a C-type of radius 50 L).

## Domain boundaries

Select a face of the domain (Regions > Fluid Domain) or right-click it. **Boundary type**: Velocity inlet, Pressure
outlet, Slip (far field), Symmetry, Wall (no-slip, stationary) or Moving wall (with the free stream); the box's
bottom face can also be the **Ground plane**. The presets set the defaults: the inlet a velocity inlet, the outlet a
pressure outlet, the other faces slip. **Conditions written** lists what each field gets on that face. A wall face
gets the parts' wall functions; tick its **Prism layers** box (off by default) to give it the parts' layers too. Run Solver needs at least one velocity inlet and one pressure
outlet. A wall (or moving wall) face is how to study ground effect on any face.

## Ground plane

The box's bottom face as a wall at the parts' lowest z or at a value, stationary or moving with the free stream,
optionally with prism layers and a slip strip ahead of where the wall starts (a wind tunnel's ground board).

## Surface preparation

Needed when parts cross or touch each other or come from CAD that was not sewn: it makes them mesh as one clean
outer surface. **Intersection features** keeps the parts and gives snappyHexMesh their crossing curves as sharp
features; **CAD union** fuses them into one solid (the default; a part that cannot be fused falls back to
intersection features). Run it again after the parts change.

## Refinement volumes

Boxes, cylinders, spheres, cones (Add, or right-click Refinement volumes), a wake box behind the parts, or an
imported surface (Add from imported geometry, or a part's Use as refinement region). Each has a **Target cell
size**; the mesh uses the first level at or below it. An imported surface refines **Inside the surface** (a closed
surface only) or **Within a distance** of it (on either side; the surface may be open, such as a sheet or a wake
surface). A closed surface starts in the inside mode, an open one in the distance mode (one surface cell).

## Reference values

**Reference density** (only scales the forces), the **reference area** (from its basis: planform or frontal box
area, or custom), the **reference length l_ref** and the **centre of rotation** (one "(x, y, z)" field in metres;
pasted "1.2 0 -0.5" works). While Auto, the fields show the values in use; their tooltips say where they come from.
Set l_ref and the area for a wing (the mean chord and the wing area).

## Stopping criteria

Residual, asymptotic and mean-stable criteria, combined with all or any, after the minimum iterations and up to the
maximum (in iterations). The oscillation check warns when a monitored quantity oscillates (chapter 7). They apply to
the next run; the monitors show the criteria of the run they judge ("Criteria of the last run").

Solvers also has the **Live view** (on by default) and its interval (**Live view every**, default 50 iterations): what
the Results Scene shows while the solver runs; it only samples and never changes the solution.

## Transient

On the Solvers node of a transient project (Physics > Flow: Incompressible, transient; D-181). Chapter 10 explains
the choices.

| Field | Default | What it does |
|---|---|---|
| Time step | Adaptive | Adaptive: each step from the Max Courant number; Fixed: the step set below |
| Max Courant number | 1 | U Δt / Δx at its largest in the mesh; 1 resolves the flow in time with the PISO mode |
| Time step Δt | Auto | The fixed step, or the adaptive run's first step (auto: t_c / 200 fixed, t_c / 1000 adaptive) |
| Largest time step | Auto | An adaptive step never grows above it (auto: t_c / 50) |
| Outer correctors | 1 | PIMPLE outer correctors per step (1 = PISO); raise only above Co 1 |
| Pressure correctors | 2 | Pressure corrections per outer corrector |
| Times in | Flow-through times | The unit of the end time, write interval, sampling start and window: t_c = l_ref / U, or seconds |
| End time | 200 t_c | The run ends here |
| Write interval | 20 t_c | The full and averaged fields are written this often and at the end |
| Sampling starts at | Auto | The statistics start here; Auto: detected once the start-up transient is over |
| Window | 20 t_c | The window of the start-up detection and of the statistics stop |
| Stop when statistically converged | off | Also end once the running mean of the coefficient below is stable over the window |
| Statistics of | Cd | The coefficient of the statistics stop and of the detection's mean |
| Tolerance | 0.5 % | The running mean's range over the window, relative to its value (floor 0.01) |
| Start from | The free stream | Or the latest time of this project's steady solution on the current mesh |

## Probes

A point probe of p and U written every iteration. The **Location** is one "(x, y, z)" field in metres: type or paste
"1.2 0 -0.5" or "(1.2, 0, -0.5)"; a wrong entry is shown on the field and not applied.

## Mesh independence study

Meshes and solves the case three times, the cell size changed by the **ratio r** between levels (default √2, about
2.8 times the cells per level in 3D), and judges the chosen reports with the grid convergence index (GCI, Celik et
al. 2008): an error band on the finest mesh's value, from the apparent order of convergence and the
Richardson-extrapolated value. It applies when the three values converge monotonically; oscillating or diverging
values get no GCI. **Current settings are** fine (default: two coarser levels are added) or medium (one coarser,
one finer). In 3D the refinement buffers keep their size in metres, so the levels are not exactly similar and the 3D
GCI is indicative (chapter 8).

## Polar sweep

For lifting bodies: the case at several angles of attack, each with its own mesh (the parts turned) and a run from
the free stream, giving CL, CD and CM against the angle. Off in a new project: tick **Enable the polar sweep** to set
the angles (a range or a list) and run it.

## Part checks

The part's surface: triangles, size, open and non-manifold edges, self-intersections, the other parts it crosses,
orientation and whether it is watertight. Fix problems with Repair part or Surface Preparation.

## Part regions

The part's regions (from STL solids or CAD faces) and their patches: rename, merge, split by feature angle, or a
patch per region; each patch becomes a wall with its own forces.
