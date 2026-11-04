# Model Assumptions

Boundary Lab is a frequency-domain linear-acoustics application for predicting
loudspeaker radiation and internal acoustic loading. It supports three
physical-system topologies:

- an unbounded exterior region only, solved with BEM;
- one or more bounded tetrahedral air regions only, solved with sparse FEM;
- one or more bounded tetrahedral air regions coupled to an unbounded exterior
  BEM region, with optional lumped electrodynamic transducer equations.

The application infers the path from the regions configured in the **System**
window. It is intended to answer questions about acoustic response,
directivity, source interaction, enclosure and port behavior, and linear
transducer loading. It is not a general structural, thermal, or nonlinear
finite-element package.

## Physical System and Boundary Conditions

Every active mesh surface belongs to an acoustic region and is classified as:

1. **Rigid**: zero normal surface velocity. A bounded rigid wall of an air
   region may optionally use the supported locally reacting Miki porous-lining
   treatment.
2. **Moving**: motion is supplied by one prescribed-velocity or
   electrodynamic component.
3. **Interface**: pressure and normal flux are transferred between a bounded
   FEM region and the exterior BEM region.
4. **Plane-wave tube termination**: the bounded FEM weak form receives a
   first-order outgoing-wave Robin condition. It is not an interface.

The UI defaults every surface to Rigid and does not provide an unassigned or
unused state. This prevents an omitted assignment from silently behaving as an
opening.

An exterior-only model accepts prescribed-velocity components. Interior and
coupled models may use prescribed-velocity components, linear electrodynamic
transducers, or both. A component can own several moving surface groups, and
each group can have a relative velocity weight. This supports idealized motion
profiles such as a dome and surround moving at different amplitudes.

Prescribed-velocity components use a canonical 1 m/s velocity basis. New
exterior-only BEM sources default to a shared rigid-translation axis, inferred
automatically or entered manually; normal velocity is the signed projection
onto each face's normal. Saved surface-normal sources and new interior/coupled
sources apply the basis as normal velocity on each face. Relative boundary weights apply in both modes. Axis magnitude is
normalized away. Axial prescribed sources are not supported in interior or
coupled systems.
Electrodynamic components use a canonical 2.83 V basis and a single rigid-body
translation degree of freedom with direct Re, Le, Bl, Mmd, Cms, and Rms
parameters. Their front and rear acoustic surfaces may belong to different
regions and do not need matching meshes.

The electrodynamic model includes linear motor force, back EMF, mechanical
mass, compliance, damping, voice-coil inductance, and reciprocal acoustic
loading. It does not model cone breakup, nonlinear or position-dependent motor
parameters, thermal compression, suspension nonlinearities, or flexible
enclosure structures. See [Coupled Solver](Coupled%20Solver.md) for the precise
supported contract and limitations.

## Linear Excitation Bases and Channel Synthesis

The acoustic solver computes an independent complex reference response for
each active excitation port. Application channels then combine those bases and
apply level, polarity, delay, and idealized analog HPF/LPF transfer functions.
Because this synthesis is linear and occurs after the physical solve, ordinary
channel edits can reuse completed basis data without rerunning BEM or FEM.

The Maximum SPL projection also reuses the linear basis, but deliberately
operates before channel synthesis. For every voltage-only electrodynamic
channel it scales isolated on-axis pressure until either the one-way peak Xmax
of an assigned component or the voltage equivalent of its rated Pmax is
reached. The rated voltage is `sqrt(Pmax * Re)` and the solver's RMS displacement
is multiplied by `sqrt(2)` before comparison with peak Xmax. One channel-level
rating pair is shared by every component on that channel; heterogeneous driver
ratings require separate channels in this first implementation.

When **Normalized Channel Correction** is enabled, Boundary Lab evaluates each
channel's isolated response at the configured horizontal reference angle and
applies a real magnitude correction before the channel controls. This makes
the isolated channel magnitude target flat before crossover shaping. It is not
a complex phase inverse, does not remove propagation or transducer phase, and
does not guarantee that a summed multiway response will be flat.

