# CAD/STEP import, CAD bridge & adaptive meshing — design notes

Status: idea, to be floated in the DIYAudio thread before any upstream issue.
Source: grilling session 2026-10-08.

## Priority

1. STEP import (meshed in blab)
2. SolidWorks plugin (phase 1 file-based, phase 2 live bridge)
3. Frequency-adaptive remeshing

## Facts from the codebase

- `gmsh` is already a dependency, used via Python API (`ath_gmsh_worker.py`, `interface_conform.py`, `mesh_clean.py`). STEP needs only the OCC kernel (`gmsh.model.occ.importShapes`).
- Only `.msh` imports with named physical groups exist today; boundaries bind to group **names** (`physical_compiler.py`).
- Imported `.msh` sources are re-checked when the app regains focus → file-based live reload already exists.
- `blab.cli server` exposes HTTP, but solve-only (no GUI control, no parameters).
- `fem_validation.py` already computes points-per-wavelength per frequency.
- Results are per frequency (`live.py`) → stitching band results is structurally plausible.

## STEP import

- Meshing happens in blab with Gmsh (required for adaptive remeshing).
- Units: auto-convert via `Geometry.OCCTargetUnit = "M"`.
- Groups: STEP face/body names (OCC/XDE labels, `Geometry.OCCImportLabels`) → physical groups.
- Roles are assigned in blab per name; on STEP reload, same name ⇒ assignment restored automatically.
- Surfaces **and** volumes in v1. `occ.fragment` over all shapes ⇒ shared faces exist once, conforming FEM/BEM interfaces without `conform-interface`.
- Mesh size: global size always settable, plus per-edge / per-face / per-volume overrides.
- Project: STEP files and generated meshes stored alongside the `.blab.json` (relative paths); project stores name→role mapping and mesh-size settings.
- Out of scope: unnamed / duplicate-name face handling.

## SolidWorks plugin

- Lives outside blab (C#/.NET COM add-in, Windows). Repo location TBD with maintainer.
- Phase 1: plugin exports named-face STEP; blab auto-reloads.
- Phase 2: generic **CAD bridge** API — local HTTP on localhost with token (reuse server infra), so Fusion2Msh or other CAD could use it too.
  - Parameters: SolidWorks global variables with a prefix (e.g. `blab_`); plugin publishes them, blab can change them → SW rebuild → re-export → remesh.
  - Solve can be triggered from SW; runs in the open blab GUI, results show there.

## Adaptive meshing

- Exterior BEM and interior FEM.
- Only for remeshable sources: Ath (regenerate) and STEP. Imported `.msh` stays fixed.
- Strategy (per band vs. finer granularity) open — decide after measuring meshing time vs. solve time.

## Open / risks

- **Biggest risk:** does SolidWorks reliably write face names into STEP (AP214/AP242) that Gmsh reads? Fallback: face colours. Must be verified on a real SW export.
- Plugin repo ownership.
- Adaptive band strategy (needs measurement).
