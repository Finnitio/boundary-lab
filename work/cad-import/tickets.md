# CAD import — local tickets

## Status (2026-10-13)
- T0 DONE, merged to feat/cad-import (62e6763). `reduced: bool` on GeneratedGeometry/Reference; `validate_reduced_assembly` in generators/resources.py; `configuration_snapshot()["frequency"] = {freq_min_hz, freq_max_hz, freq_count}`. Reduced assembly under symmetry Off is accepted as full model (CAD provider must reject mismatch itself).
- T1 DONE, merged (3c2f409). Package `blab.cad_import`: `inspect_step(path, *, forward, up) -> CadGeometry`; `mesh_step(path, CadImportSettings, output_dir) -> CadImportResult`. Types: CadGeometry(bodies, faces, regions, interfaces, bbox_m, symmetry, warnings), CadBody, CadFace(id, bodies, step_name, centre, area, normal, surface_type), CadRegion(mesh_id, kind, bodies), CadInterface(name, mesh_id, face_ids), CadMesh(id, purpose, path, volume_groups, surface_groups). BEM mesh id `exterior`; air mesh id = slug of first body; surface groups `"<body> opening"`, user groups, `walls`. Interface BEM boundary uses same group name in mesh `exterior`. CLI `blab cad-import`. Fixtures `tests/cad_fixtures.py`. Face IDs = gmsh tags after fragment.
- Open decisions (ask user): size floor only when override < target; growth only grades overrides, not curvature; two-sided diaphragms not modellable under interface rule.
- Untracked `tests/fixtures/cad_import/*.STEP` (likely user's real exports) — unused so far.
- NEXT: T2 (frontier). User asked to stop after T1.

Spec: `docs/specs/cad-import.md` (repo). Glossary: `GLOSSARY.md`. Exploration notes: `notes.md` (this folder).
Integration branch: `feat/cad-import`. User stories referenced as US#.

## T0 — Host: accept already-reduced assemblies under symmetry
Blocked by: none
Scope: spec "Host change (slice 0)" + Testing "Slice 0". US 46, 47.
- Assembly may declare itself already reduced; host checks every resource lies in positive X / positive X,Y region (reuse existing symmetry checks); outside → atomic rejection. Unreduced assemblies under symmetry still rejected. Host never cuts.
- Document the declaration in the provider API guide.
- Also (decision, see notes.md "Decisions"): add read-only frequency block (freq_max_hz etc.) to `configuration_snapshot`; document in provider API guide.
Done when: tests via generator assembly test fixture cover accept-X, accept-XY, reject-outside-region atomically, unreduced still rejected; snapshot carries freq_max_hz and patches can't set it.

## T1 — Headless core + CLI
Blocked by: none
Scope: spec "Meshing pipeline", "Sizing rule", "Interface detection", "Symmetry suggestion", "CLI". US 1-8, 9-12 (axis mapping, headless only), 13-21 (mesh/groups/interfaces data, not System wiring), 33-41, 44-45 (detection + mismatch rejection), 59-60.
- Headless pipeline package `src/blab/cad_import/` (no Qt; see notes.md Decisions). Takes fmax and c as explicit inputs. STEP read (OCC, metres), axis mapping, classify, fragment, interface + symmetry-open-edge detection, single conformal mesh with size fields (target size c/fmax/N, per-body & per-face-group overrides, curvature ~12/circle, growth ≤1.3, smallest override = floor), split into one tet mesh per connected air-body group (volume group per air body) + one BEM exterior surface mesh; face groups on both sides of interfaces; default walls group; warnings (covered air face, exterior gaps with open edges); bbox report; stable default names for unnamed bodies.
- CLI command: STEP path, fmax, elements per wavelength, output folder → writes assembly meshes. Same pipeline → identical output as provider.
- Fixtures built in code with Gmsh OCC → STEP (vented box: chamber+port+exterior; waveguide: throat+exterior; mm units). Helper to strip names.
Done when: tests on generated meshes (groups, edge lengths, node-matching at interfaces, axis mapping, symmetry detection, rejections) + CLI e2e test pass.

## T2 — Provider package, 3D editor, visibility tree
Blocked by: T1 (and T0 for symmetry acceptance tests)
Scope: spec "CAD import is a bundled geometry provider", "Design source" (path, axis mapping, N, overrides, curvature/growth; face groups field may be present but empty), "Editor" (viewport, body/face tree, visibility, Show all, Clear, sizing settings w/ computed target size, Mesh/Cancel, revisions/busy). US 6-8 display, 20-21, 28-37, 42, 46 (provider declares reduced), 55-58.
- Bundled provider packaged like vented_enclosure; returns assembly + regions, default walls rigid boundary, detected interfaces (entity + interface boundaries both sides) in one response; c and fmax from request project config.
- Closable CAD Import dock; meshes appear in Meshes locked to design; project save/restore without re-mesh.
Done when: provider-contract tests (catalog load → generate from fixture → stage → compile physical system / prepare solve), incl. under X/XY symmetry; UI tests for dock generate, tree visibility, Show all/Clear.

## T3 — Face picking, face groups, orientation pickers, System entries
Blocked by: T2
Scope: US 9-11 (pickers in editor), 22-27, 38-39 (override UI), 17-18 already from T1/T2 kept consistent.
- Face picking in viewport (drivable via editor API), name a face group spanning several faces; STEP face names → groups; groups persisted in design source with STEP names + fingerprints.
- Provider sends boundary entries only for NEW face groups (rigid), never resends existing; user roles/weights/components/channels survive regeneration.
Done when: tests: picking via API creates group → regenerate → physical group in mesh + rigid boundary in System; user marks moving + attaches component → regenerate → preserved; orientation picker change remeshes reoriented.

## T4 — Re-import matching + STEP file watching
Blocked by: T3
Scope: spec "Re-import matching", "Watching the STEP file". US 48-54.
- Match faces by STEP name, then fingerprint (centre, area, normal, surface type) within tolerance. Any group without faces → reject before response; previous meshes kept; unmatched groups reported to editor as needing review; re-pick repairs; delete group sends boundary removal + component detachment in same patch.
- On app focus regain, changed STEP file → re-mesh prompt (no auto regenerate).
Done when: tests regenerate from modified fixtures (named, and name-stripped for fingerprint), unmatched rejection with meshes kept, delete-group patch, focus-change prompt.