Passive electrical networks, amplifier source-impedance interaction, feedback
control, and level-dependent processing would alter the physical solve rather
than act as ordinary post-solve channel weights. They are not part of the
current application model.

## Exterior Boundary Integral Model

In the unbounded region, acoustic pressure satisfies the frequency-domain
Helmholtz equation:

$$
\nabla^2 p + k^2 p = 0
$$

where:

- `k = omega / c`;
- `omega = 2 pi f`;
- `c` is the sound speed.

The exterior mesh is the boundary of the acoustic domain. Prescribed outward
normal velocity is converted to Neumann data using the solver's
`exp(+i omega t)` convention:

$$
q = \frac{\partial p}{\partial n} = -i \rho \omega v_n
$$

where `rho` is fluid density. Rigid surfaces use `v_n = 0`; moving surfaces use
the component velocity projected onto the face normal. Interface surfaces in a
coupled system receive their normal derivative from the FEM-BEM solution.

Boundary pressure is represented with continuous first-order (`P1`) basis
functions and boundary velocity/flux with discontinuous constant (`DP0`) basis
functions. BEAT Engine assembles dense Galerkin operators and uses direct dense
linear algebra. The Bempp backend uses Bempp-cl operators and GMRES.

The classical exterior Neumann equation can be written as:

$$
\left(K - \frac{1}{2} I\right) p = S q
$$

with single-layer operator `S`, double-layer operator `K`, identity `I`,
unknown boundary pressure `p`, and prescribed Neumann data `q`. This classical
form can become unreliable at fictitious interior resonances. Boundary Lab's
Burton-Miller combined-field path adds the hypersingular and adjoint
double-layer equations to suppress those artifacts, at additional assembly
cost. The shared BEAT Engine implementation is described in [BEAT Engine
Core](advanced/beat-engine-core.md).

After solving the boundary pressure, exterior pressure at observation point
`x` is evaluated from the representation formula:

$$
p(x) = D[p](x) - S[q](x)
$$

where `D` and `S` are the double- and single-layer potentials.

## Interior FEM Model

With bounded regions and no unbounded region, Boundary Lab assembles only the
first-order pressure FEM system and factors it as a sparse matrix on the CPU.
Disconnected chambers remain acoustically separate unless one shared
electrodynamic component couples their moving surfaces. Rigid walls are the
natural boundary condition; homogeneous bulk loss, rigid-backed Miki wall
treatments and porous region materials use the same formulations as a coupled
solve.

A plane-wave tube termination imposes the first-order outgoing condition
$\partial p/\partial n=-i k p$ for the `exp(+i omega t)` convention. It represents
the characteristic impedance $\rho c$ of a locally uniform tube, not a hidden
exterior region. Its accuracy degrades when higher-order or evanescent modes
are significant at the cut plane. See [Interior FEM Solver](advanced/Interior%20FEM%20Solver.md).

## Porous Region Materials

A bounded region may be filled with a porous material such as foam, fibre
wadding, or mineral wool. Boundary Lab models the fill as an **equivalent
fluid**. The FEM unknown is the pore pressure. The region uses a complex,
frequency-dependent effective density ρ_eq(ω) and bulk modulus K_eq(ω) instead
of air's ρ0 and ρ0c0². The model assumes that:

- the material is homogeneous and isotropic throughout the region;
- pores and fibres are much smaller than the wavelength, so pressure and
  velocity are macroscopic averages over many pores;
- the frame is either rigid or limp. Full Biot poroelasticity, an elastic frame
  with its own waves and resonances, is not modelled;
- the acoustics are linear. Flow resistivity does not depend on level.

The effective properties follow J.-F. Allard and N. Atalla, *Propagation of
Sound in Porous Media*, 2nd ed., Wiley 2009:

- Johnson effective density ρ(ω) = ρ0[α∞ + νφ/(jωq0)·G(ω)] with q0 = η/σ
  (Eqs. 5.50, 5.52).
