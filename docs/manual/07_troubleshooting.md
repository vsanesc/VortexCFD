# 7. Troubleshooting

## 7.1 checkMesh: hard and soft failures

After every mesh the app runs checkMesh and classifies each failed check (D-100):

- **Hard** failures make the mesh unusable; Run Solver and the polar sweep are blocked, and the badge reads "Mesh
  invalid: checkMesh failed". They are: zero or negative cell volumes or face areas, incorrectly oriented face
  pyramids, faces above 90 degrees non-orthogonality, open cells, invalid face labels, faces not in upper
  triangular order, an open boundary, and any failure checkMesh counts without describing it.
- **Soft** failures are quality warnings; the solver can run, the badge reads "Mesh: warnings" and the Run Solver
  tooltip lists them: skewness above 4, aspect ratio above 1000, concave cells, small face interpolation weights,
  small volume ratios, small determinants, unused points, and the severely non-orthogonal faces (70 to 90 degrees).

What to do with a hard failure: look at the Mesh report's checkMesh lines. Inverted pyramids or negative volumes
usually come from the layer phase at sharp or thin features: try the default "robust" layer controls, a finer
surface near the feature, or fewer layers; run Edit > Surface Preparation for intersecting parts. A lost part (a part
with no faces in the mesh, usually too small or thin for the background cells) also blocks the solver: refine the
surface or the part's levels.

Soft warnings near sharp trailing edges or in the layers are common; check the results there before relying on them.

## 7.2 The first-cell drift warning

*Layers collapsed near the wall: first cell X mm vs Y mm planned; y+ will be about N times the target.* After
meshing the app walks the mesh and measures the wall-adjacent cell height (D-109). When its area-weighted mean is
more than 1.5 times the plan, the layers collapsed somewhere and y+ will be off by that factor; the Mesh report and
the Run Solver tooltip say so. Look at the layer table for the patch with low coverage; then refine the surface
there, use the robust layer controls, or accept a higher y+ (with wall functions a y+ up to about 300 is fine).

## 7.3 An oscillating steady run and the mean-stable criterion

A steady solver on a flow with strong separation (a bluff body, a stalled wing) often never settles: the forces
oscillate about a steady mean and the residuals stall. The monitors flag a quantity whose relative oscillation over
the last window is above the threshold (default 1 % over 100 iterations, D-059).

For such runs stop on the **mean-stable** criterion (Solvers > Stopping Criteria, D-118): the mean of a quantity
(for example Cd) over the last W iterations against the mean of the W before, within a tolerance (default 500
iterations and 0.5 %). The report and the mesh study then use the windowed mean, not the last value, with the half
range of the oscillation beside it (D-119). The range-based "asymptotic" criterion is never met by an oscillating
quantity; use it for runs that settle.

## 7.4 A run that will not converge

1. Look at the console: a crash prints OpenFOAM's stack trace block in the error colour; a diverging solver dies
   with a floating point exception (SIGFPE) and often prints no nan residual: the Run state says "Crashed".
2. Check the mesh first: hard failures block the run, but soft warnings (high skewness, small weights) can still
   make it diverge; refine or simplify where they are.
3. Check the set-up: the free-stream speed and the viscosity (the Reynolds number), the reference values, and for
   internal flow at least one inlet and one outlet with sensible values.
4. Internal flow with a total-pressure inlet converges slowly by design (SIMPLE with a relaxed pressure, D-131); a
   mass-flow inlet is the robust choice when the flow rate is known.
5. Let it run longer (Solvers > Iterations) when the residuals still fall; stop on the mean-stable criterion when
   the forces oscillate (7.3).
6. Open the case in ParaView (Open in ParaView, top bar) to look at the fields where the residuals peak.
