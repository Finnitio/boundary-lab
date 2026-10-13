# CAD Import — exploration notes (for implementers)

Paths relative to repo root. HEAD at time of writing `df0fe8e`. Prior art commits: `a56901f` (vented enclosure, #43), `e198523` (assemblies, #42).

Env: project venv `.venv/Scripts/python.exe` (3.13.5); system `python` lacks gmsh — use the venv. Policy hook blocks multi-line `python -c`: put scripts in scratchpad, run `python -I <file>`.
Venv: gmsh 4.15.2 (OpenCASCADE + OpenCASCADE-CAF → STEP labels/names), meshio 5.3.5, numpy 2.5.3, pyvista 0.49.0, PySide6 6.11.2, vtk 9.7.1. Windows runtime lock `packaging/requirements-win.txt`: gmsh 4.15.2, pyvista 0.48.4, pyvistaqt 0.11.4.

## Decisions (settled by orchestrator / user)
- **c and fmax**: add a read-only frequency block (`freq_max_hz`, plus whatever is natural e.g. min/count) to `configuration_snapshot` (contract change, additive, document in provider API guide; `validate_patch` must keep rejecting it as a patch section). c = sound_speed of the unbounded_air region in `configuration["physical_system"]` if present, else 343.0. Done in T0.
- **Core location**: Qt-free headless core in `src/blab/cad_import/` (package). CLI command `blab cad-import` in blab. Provider worker (`geometry_providers/cad_import/...`) imports `blab.cad_import` (verify `-I` worker can import blab; editable install keeps site-packages).
- **Reduced declaration**: typed field on `GeneratedGeometry` + `GeneratedGeometryReference` (e.g. `reduced: bool = False`, meaning "already reduced for the project symmetry"), round-tripped in project payload. Done in T0.
- **Rejection reporting to editor (T4)**: run matching in the editor (Qt-free module) before Generate, and also enforce in provider; no new event kind unless unavoidable.
- **Bundled enablement**: generalise `bundled_provider_ids()` + "introduced" settings gate to cover cad_import (T2).
- **STEP path**: stored as given (absolute) in source.

## 1. Generator / provider contract
### `src/blab/generators/base.py` (re-exported from `blab.generators`)
- `PROVIDER_API_VERSION = 1` (l.18).
- `generated_mesh_id(document_id, local_id)` → `f"{document_id}/mesh/{local_id}"` (l.21): stable host mesh ID. Display name `generated_mesh_name(doc, local_id)` = `"<sanitized design name>__<local_id>"` (`resources.py:11`).
- `GeneratorCapabilities` (l.31): `supports_symmetry` unused for assemblies.
- `GeneratedMesh(id, purpose, mesh_path=None, mesh_data=None)` (l.41): id `[a-z][a-z0-9_-]*`; purpose `bem_surface`|`fem_volume`; exactly one of path/data.
- `GeneratedGeometryReference` (l.70): persisted artifact; has `meshes`, `provider_metadata`, `mirror_axes`.
- `GeneratorDocument(id, name, provider_id, provider_schema_version, source, mesh_enabled, mesh_scale_factor=0.001, mesh_translation_mm, artifact)` (l.86).
- `GenerationRequest(provider_id, document_id, mesh_name, source, run_root, case_name, provider_options, schema_version, request_id, project_revision, configuration)` (l.100); deep-copies source/configuration/provider_options.
- `GeneratedGeometry(provider_id, output_dir, mesh_path, radiators, ..., mirror_axes, provider_metadata, meshes)` (l.125). `__post_init__` l.143–165: with `meshes`, forbids mesh_path/mesh_data/cleaned/reduced fields/radiators/mirror_axes; provider_metadata must be finite JSON. `to_reference()` l.193.
- `GenerationResponse(request_id, geometry, configuration_patch={}, schema_version=1)` (l.218): omitted configuration preserves host values.
- `complete_generation(request, response)` (l.232): checks version/request_id/provider_id, `validate_patch`, rejects bare GeneratedGeometry with meshes → `GenerationCompleted(request, result, configuration_patch, legacy_response)`.
- Protocols: `GeneratorSession.generate(*, status_callback, stop_requested)`, `.stop()`; `GeneratorBackend.create_session(request)`, `.restore(document)`. `GenerationCancelledError`.

### Patch semantics `src/blab/generators/configuration.py`
- `ENTITY_SECTIONS` (l.34): regions, surface_assignments (Boundary), interfaces, component_assignments, excitation_ports. `PATCH_SECTIONS` adds component_parameters, channel_config, component_channels, symmetry_config, stitching_config.
- `configuration_snapshot(project)` (l.50): physical_system dict, channel_config, component_channels, symmetry_config{mode}, stitching_config. No frequency (docstring l.4) — T0 adds it.
- `project_revision(project)` (l.66): sha256 of asdict(project) minus active tab; includes project_preferences → freq edits invalidate in-flight generation.
- `validate_patch` (l.122): rejects unknown sections/fields, null, dup ids, non-finite.
- `_merge` (l.110): objects merge recursively, arrays replace, None raises = "omitted fields preserved".
- `_owned_entities(system, mesh_ids)` (l.186): boundaries owned if group on its meshes; regions if all mesh_ids within; components if all boundary_ids owned (incl. user-created components attached only to CAD boundaries); ports/interfaces derived.
- `_check_references` (l.202): component with empty boundary_ids invalid → deleting a group that is a component's only boundary requires removing component + ports in same patch.
- `apply_configuration_patch(project, patch, *, document_id, mesh_ids)` (l.229): new IDs must start `document_id + "/"`; existing IDs must be owned; `remove` lists must name owned entities; physical update sets `AUTO_SEEDED_EXTERIOR_KEY=False`; `symmetry_config.mode` changes `project.symmetry` (l.339).

### Staging `src/blab/generators/application.py`
- `stage_generation(project, generated, completed, *, imported_radiators)` (l.21) → detached candidate; callers commit project+artifact together. Rejects stale revision ("Generation discarded because project inputs changed."), changed source/provider. Routes to `_stage_assembly` when `geometry.meshes`.
- `_stage_assembly` (l.128):
  - **l.130–131** `if project.symmetry != "off": raise ValueError("Generated mesh assemblies currently require symmetry Off.")`
  - seeds empty `PhysicalSystem("system:loudspeaker")` (l.166); rejects overwriting unowned mesh IDs / name collisions; builds MeshResources with design scale/translation.
  - auto-adds BEM resource IDs to existing `unbounded_air` region when a surface_assignments upsert references that region (l.192–204) — how a provider joins the shared exterior.
  - applies patch; **l.211–212 second symmetry rejection** (patch sets symmetry_config); retires old_ids−new_ids; `_check_references`; every new mesh must be in a region (l.225).
  - **l.229 `PhysicalSystemCompiler().compile(candidate.physical_system)` uses default symmetry_mode="off"** — slice 0 must pass `candidate.symmetry`.
  - then `infer_physical_solve_kind`, sets artifact.

### Other assembly symmetry rejections (slice 0)
- `src/blab/generators/resources.py:21` `generated_mesh_entries(document, result, symmetry="off")`, **l.30–33** raises "Generated mesh assemblies currently require symmetry Off; automatic coupled reduction is unsupported." when symmetry != off and mesh_enabled. Entries `locked=True`, `assembly_id=document.id`.
- `src/blab/generators/postprocess.py:12` `ensure_reduced_geometry(result)` **l.20–23** same message for result.meshes. Called from `src/blab/ui/mesh_preparation.py:38–39` (`MeshPreparationSnapshot.entries`) and `src/blab/ui/main_window/mesh_workflow.py:258–273` (`_generated_geometry_for_solver_symmetry`, rewrites artifact).
- `src/blab/headless.py:128` `load_headless_project` → `generated_mesh_entries(document, result, symmetry)` raises under symmetry.
- Persistence: `src/blab/project/model.py` `_artifact_to_payload` (l.269) / `_artifact_from_payload` (l.302) reject mirror_axes with meshes. `registry.restore_generator_document` (`registry.py:84`) rebuilds assembly from artifact. New typed field → base, model, registry.
- Must keep passing for unreduced: `tests/test_generator_assemblies.py:168` `test_assembly_rejection_is_atomic[symmetry]` (patch `{"symmetry_config":{"mode":"x"}}`) and l.227 (`generated_mesh_entries(document, geometry, "x")` match "symmetry Off").

### Positive-region / symmetry checks to reuse
- `src/blab/symmetry.py`: `_SYMMETRY_AXES={"off":(),"x":(0,),"xy":(0,1)}`; `symmetry_plane_tolerance_m(points_m)` (l.53) max(1e-9, 1e-6×bbox diag); `snap_points_to_symmetry_planes` (l.70); **`validate_reduced_mesh_config(mesh_config, symmetry, *, tolerance_m=None)` (l.91)** raises `SymmetryValidationError` (l.31) "Mesh '…' is not in the positive X fundamental domain for X symmetry. Vertex i has x=… m after scale and translation." Reads `meshio.read(mesh_config.file)` only (no mesh_data) → switch to `read_resource_mesh`. Scale default 0.001 when None. Only used in tests/test_symmetry.py today. `validate_reduced_mesh_configs` (l.125). `MeshConfig(name, file, scale_factor, translation_m, mesh_data)` in `config.py:63`.
- `src/blab/interface_conform.py`: `_validate_positive_symmetry_domain` (l.764) inside `build_conforming_interface_map(..., symmetry_mode)` (l.564), run from `PhysicalSystemCompiler._compile_interface` (`physical_compiler.py:607`).
- `src/blab/mesh_topology.py:73` `analyze_exterior_mesh_topology(mesh_configs, symmetry)`: open BEM edges on active planes allowed (`_exclude_symmetry_plane_edges` l.153). Use for symmetry-plane open edges.
- `PhysicalSystemCompiler.compile(system, symmetry_mode=...)` (`physical_compiler.py:80`): snaps points (`_transformed_mesh` l.763), infers component symmetry (`component_symmetry.infer_component_symmetry`).
- `system_solve.prepare_system_solve(..., symmetry_mode=)` (l.87) and headless already thread symmetry.
- Fixtures: `tests/fixtures/SAWMOD/SM{femvolume,exterior}_reduced_{x,xy}.msh` — NOT conformal as-is (`test_interface_conform.py:358` conforms them). Assembly fixtures `femvolume.msh`, `exterior_conforming.msh` (mm) are full & symmetric (X −50..50, −125..125): good for "unreduced still rejected" and "declared reduced but outside positive region → atomic reject". A genuinely reduced conformal accepted case needs a new fixture (Gmsh OCC in test, or conform a SAWMOD reduced pair).

### Provider API guide `docs/advanced/geometry-provider-api.md` (674 lines)
"Named mesh assemblies" (l.117–189), esp. l.184–189 "This increment supports full models with symmetry Off…"; "Patch semantics" symmetry note (l.266–270); "Validation" (l.452); manifest table l.331; editor contract l.355–426.

## 2. Bundled vented-enclosure provider `geometry_providers/vented_enclosure/`
- `provider.json`: manifest_version 1, id `blab.vented_enclosure`, provider_api 1, source_schema_version 1, backend `enclosure.backend:create_backend`, editor `enclosure.editor:create_editor`, default_source{…}, mesh_scale_factor 1.0 (metres). `README.md`. `enclosure/__init__.py`, `parameters.py` (Qt-free FIELDS/DEFAULTS/validate), `backend.py`, `worker.py`, `editor.py`.
- Discovery `src/blab/generators/catalog.py`: `provider_roots()`=APP_ROOT/"geometry_providers" (l.23); **`bundled_provider_ids()` (l.27) hardcodes vented_enclosure** — add cad_import. `ProviderManifest.read` (l.48). `ProviderCatalog(roots, enabled, reserved=("ath","ath4"))` (l.88): `scan()`, `package(id)`, `factory(id,"backend"|"editor")` imports under private namespace `_blab_provider_<hash>` (use relative imports), `source_defaults(id)`. `provider_catalog()` singleton (l.188); tests monkeypatch `catalog_module._catalog`.
- `registry.generator_info(provider_id)` (`registry.py:62`) → `editor_kind="custom"`; `create_generator` (l.77); `available_generator_infos`.
- First-run enable: `src/blab/ui/settings.py:168` `load_gui_preferences` adds bundled ids once, gated on QSettings `providers/vented_enclosure_introduced` (l.178–181, l.278) → generalise.
- Packaging copies whole `geometry_providers/` (`scripts/build_windows_runtime.py:156`, `scripts/restage_windows_application.py:77`).
### backend.py
- `configuration_patch(request)` (l.16): IDs `document_id + "/…"`; joins existing `unbounded_air` region from `request.configuration["physical_system"]` (l.21); adds regions/components only if absent (l.24,34,55); upserts boundaries (`group={"mesh_id","dimension":2,"name"}`) and interface (`bounded_boundary_id`/`unbounded_boundary_id`); sets component_channels only if route absent (l.82).
- `EnclosureSession.generate` (l.102): rejects symmetry != off (l.110); writes `run_root/vented_enclosure_<uuid>/source.json` (fresh folder); `subprocess.Popen([sys.executable,"-I","-B","-X","utf8", worker.py, source.json], creationflags=CREATE_NO_WINDOW)` logging to meshing.log; polls `wait(timeout=0.1)` + `check_cancelled()`; `stop()` terminates; reads `mesh_info.json` → `GenerationResponse(request.request_id, GeneratedGeometry(provider_id, output, None, (), source_path=…, meshes=(GeneratedMesh("interior","fem_volume",…), GeneratedMesh("exterior","bem_surface",…)), provider_metadata=…), patch)`.
- `EnclosureBackend.restore()` → None (host restores assembly). `create_backend(**options)`.
### worker.py
- Runs `-I` (no package context): siblings via `runpy.run_path` (l.14–20); only gmsh/meshio/numpy.
- Gmsh pattern `build()` (l.23): initialize, `General.Terminal=1`, `NumThreads=2`, occ.*, `occ.removeAllDuplicates()`, `addSurfaceLoop(sewing=True)`, `addPhysicalGroup(3,[vol],10,"air")` + named surface groups, `Mesh.MeshSizeMax/Min`, `MeshSizeFromCurvature=20`, `mesh.setSize`, `generate(3)`.
- **FEM write** (l.158–165): remove BEM-only physical groups, `Mesh.MshFileVersion=4.1`, `Binary=0`, `SaveAll=0`, `gmsh.write`. BEAT volume importer needs native Gmsh 4.1 ASCII with entity classification.
- **BEM write** (l.166–177): `meshio.write(..., file_format="gmsh22", binary=False)` with cell_data `gmsh:physical`, `gmsh:geometrical`, field_data `{name:[tag,2]}`. Geometrical tags required on BEM triangles (`interface_conform._triangle_data` l.705/714). Nodes compacted per resource.
- `orient_closed(points, tri)` (l.193): watertight, connected, orientable, orient outward. Shared interface triangles identical in both exports = node-for-node conformity.
- Writes `mesh_info.json`, `geometry.brep`.
- Several FEM meshes from one Gmsh model: re-scope physical groups per export, or use meshio 4.1 writer as `speaker_symmetry._gmsh41_mesh` (l.654).
### editor.py `EnclosureEditor(parent, host)` (l.80)
- `self.source`, `self.revision`; `apply_source(source, revision)` blocks signals; `edited` → `host.update_source(source|{k:v}, expected_revision=self.revision)`; `host.services.subscribe(self.event)`; `event.kind=="geometry_accepted"` → "Meshes accepted."; `set_operation_state(state)` → `tabs.setEnabled(not state.active)`; `dispose()`; `create_editor(parent, document_host)` (l.198).
### Host side
- `src/blab/ui/provider_editor.py`: `SourceSnapshot` (l.26); `ProviderEditor` protocol (l.32: widget, apply_source, set_operation_state, dispose); `DocumentHost(window, document)` (l.40): `snapshot()` (revision sha256), `update_source(source, *, expected_revision)` (`ProviderHostError("stale_source")`), `generate(*, expected_revision)` (raises busy; returns pending_request_id), `services` (scoped ProviderHost), `dispose()`.
- `src/blab/ui/main_window/generator_documents.py`: `generation_context()` (l.53); `accept_generation(completed)` (l.57) re-checks revision, `stage_generation`, commits project + `generated_geometry_by_document_id`; `update_provider_editor_states()` (l.97); `rebuild_generator_document_tabs()` (l.105) builds DocumentHost, calls `provider_catalog().factory(id,"editor")(container, host)`, validates non-dock QWidget; failure → read-only JSON placeholder; `self._provider_editors[doc.id] = (adapter, host)`; `new_default_generator_document` (l.263); `add_generator_document` (l.282).
- Design dock "Generator", objectName `ath_editor_dock`, closable: `view_builder.py:233` `_make_panel_dock` (l.197–210). Tabs `self.editor_tabs`; host Generate button `generate_button` (view_builder l.316/343).
- `src/blab/ui/main_window/geometry_workflow.py`: `GeometryWorkflowController.generate_geometry` (l.81) run_root `GENERATED_GEOMETRY_ROOT` (`constants.py:13`; tests monkeypatch `geometry_workflow.GENERATED_GEOMETRY_ROOT`). `_on_geometry_generated` (l.139) → `accept_generation`; rejection → `show_error("Geometry generation failed", msg)`; editors get no failure event.
- Events `generators/host.py`: only `"geometry_accepted"` (l.289), `"solve_status"`. `ProviderContext` (l.31) has freq_min_hz/freq_max_hz/freq_count via `services.context()` (Future, GUI thread).
- `src/blab/ui/generator_worker.py` `GeneratorWorker.run` (l.26): create_generator → create_session → generate → complete_generation; exceptions → `failed(str)`.

## 3. Gmsh, deps, tests, CI
- Gmsh in src/blab: `ath.py:466` `mesh_ath_geo_text` in-process under `ATH_GMSH_LOCK` (guards `gmsh.isInitialized()`, restores model); `ath_gmsh_worker.py` subprocess; `interface_conform.py:1419` `_remesh_planar_surface`.
- No OCC STEP import yet: `gmsh.model.occ.importShapes(path)` with `Geometry.OCCTargetUnit="M"`, `Geometry.OCCImportLabels=1`; then `occ.fragment`.
- Physical-group conventions: FEM = named volume group (dim 3) + named surface groups (dim 2); only region exterior faces count; faces shared by two selected tets are internal (`fem_topology.selected_volume_surface_tags` l.15) → **don't tag faces between touching air bodies in a merged mesh** ("assigns physical surface groups outside its selected volume groups"). Coverage `physical_compiler._validate_boundary_coverage` (l.690): every physical surface tag on each region mesh needs exactly one boundary → default walls group. BEM closed shell; open edges only on active symmetry planes. Group refs by **name** survive tag changes (guide l.276).
- `blab.mesh_data.read_resource_mesh(resource)` (l.172); `MeshData` (l.36).
- pyproject: deps beat-engine (git pin), gmsh, matplotlib, meshio, numpy, scipy; extras dev=[pytest, ruff>=0.15,<0.16], gui=[PySide6, pyvista>=0.47, pyvistaqt]; script `blab = "blab.cli:main"`; pytest pythonpath ["src"], testpaths ["tests"]; ruff py311, line-length 120, select E,F,I, ignore E501; no custom markers.
- `tests/conftest.py`: QT_QPA_PLATFORM=offscreen; `_isolate_qsettings`, `_cleanup_qt_windows`, `qapp`; `main_window` replaces MeshPreview with `StubMeshPreview` (no GL offscreen); `_stub_qt_interactor_class()` + `balloon_window` fixture show monkeypatching `pyvistaqt.QtInteractor`. **CAD editor 3D view needs same stubbing or graceful degrade** (MainWindow tests construct editors).
- `tests/gui_stack.py`: `BLAB_SKIP_GUI_TESTS=1` skips Qt modules. `tests/test_test_suite_health.py`: no `Path("src/…")` literals; use `tests/repo_paths.py` (REPO_ROOT, BLAB_SRC).
- CI `.github/workflows/ci.yml` (windows-latest, Py 3.11, offscreen, MPLBACKEND=Agg): `pip install -e ".[gui,dev]"`, `ruff check .`, `ruff format --check pyproject.toml scripts src tests`, `pytest`; engine integration job.
- AGENTS.md: focused `python -m pytest <file>`, `python -m ruff check src tests`; keep solve prep Qt-free.

## 4. CLI
- `src/blab/cli.py` `COMMAND_MODULES` (l.7): clean, conform-interface, gui, server, solve, prepare, plot, project, rocm. `main(argv)` → `import_module(mod).main(args.args, prog=f"blab {cmd}")`. New command = entry + module with `main(argv, prog=None)` and argparse `_build_arg_parser(prog)` (example end of `interface_conform.py`, `--force`, `parser.error`).
- Tests: `tests/test_cli.py` (monkeypatched import_module l.7; asserts COMMAND_MODULES l.31); `tests/test_headless.py:155` parser checks. No e2e CLI test yet → call `module.main([...])` with tmp_path.
- Docs: `docs/advanced/cli-workflow.md`; `docs/Inputs and Outputs.md:76–94`.

## 5. Test prior art
- `tests/test_vented_enclosure_generator.py`: `ROOT = parents[1]/"geometry_providers"`; fixture `plugin` (l.29) `ProviderCatalog([ROOT], enabled=[PROVIDER]).scan()` → `catalog.factory(PROVIDER,"backend")()`; private modules via `importlib.import_module(type(backend).__module__)`. `make_project(source)`: `replace(new_generator_document(name, provider_id=…, source=…), mesh_scale_factor=1)` → `ProjectDocument((doc,), doc.id)`. `make_request`: `GenerationRequest(..., configuration=configuration_snapshot(project))`. `generated`: `backend.create_session(req).generate()` → `stage_generation(project, {}, complete_generation(req, resp))`. Tests: compile+prepare+reopen (l.67: `PhysicalSystemCompiler().compile(system)`, `prepare_system_solve(...).solve_kind=="coupled_bem_fem"`, `write_project_file` + `load_headless_project`); conformity (l.97: rounded triangle point sets per group, watertight edges, positive volume orientation); regeneration preserves user edits (l.127); cancellation; shared exterior; invalid inputs `pytest.raises(ValueError, match=…)`.
- `tests/test_generator_assemblies.py`: fixture `assembly_case` (l.31) from `test_physical_compiler._bidirectional_electrodynamic_fixture_system()` (l.1724) with femvolume.msh/exterior_conforming.msh (mm), IDs remapped to `design/...`, mesh IDs `generated_mesh_id("design", local)`, `GeneratedGeometry("test.assembly", tmp, None, (), meshes=…)`. `stage(project, geometry, patch)` (l.75). Tests: coupled + regen with `{}` (l.91); save/reopen/headless/preview w/o plugin, `memory` param (l.120); `test_assembly_rejection_is_atomic` (l.168) faults group/purpose/interface/unowned/missing_mesh/stale/symmetry, asserts `project == before`; enable/transform/remove (l.216); shared exterior (l.243); retiring (l.265).
- `tests/test_ui_generator_assemblies.py`: `accept(main_window, assembly_case)` → `main_window.accept_generation(complete_generation(...))`; Meshes lock via `main_window._mesh_config_dialog_entries()`, `MeshConfigDialog`, `_apply_mesh_config_dialog_entries`.
- `tests/test_ui_vented_enclosure.py`: enable-once via `MemorySettings` (test_ui_settings). Editor test: monkeypatch `catalog_module._catalog`; `main_window.preferences.default_geometry_provider = PROVIDER`; `main_window.add_generator_document()`; `editor, host = main_window._provider_editors[doc.id]`; drive widgets, assert `host.snapshot().source`; `editor.set_operation_state(SimpleNamespace(active=...))`. Dock generate: monkeypatch `GENERATED_GEOMETRY_ROOT` + `show_error`; `host.generate(expected_revision=host.snapshot().revision)`; pump `qapp.processEvents()` while `geometry_controller.active` (30 s); assert artifact meshes, compiled interfaces, "accepted" in status.
- Also: test_provider_api.py, test_provider_packages.py (example_box at `tests/fixtures/geometry_providers/example_box`), test_ui_provider_editors.py, test_ui_provider_host.py, test_symmetry.py, test_interface_conform.py, test_component_symmetry.py.

## 6. Project config, persistence, Meshes, viewport
- fmax: `ProjectPreferencesState.freq_max_hz` (default 20000) `src/blab/project/model.py:31` on `ProjectDocument.project_preferences`; live GUI via `project_workflow.current_project_preferences()` (used in `_generation_project_snapshot`, `generator_documents.py:48`).
- c: per region `AcousticRegion.sound_speed_m_per_s=343.0` (`physical_model.py:97`); legacy `SimulationConfig.sound_speed` (`config.py:74`). No project-level c.
- Sizing test helpers: `fem_validation.tetrahedron_edge_statistics_m` (l.122), `frequency_mesh_resolution` (l.147).
- Save/load: `project/model.py` `generator_document_to_payload` (l.198), `generator_document_from_payload` (l.216), `_artifact_to_payload`/`_artifact_from_payload` (l.269/302). `project/io.py`: PROJECT_SCHEMA_VERSION=10, `write_project_file`, `read_project_file`, `resolve_project_paths` (l.66), `_project_payload_with_portable_paths` (l.118). Provider source opaque (not relativised). Cached meshes restore without plugin.
- Meshes: `MeshConfigDialog` (`src/blab/ui/dialogs.py:519`): generated rows locked, read-only name, assembly_id; assembly rows linked (`_append_row` l.622, `_sync_assembly` l.677); symmetry combo l.560–606. `mesh_workflow.py` `mesh_entries_for_symmetry` (l.57), `_apply_mesh_config_dialog_entries`. System interface rebuild refuses locked BEM meshes (`system_config.py:985`, 1020).
- File-watch prior art: `MainWindow.changeEvent` ActivationChange (`window.py:636–641`) → `_reload_updated_imported_meshes_on_focus` (`mesh_workflow.py:160`); fingerprint `(st_mtime_ns, st_size)` (`_mesh_source_fingerprint` l.137), 0.5 s debounce.
- 3D: pyvista + pyvistaqt QtInteractor. `src/blab/ui/mesh_preview.py` `MeshPreview` (l.129) falls back to label w/o pyvistaqt; checkable body tree overlay (`_ViewportTreeOverlay` l.85, `body_tree` itemChanged → `_surface_visibility`); hover picking `vtk.vtkCellPicker` (`_install_hover_picker` l.987, `_preview_interactor`); `_PreviewActorRecord` (l.76). `observation_plane_viewport.py:171` vtkCellPicker. Hierarchy: `src/blab/preview_hierarchy.py`. No click-to-select face picking yet.

## 7. conform-interface & System model
- `src/blab/interface_conform.py`: `conform_bem_interface_to_fem` (l.93), `conform_interface_mesh_files` (l.499), `validate_conforming_interfaces` (l.534), **`build_conforming_interface_map(fem, bem, fem_interface_name, bem_interface_name, coordinate_tolerance=1e-8, require_closed_bem=True, symmetry_mode)` (l.564)** used by compiler. GUI rebuild: `system_editing.rebuild_configured_interfaces` (l.244), `SystemConfigDialog._match_interface_pair`.
- `src/blab/physical_model.py`: `MeshResource(id, name, file, purpose, scale_to_m, translation_m, mesh_data)`; `AcousticRegion(id, name, kind bounded_air|unbounded_air, mesh_ids, volume_groups: PhysicalGroupRef(dim 3), sound_speed_m_per_s, density_kg_per_m3, loss_model)`; `Boundary(id, name, region_id, group=PhysicalGroupRef(mesh_id, dimension=2, name, tag), kind rigid|moving|interface|plane_wave_tube_termination|impedance|unused, parameters)`; `AcousticInterface(id, name, bounded_boundary_id, unbounded_boundary_id, coordinate_tolerance_m=1e-8)`; `PhysicalComponent(id, name, kind ideal_velocity_source|electrodynamic_transducer|passive_radiator, boundary_ids, parameters)`; `ExcitationPort(id, name, component_id, kind normal_velocity|voltage)`; `PhysicalSystem(...)`; `physical_system_to_dict/_from_dict`.
- Rules: `infer_physical_solve_kind` (l.155) ≤1 unbounded region; compiler `_validate_authoring_model` (`physical_compiler.py:255`): mesh purpose matches region kind; bounded region needs volume groups; interface boundary in exactly one interface & kind interface; moving boundary owned by exactly one component; port counts. Coupled solver only FEM–BEM interfaces → merge touching air bodies.
- System UI `src/blab/ui/system_config.py` `SystemConfigDialog` (l.203), tabs Regions/Boundaries/Interfaces/Components (l.289–292).
- Docs: `docs/Physical System Model.md`; `docs/Coupled Solver.md` (symmetry l.127–133, 180–182).