- Simplified Lafarge bulk modulus K(ω) with static thermal permeability k0′
  (Eqs. 5.51, 5.53). JCA uses k0′ = φΛ′²/8 (Eqs. 5.54, 5.55), which reduces it to
  the Champoux–Allard form. JCAL with that k0′ is JCA.
- Equivalent fluid ρ_eq = ρ/φ and K_eq = K/φ (Eqs. 5.43, 5.44). In this form,
  pressure and normal volume velocity are continuous at a region seam or an
  FEM-BEM interface without a porosity factor. Moving boundaries and interfaces
  of a porous region relate velocity to the pressure gradient through ρ_eq.
- A limp frame replaces the rigid-frame density with Panneton's approximation
  ρ_limp = (ρ_t·ρ_eq − ρ0²)/(ρ_t + ρ_eq − 2ρ0), with ρ_t = ρ1 + φρ0
  (Eq. 11.55). K_eq is unchanged.

ρ0 and c0 come from the region. The air viscosity η = 1.84 × 10⁻⁵ Pa·s, the
Prandtl number ≈ 0.72, and γ = 1.4 are the constants that thermoviscous wall
losses use. The static pressure is P0 = ρ0c0²/γ, so a resistance-free, fully
open material reduces exactly to the region's air. The book writes fields as
e^(+jωt). That matches Boundary Lab's `exp(+i omega t)` convention with j = i,
so a passive material has Im ρ_eq < 0. The BEAT Engine
[Porous materials](https://github.com/JWSound/BEAT_Engine/blob/main/docs/Porous%20Materials.md) page lists the full formulas, the assembly, and
the validation against analytical tube and layer solutions.

### Choosing a model and frame

- **JCA** needs porosity, flow resistivity, tortuosity, and the viscous and
  thermal characteristic lengths. All built-in presets provide these values.
- **JCAL** adds a measured static thermal permeability k0′, which refines the
  low-frequency bulk modulus (the isothermal-to-adiabatic transition). Without a
  measurement, keep JCA. The dialog prefills k0′ = φΛ′²/8, which reproduces JCA.
- A **rigid frame** assumes the skeleton does not move. This fits heavy or
  stiff materials such as mineral wool, glass-wool boards, and foam bonded to
  a wall. It also fits any material well above its decoupling frequency
  F_d ≈ σφ²/(2πρ1).
- A **limp frame** assumes the skeleton moves with the air but has no
  stiffness. This fits light, loosely packed wadding. Below F_d its density
  approaches the total apparent density ρ_t, which adds the fibres' inertia to
  the air. Well above F_d it approaches the rigid result. For the Soft fibrous
  preset (σ = 25 000 Pa·s/m², φ = 0.98, ρ1 = 30 kg/m³), F_d ≈ 127 Hz.
- Neither frame represents frame resonances, or compressed or bonded elastic
  foams whose skeleton stiffness matters in the band. Those cases need Biot
  theory.

Preset values are book data for specific samples. Real products vary, so use
manufacturer or measured data where available. Typical loudspeaker waddings
such as polyester, BAF, or Sonofil are not in the book and have no preset.

### Mesh resolution

A porous region needs a finer mesh than air. Its wavelength
λ = 2π/Re(k_eq), with k_eq = ω√(ρ_eq/K_eq), is shorter, and the wave decays
along its path. At 5 kHz it is about 57.5 mm in Soft foam and 52.6 mm in Glass
wool, against 68.6 mm in air. The BEAT Engine convergence study measured these
thresholds at the maximum solve frequency for about 5 % (0.4 dB)
input-impedance error:

- P1: at least 11 elements per porous wavelength;
- P2: at least 3 elements per porous wavelength.

The compiler compares each porous region's mean tetrahedron edge with λ/N at
the highest solve frequency. If the edge is longer, it reports the warning
`porous_mesh_too_coarse` with the needed edge length. The solve still runs.
Boundary Lab does not refine the mesh. Set a smaller volume element size for
that region where the mesh is made, in Gmsh or the generator, and re-import
it. The check uses the mean edge, so a strongly anisotropic mesh, such as thin
slabs across a tube, may warn although it resolves the propagation direction.

### Porous-region limitations

Inside porous regions, Boundary Lab's velocity-derived field displays compute
particle velocity from the pressure gradient with the air density ρ0, not with
ρ_eq(ω). The affected displays are Particle Velocity Magnitude and Acoustic Flow
Arrows (active and reactive intensity, animated velocity) on observation planes
and in the Element Field. Their values inside a porous region differ from the
macroscopic velocity by the complex factor ρ_eq/ρ0 in magnitude and phase.
Pressure, SPL, and impedance are correct everywhere. So are the solver's
diaphragm, interface-velocity, and exterior results, and velocity displays in
air regions.

Porous materials are also limited to bounded FEM regions. They cannot be used
in the exterior BEM region or in a lumped sealed rear chamber. Their boundaries
cannot carry plane-wave terminations, thermoviscous wall losses, or Miki
linings. Coupled porous solves run on the BEAT CPU and CUDA backends only. ROCm
and Metal reject them before the solve. Interior porous solves always run on
CPU. Anisotropic, double-porosity, full Pride–Lafarge, and Wilson models are not
available, and JCA/JCAL cannot be used as a locally reacting wall impedance.

## Coupled FEM-BEM Model

See [Coupled Solver](Coupled%20Solver.md).

## Symmetry

X symmetry uses a positive-X half model; XY symmetry uses a
positive-X/positive-Y quarter model. The active mesh must lie in that
fundamental domain. BEAT Engine includes reflected BEM source contributions
and evaluates the full observation field from the reduced solve.

Boundary Lab determines separately whether each component and FEM-BEM
interface is actually cut by an active symmetry plane. For an electrodynamic
component, selected moving-surface perimeter adjacency determines its surface
completion factor and the number of distinct physical components represented
by symmetry images. These values are inferred from topology rather than chosen
from a manual multiplier.

Symmetry assumes the omitted geometry and excitation are exact mirror images.
It is therefore invalid for asymmetric geometry, material properties,
component parameters, or drive conditions.

## SPL, Directivity, and Balloon Data

Complex pressure magnitude is converted to sound-pressure level with:

$$
\mathrm{SPL} = 20\log_{10}\left(\frac{|p|}{20 \times 10^{-6}}\right)
$$

On-axis plots and on-axis text exports retain absolute SPL for each solved
channel basis after the selected channel correction. Directivity plots are
normalized during visualization to their configured reference angles and then
optionally smoothed and clipped to the selected display range. Polar exports
contain normalized magnitude and relative phase.

When Balloon Sampling is enabled, the solver evaluates approximately
equal-area Fibonacci-sphere directions. Those solved points are used directly
as balloon vertices, and a shared spherical triangulation supplies the display
and export topology. The balloon mesh therefore scales with the requested
sampling precision without first interpolating onto a separate latitude and
longitude grid. Slice plots still interpolate the spherical data along their
requested great-circle directions.

## Practical Limitations

Results remain subject to mesh resolution, geometry and physical-group
quality, interface conformity, numerical precision, observation distance, and
the assumptions above. Dense BEM storage and factorization grow rapidly with
boundary size; fine meshes should be tested at a few representative
frequencies before committing to a long sweep.

Boundary Lab currently does not provide:

- structural diaphragm, suspension, or enclosure-panel FEM;
- nonlinear, transient, thermal, or level-dependent behavior;
- automatic conversion from a conventional T/S set containing Mms to the
  direct Mmd parameter used by the electrodynamic model;
- passive-radiator components;
- arbitrary surface impedance functions or spatially varying volume loss
  within one region (materials are homogeneous per region);
- poroelastic (Biot) materials, frame resonances, or porous material outside
  bounded FEM regions (see [Porous Region Materials](#porous-region-materials));
- multiple unbounded exterior regions or different gases (density or sound
  speed) within one coupled system;
- iterative, fast-multipole, or distributed coupled solving.

Use measurement or a suitable structural/electroacoustic tool where these
effects dominate, and treat Boundary Lab's result as the prediction of the
configured linear acoustic model rather than the complete behavior of a real
loudspeaker.
