**Some usability ideas: GUI layout, STEP import and a CAD bridge**

Hi JW, thanks for the update. I've had two ideas in draft for a while and merged them into one post here. I'm happy to do the implementation work myself. What I'd like to know first is whether you'd want these in main, since I don't plan to maintain my own Boundary Lab fork. If something doesn't fit your vision for the project, that's completely fine. I'd rather hear it now than open a PR you don't want.

---

**1. GUI layout: Model Tree (COMSOL-style), with beginners in mind**

I know you like the classic Windows-style dialogs because they keep the advanced features out of a beginner's way, and I agree that's worth keeping. What I'd like to fix is a few concrete pain points:

- Editing a component takes about 7 clicks and 2 stacked dialogs (System → Components → select → Edit → change → OK → OK). The dialogs also cover the mesh preview, so you can't see which surface you're editing.
- The GUI doesn't make clear what is actually part of the model. For example, the **Multi_region_SAWMOD** example opens with an Ath design window ("waveguide"). Its config is empty and nothing in it is used for the solve, because the model is built entirely from the imported `.msh` files. A beginner would reasonably think they need to do something there.

The idea is a three-pane layout: **Model Tree | Settings | Graphics** (clickable prototype: https://claude.ai/artifact/LvW144hTQdnwUQd4UWM6Lk).
- The tree shows the project in workflow order: Geometry → Meshes → System (Regions, Boundaries, Interfaces, Components) → Channels → Solve → Results. It mirrors `.blab.json`, so the file format doesn't change.
- It only shows what the model contains. In SAWMOD you'd see four imported meshes and no Ath node.
- The graphics follow the selection: select a component and its moving surfaces are highlighted with the motion arrow, and the other meshes are ghosted.
- The tree shows state: Interfaces is greyed out until both region types exist, invalid components are disabled with a reason, and Solve/Results are marked *out of date* after model changes.

**To keep advanced features hidden from beginners**, the tree could start with only the basic nodes. Advanced nodes and settings (interfaces, symmetry, loss models, solver options…) would appear when you add them via right-click/"+" or turn on a "Show advanced" toggle. You'd get the same progressive disclosure the dialogs give today, without the modal stacking.

It can be done incrementally: (1) tree + settings pages hosting the existing dialog contents, (2) selection-aware graphics reusing the mesh preview's surface picking, (3) Plot Groups and undo. If the full layout is too big a change, a smaller step would also help: non-modal dialogs that leave the preview visible, and hiding unused generator windows like the one in SAWMOD.

---

**2. STEP import, a CAD bridge and adaptive meshing**

Today, geometry comes either from Ath or from imported `.msh` files with named physical groups. Boundaries are bound to those group names, and an imported `.msh` is re-checked when the app regains focus, so a file-based "live reload" already exists. The idea builds on that, in three steps that are each useful on their own.

**2a. STEP import, meshed inside Boundary Lab**

Gmsh is already a dependency, so only its OpenCASCADE kernel (`gmsh.model.occ.importShapes`) is needed to load STEP directly.
- **Units:** converted automatically on import, so there's no more guessing whether a mesh is in mm or m.
- **Names → groups:** named faces and bodies in the STEP become physical groups, just like the named groups in a `.msh` today. You assign roles (rigid, moving, interface…) per name once in Boundary Lab. When the STEP is changed and reloaded, faces with the same name get their assignments back automatically.
- **Surfaces and volumes:** solids become FEM regions and surfaces become BEM boundaries. All shapes are run through `occ.fragment`, so faces shared between a FEM volume and the exterior exist only once. That gives **conforming FEM/BEM interfaces by construction**, with no separate conform step (compare `exteriorBEM.msh` vs. `exteriorBEM_interface_conformed.msh` in SAWMOD).
- **Mesh size:** a global element size that can always be set, plus per-edge, per-face and per-volume overrides, e.g. finer at the throat and coarser on the baffle.
- **Project:** STEP files and generated meshes are stored alongside the `.blab.json` with relative paths. The project stores the name→role mapping and the mesh-size settings.
- **Out of scope for a first version:** handling unnamed or duplicate-named faces. Those would just produce a clear error.
- **Main risk:** whether SolidWorks reliably writes face names into STEP (AP214/AP242) in a form Gmsh reads. I'd verify that on real exports before writing any code. The fallback would be face colours.

**2b. CAD bridge, starting with SolidWorks**

This would live *outside* Boundary Lab (a C#/.NET add-in in its own repo). The only part in Boundary Lab would be a small, CAD-agnostic API.
- **Phase 1, file-based:** the add-in exports a named-face STEP with one click, and Boundary Lab reloads it the way it reloads `.msh` today. This needs nothing new in Boundary Lab beyond 2a.
- **Phase 2, live bridge:** a small HTTP API on localhost with a token, reusing the existing `blab server` infrastructure.
  - **Parameters:** SolidWorks global variables with a prefix (e.g. `blab_throat_dia`) are published to Boundary Lab and can be changed from there. SolidWorks then rebuilds and re-exports, and Boundary Lab remeshes.
  - **Solve from CAD:** a solve can be started from inside SolidWorks. It runs in the open Boundary Lab window, and the results show there.
  - Because the API is CAD-agnostic, Fusion2Msh or other CAD tools could use it too.

**2c. Frequency-adaptive remeshing**

Since meshing happens inside Boundary Lab for Ath and STEP sources, low-frequency bands could be solved on coarser meshes, both the exterior BEM and the interior FEM. Given BEM's quadratic memory scaling, that could save a lot of time and VRAM. `fem_validation.py` already computes points per wavelength per frequency, and results are stored per frequency, so stitching bands together looks structurally feasible. Imported `.msh` files would stay fixed. I'm honestly not sure how much it gains: the banding strategy (per band, or finer) depends on meshing time vs. solve time, and I'd measure that first.

---

**Questions**
- Would you want a tree layout in main if it keeps a beginner-friendly default view? Or would you rather start with the smaller dialog fixes?
- Live editing + undo, or keep explicit OK/Apply?
- Would you accept a STEP/OCC import path in main? And later a localhost bridge API for CAD tools (the add-in itself would live elsewhere)?
- Would you be interested in moving Fusion2Msh onto such a bridge, or keep it `.msh`-based?
- Any of these you'd rather keep out of Boundary Lab's scope entirely?
