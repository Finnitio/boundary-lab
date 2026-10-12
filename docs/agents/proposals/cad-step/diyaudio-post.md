**Idea: STEP import, CAD bridge (SolidWorks) and adaptive meshing**

Hi all, hi JW — I'd like to float an idea before opening any issues, to see if it fits where Boundary Lab is heading.

**1. STEP import, meshed inside Boundary Lab**
Gmsh is already a dependency, so its OpenCASCADE kernel could load STEP directly:
- Named faces/bodies in the STEP become physical groups. You assign roles (rigid, moving, interface…) in Boundary Lab once; when the STEP is reloaded, faces with the same name get their assignments back automatically.
- Surfaces and volumes: solids become FEM regions, and fragmenting the shapes gives conforming shared faces without a separate conform step.
- Global mesh size plus per-edge/face/volume overrides; units taken from the STEP.
- STEP files and generated meshes stored alongside the project file.

**2. CAD bridge, starting with SolidWorks**
- Phase 1: a SolidWorks add-in exports named-face STEP, and Boundary Lab reloads it (just like `.msh` reload today).
- Phase 2: a small local HTTP API (localhost + token) so the CAD side and Boundary Lab can talk both ways: expose prefixed global variables (e.g. `blab_throat_dia`), change them from Boundary Lab and get the rebuilt model back, or start a solve from inside the CAD tool with results showing in the open Boundary Lab window.
- The API would be CAD-agnostic, so Fusion2Msh could use it too. The SolidWorks add-in would live in its own repo.

**3. Frequency-adaptive remeshing (later)**
Since meshing happens in Boundary Lab for Ath and STEP sources, low-frequency bands could be solved on coarser meshes (BEM and FEM). Given the quadratic memory scaling of BEM, that could save a lot of time and VRAM. Imported `.msh` would stay fixed. The banding strategy would depend on measured meshing vs. solve time. Not sure how much could be gained by this approach though

**Questions for JW**
- Would you accept a STEP/OCC import path and a local bridge API upstream?
- Would you be interested in moving Fusion2Msh onto such a bridge, or would you rather keep it `.msh`-based?
- Any parts you'd prefer to stay out of Boundary Lab's scope?

I'd be happy to do the implementation work if this fits.
