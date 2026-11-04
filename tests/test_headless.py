import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from beat_engine import beat_contract

import blab.headless as headless_module
from blab.headless import (
    HeadlessProject,
    HeadlessResultWriter,
    HeadlessSolveSpec,
    load_headless_solve_spec,
    prepare_headless_solve,
    resolve_headless_backend,
)
from blab.physical_model import (
    ExcitationPort,
    ExcitationPortKind,
    PhysicalSolveKind,
    PhysicalSystem,
)
from blab.project.model import ProjectPreferencesState
from blab.project_cli import _build_arg_parser
from blab.project_cli import main as project_main
from blab.solve_results import ResultDomain
from blab.solvers.coupled_backend import PhysicalSystemProductionBackend, validate_solve_plan
from blab.system_contract import OutputRequest, QuantityResult, SystemFrequencyResult, SystemSolveRequest
from blab.system_solve import PreparedSystemSolve, canonicalize_observation_result


def test_headless_request_parses_explicit_frequencies_and_probes(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "frequencies_hz": [40, 50, 63],
                "include_project_observations": False,
                "excitation_port_ids": ["excitation:woofer"],
                "probes": [
                    {
                        "id": "farfield",
                        "coordinate_frame": "project",
                        "points_m": [[0, 0, 3], [1, 0, 3]],
                    }
                ],
                "retain": ["bem_boundary_traces"],
                "solver_options": {"validation_diagnostics": True},
            }
        ),
        encoding="utf-8",
    )

    spec = load_headless_solve_spec(request_path)

    assert spec.frequencies_hz == (40.0, 50.0, 63.0)
    assert spec.excitation_port_ids == ("excitation:woofer",)
    assert spec.probes[0].points_m.shape == (2, 3)
    assert spec.retain == ("bem_boundary_traces",)
    assert spec.include_project_observations is False


def test_headless_request_rejects_duplicate_frequencies(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps({"schema_version": 1, "frequencies_hz": [100, 100]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unique"):
        load_headless_solve_spec(request_path)


def test_canonical_observation_result_preserves_complex_excitation_basis() -> None:
    prepared = _prepared_request()
    raw = SystemFrequencyResult(
        freq_hz=100.0,
        excitation_port_ids=("excitation:source",),
        quantities=(
            QuantityResult(
                id="ui:exterior-pressure",
                quantity="exterior_pressure",
                unit="Pa",
                values=np.asarray([[1 + 2j, 3 + 4j]], dtype=np.complex64),
                axes=("excitation", "observation"),
            ),
        ),
    )

    canonical = canonicalize_observation_result(prepared, raw)

    assert canonical.quantities[0].id == "acoustic:pressure:probe:test"
    np.testing.assert_array_equal(
        canonical.quantities[0].values,
        np.asarray([[1 + 2j, 3 + 4j]], dtype=np.complex64),
    )


def test_result_writer_persists_partial_complex_frequency_result(tmp_path: Path) -> None:
    project_file = tmp_path / "sample.blab.json"
    project_file.write_text('{"schema_version": 8}', encoding="utf-8")
    project = HeadlessProject(
        path=project_file,
        payload={"schema_version": 8},
        physical_system=PhysicalSystem("system:test", "Test", (), (), ()),
        preferences=ProjectPreferencesState(),
        symmetry="off",
        component_channel_by_id={},
    )
    prepared = _prepared_request()
    writer = HeadlessResultWriter(
        tmp_path / "run",
        project=project,
        prepared=prepared,
        backend_id="beat_cpu",
        public_request={"schema_version": 1},
    )
    result = canonicalize_observation_result(
        prepared,
        SystemFrequencyResult(
            freq_hz=100.0,
            excitation_port_ids=("excitation:source",),
            quantities=(
                QuantityResult(
                    id="ui:exterior-pressure",
                    quantity="exterior_pressure",
                    unit="Pa",
                    values=np.asarray([[1 + 2j, 3 + 4j]], dtype=np.complex64),
                    axes=("excitation", "observation"),
                ),
            ),
            diagnostics={"relative_residual": 1e-5, "engine_provenance": {"engine": {"source_sha256": "test-digest"}}},
        ),
    )

    writer.write_result(result)
    writer.finish(status="complete")

    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    metadata = json.loads((tmp_path / "run" / "frequencies" / "000000.json").read_text(encoding="utf-8"))
    arrays = np.load(tmp_path / "run" / "frequencies" / "000000.npz")
    assert manifest["status"] == "complete"
    assert manifest["schema_version"] == 2
    assert len(manifest["meshes"]) == 1
    assert manifest["meshes"][0]["id"] == "mesh:exterior"
    assert manifest["completion_mask"] == [True]
    assert manifest["engine_runs"] == [metadata["diagnostics"]["engine_provenance"]]
    assert metadata["quantities"][0]["id"] == "acoustic:pressure:probe:test"
    assert arrays["q0000"].dtype == np.complex64
    np.testing.assert_array_equal(arrays["q0000"], np.asarray([[1 + 2j, 3 + 4j]], dtype=np.complex64))


def test_headless_events_carry_elapsed_eta_and_warm_up_prediction(tmp_path: Path) -> None:
    from blab.warm_up_history import WarmUpHistory, WarmUpKey

    key = WarmUpKey("cpu", "0.4.0", "8", True)
    WarmUpHistory().record(key, 90.0)
    frequencies = (100.0, 200.0, 300.0, 400.0, 500.0)
    prepared = _prepared_request()
    prepared = replace(prepared, request=replace(prepared.request, frequencies_hz=frequencies))

    class Session:
        def __init__(self, request):
            self.request = request

        def warm_up_key(self):
            return key

        def solve_stream(self):
            self.request.status_callback("Preparing BEAT CPU geometry caches")
            for freq_hz in frequencies[:4]:
                yield _raw_exterior_result(freq_hz)

        def stop(self):
            pass

    backend = SimpleNamespace(create_system_session=Session)
    events = []
    with pytest.raises(RuntimeError, match="all requested frequencies"):
        headless_module.run_headless_solve(
            _headless_project(tmp_path),
            prepared,
            output_dir=tmp_path / "run",
            backend_id="beat_cpu",
            public_request={"schema_version": 1},
            event_callback=events.append,
            backend=backend,
        )

    (status,) = [event for event in events if event["event"] == "status"]
    assert status["predicted_warm_up_s"] == 90.0
    assert status["elapsed_s"] >= 0.0
    completed = [event for event in events if event["event"] == "frequency_completed"]
    assert [event["eta_s"] is None for event in completed] == [True, True, True, False]
    assert completed[-1]["eta_s"] >= 0.0
    assert all(event["elapsed_s"] >= 0.0 for event in completed)
    assert len(WarmUpHistory().durations_s(key)) == 2


def test_text_events_use_the_status_bar_format() -> None:
    from blab.project_cli import format_solve_event

    assert (
        format_solve_event(
            {"event": "frequency_completed", "solved_count": 4, "frequency_count": 10, "elapsed_s": 46.0, "eta_s": 18.0}
        )
        == "Solving 4/10 · 0:46 elapsed · ~0:20 left"
    )
    assert (
        format_solve_event({"event": "status", "message": "Preparing", "elapsed_s": 42.0, "predicted_warm_up_s": 90.0})
        == "Preparing · 0:42 / ~2:00"
    )
    assert format_solve_event({"event": "failed", "message": "Backend failed"}) == "Backend failed"
    assert format_solve_event({"event": "started"}) is None


def _headless_project(tmp_path: Path) -> HeadlessProject:
    project_file = tmp_path / "sample.blab.json"
    project_file.write_text('{"schema_version": 8}', encoding="utf-8")
    return HeadlessProject(
        path=project_file,
        payload={"schema_version": 8},
        physical_system=PhysicalSystem("system:test", "Test", (), (), ()),
        preferences=ProjectPreferencesState(),
        symmetry="off",
        component_channel_by_id={},
    )


def _raw_exterior_result(freq_hz: float) -> SystemFrequencyResult:
    return SystemFrequencyResult(
        freq_hz=freq_hz,
        excitation_port_ids=("excitation:source",),
        quantities=(
            QuantityResult(
                id="ui:exterior-pressure",
                quantity="exterior_pressure",
                unit="Pa",
                values=np.asarray([[1 + 2j, 3 + 4j]], dtype=np.complex64),
                axes=("excitation", "observation"),
            ),
        ),
    )


def test_project_cli_exposes_validate_and_solve_commands() -> None:
    parser = _build_arg_parser("blab project")

    validate = parser.parse_args(["validate", "speaker.blab.json", "--json"])
    solve = parser.parse_args(["solve", "speaker.blab.json", "--events", "ndjson"])
    export = parser.parse_args(
        [
            "export-speaker",
            "speaker.blab.json",
            "--output",
            "speaker.blabsp",
            "--fidelity",
            "coupled",
        ]
    )
    speaker_preflight = parser.parse_args(["speaker-preflight", "speaker.blab.json", "--rom-rank", "128"])
    evaluate_fem = parser.parse_args(["evaluate-fem", "runs/case"])
    compare_fem = parser.parse_args(["compare-fem", "coarse.json", "fine.json"])

    assert validate.project_command == "validate"
    assert validate.json is True
    assert validate.backend == "beat_auto"
    assert solve.project_command == "solve"
    assert solve.events == "ndjson"
    assert export.project_command == "export-speaker"
    assert export.output == Path("speaker.blabsp")
    assert export.fidelity == "coupled"
    assert not hasattr(export, "coupled_representation")
    assert speaker_preflight.project_command == "speaker-preflight"
    assert speaker_preflight.rom_rank == 128
    assert evaluate_fem.project_command == "evaluate-fem"
    assert evaluate_fem.run_dir == Path("runs/case")
    assert evaluate_fem.min_points_per_wavelength_p95 == 8.0
    assert evaluate_fem.min_points_per_wavelength_maximum_edge == 4.0
    assert evaluate_fem.split_surface_entities is False
    assert compare_fem.project_command == "compare-fem"
    assert compare_fem.coarse_report == Path("coarse.json")


def test_auto_backend_prefers_functional_cuda(monkeypatch) -> None:
    monkeypatch.setattr(headless_module, "_command_available", lambda _command: True)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(headless_module.subprocess, "run", fake_run)

    assert resolve_headless_backend("beat_auto", julia_executable="custom-julia") == "beat_cuda"
    assert calls[0][0][0] == "custom-julia"
    assert "CUDA.functional()" in calls[0][0][-1]


def test_auto_backend_falls_back_to_cpu_when_cuda_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(headless_module, "_command_available", lambda _command: True)
    monkeypatch.setattr(
        headless_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )

    assert resolve_headless_backend() == "beat_cpu"


def test_explicit_backend_does_not_probe_cuda(monkeypatch) -> None:
    monkeypatch.setattr(
        headless_module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("explicit backend should not probe CUDA"),
    )

    assert resolve_headless_backend("beat_cpu") == "beat_cpu"
    assert resolve_headless_backend("beat_cuda") == "beat_cuda"
    assert resolve_headless_backend("beat_rocm") == "beat_rocm"
    assert resolve_headless_backend("beat_cpu_condensed") == "beat_cpu"


def test_solve_plan_validation_checks_protocol_before_backend_capabilities() -> None:
    request = replace(_prepared_request().request, frequencies_hz=())

    with pytest.raises(ValueError, match="at least one frequency"):
        validate_solve_plan(request)


def test_headless_full_matrix_diagnostics_disable_default_condensation(monkeypatch, tmp_path: Path) -> None:
    prepared = _prepared_request()
    request = SystemSolveRequest(
        compiled_system=prepared.request.compiled_system,
        frequencies_hz=prepared.request.frequencies_hz,
        excitation_port_ids=prepared.request.excitation_port_ids,
        outputs=prepared.request.outputs,
        solver_options={"static_condensation": True},
    )
    prepared = PreparedSystemSolve(
        request=request,
        backend_id=prepared.backend_id,
        solve_kind=prepared.solve_kind,
        polar_angle_deg=prepared.polar_angle_deg,
        excitation_channel_names=prepared.excitation_channel_names,
        excitation_component_names=prepared.excitation_component_names,
        horizontal_count=prepared.horizontal_count,
        vertical_count=prepared.vertical_count,
        result_domains=prepared.result_domains,
    )
    monkeypatch.setattr(headless_module, "prepare_system_solve", lambda *_args, **_kwargs: prepared)
    validated = []
    monkeypatch.setattr(headless_module, "validate_solve_plan", lambda request, **_: validated.append(request))
    project_path = tmp_path / "project.blab.json"
    project_path.write_text("{}", encoding="utf-8")
    project = HeadlessProject(
        path=project_path,
        payload={},
        physical_system=PhysicalSystem("system:test", "Test", (), (), ()),
        preferences=ProjectPreferencesState(),
        symmetry="off",
        component_channel_by_id={},
    )

    result = prepare_headless_solve(
        project,
        HeadlessSolveSpec(solver_options={"validation_diagnostics": True}),
        backend_id="beat_cpu",
    )

    assert validated == [result.request]

    assert result.request.solver_options["validation_diagnostics"] is True
    assert result.request.solver_options["static_condensation"] is False


def _prepared_request() -> PreparedSystemSolve:
    port = ExcitationPort(
        id="excitation:source",
        name="Source",
        component_id="component:source",
        kind=ExcitationPortKind.NORMAL_VELOCITY,
    )
    import json

    from blab.system_contract import compiled_system_from_dict

    fixture = Path(beat_contract.__file__).with_name("example-exterior-request.json")
    compiled_payload = json.loads(fixture.read_text())["compiled_system"]
    compiled_payload["meshes"][0]["file"] = str(Path(__file__).parent / "fixtures/exterior.msh")
    compiled = compiled_system_from_dict(compiled_payload)
    request = SystemSolveRequest(
        compiled_system=compiled,
        frequencies_hz=(100.0,),
        excitation_port_ids=(port.id,),
        outputs=(
            # The backend returns one compact array; canonicalization splits it.
            OutputRequest(
                id="ui:exterior-pressure",
                quantity="exterior_pressure",
                options={
                    "points_m": [[0, 0, 1], [0, 0, 2]],
                    "observation_domains": [
                        {
                            "id": "observation:probe:test",
                            "quantity_id": "acoustic:pressure:probe:test",
                            "offset": 0,
                            "count": 2,
                        }
                    ],
                },
            ),
        ),
    )
    return PreparedSystemSolve(
        request=request,
        backend_id="beat_cpu",
        solve_kind=PhysicalSolveKind.EXTERIOR_BEM,
        polar_angle_deg=np.empty(0),
        excitation_channel_names=np.asarray(["main"]),
        excitation_component_names=np.asarray(["Source"]),
        horizontal_count=0,
        vertical_count=0,
        result_domains=(
            ResultDomain(
                id="observation:probe:test",
                kind="point_probe",
                dimensions=("observation",),
                coordinates={"points_m": np.asarray([[0, 0, 1], [0, 0, 2]], dtype=float)},
            ),
        ),
    )


@pytest.mark.parametrize("backend_id", ["beat_cpu", "beat_cuda", "beat_rocm"])
@pytest.mark.parametrize("precision", [None, "float32", "float64"])
def test_headless_precision_reaches_production_session(tmp_path, monkeypatch, backend_id, precision):
    from blab.solvers.coupled_backend import CoupledSession

    project_file = tmp_path / "sample.blab.json"
    project_file.write_text('{"schema_version": 8}', encoding="utf-8")
    project = HeadlessProject(
        path=project_file,
        payload={"schema_version": 8},
        physical_system=PhysicalSystem("system:test", "Test", (), (), ()),
        preferences=ProjectPreferencesState(),
        symmetry="off",
        component_channel_by_id={},
    )
    prepared = _prepared_request()
    options = {} if precision is None else {"precision": precision}
    prepared = replace(prepared, request=replace(prepared.request, solver_options=options))
    captured = []

    def solve_stream(session):
        captured.append(session.request.solver_options["precision"])
        yield SystemFrequencyResult(
            freq_hz=100.0,
            excitation_port_ids=("excitation:source",),
            quantities=(
                QuantityResult(
                    id="ui:exterior-pressure",
                    quantity="exterior_pressure",
                    unit="Pa",
                    values=np.asarray([[1 + 2j, 3 + 4j]], dtype=np.complex128),
                    axes=("excitation", "observation"),
                ),
            ),
        )

    monkeypatch.setattr(CoupledSession, "solve_stream", solve_stream)
    result = headless_module.run_headless_solve(
        project,
        prepared,
        output_dir=tmp_path / "run",
        backend_id=backend_id,
        public_request={"schema_version": 1, "solver_options": options},
    )
    assert result["solved_count"] == 1
    assert captured == [precision or "float32"]


def test_interface_radiation_is_an_explicitly_retainable_project_observation(tmp_path):
    from blab.solve_results.model import INTERFACE_RADIATION_ID, RADIATION_SOURCE_DOMAIN_ID

    path = tmp_path / "radiation.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "include_project_observations": False, "retain": ["interface_radiated_pressure"]}
        )
    )
    assert load_headless_solve_spec(path).retain == ("interface_radiated_pressure",)
    output = OutputRequest(
        id=INTERFACE_RADIATION_ID, quantity="interface_radiated_pressure", options={"points_m": [[0, 0, 3]]}
    )
    domain = ResultDomain(
        id=RADIATION_SOURCE_DOMAIN_ID, kind="radiation_source_collection", dimensions=("radiation_source",)
    )
    outputs, domains = headless_module._without_project_observations([output], [domain])
    assert outputs == [] and domains == []
    prepared = _prepared_request()
    with pytest.raises(ValueError, match="FEM-BEM interfaces"):
        validate_solve_plan(replace(prepared.request, outputs=(output,)))


FILLED_TUBE = Path(__file__).parents[1] / "examples" / "filled_tube" / "filled_tube.blab.json"
FILLED_TUBE_MATERIAL = {
    "model": "jca",
    "frame": "rigid",
    "porosity": 0.98,
    "flow_resistivity_pa_s_per_m2": 25_000.0,
    "tortuosity": 1.02,
    "viscous_characteristic_length_m": 90e-6,
    "thermal_characteristic_length_m": 180e-6,
}


def test_validation_and_run_provenance_record_each_region_material(tmp_path: Path) -> None:
    project = headless_module.load_headless_project(FILLED_TUBE)
    prepared = prepare_headless_solve(project, load_headless_solve_spec(None), backend_id="beat_cpu")
    expected = [
        {"region_id": "region:fill", "name": "Porous fill", "kind": "bounded_air", "material": FILLED_TUBE_MATERIAL}
    ]

    summary = headless_module.validation_summary(project, prepared, backend_id="beat_cpu")
    HeadlessResultWriter(
        tmp_path / "run", project=project, prepared=prepared, backend_id="beat_cpu", public_request={}
    ).finish(status="complete")
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))

    assert summary["region_materials"] == expected
    assert manifest["region_materials"] == expected


def test_validate_json_reports_material_warnings_per_region(tmp_path: Path, capsys) -> None:
    project = json.loads(FILLED_TUBE.read_text(encoding="utf-8"))
    project["physical_system"]["regions"][0]["loss_model"]["thermal_characteristic_length_m"] = 60e-6
    shutil.copy(FILLED_TUBE.with_suffix("").with_suffix(".msh"), tmp_path)
    path = tmp_path / FILLED_TUBE.name
    path.write_text(json.dumps(project), encoding="utf-8")

    capsys.readouterr()
    project_main(["validate", str(path), "--backend", "beat_cpu", "--json"], prog="blab project")
    summary = json.loads(capsys.readouterr().out)

    assert summary["valid"]
    assert [(item["code"], item["region_id"]) for item in summary["warnings"]] == [
        ("porous_thermal_length_below_viscous_length", "region:fill")
    ]


def test_run_manifest_records_the_validation_warnings_the_run_was_made_despite(tmp_path: Path) -> None:
    payload = json.loads(FILLED_TUBE.read_text(encoding="utf-8"))
    payload["physical_system"]["regions"][0]["loss_model"]["thermal_characteristic_length_m"] = 60e-6
    shutil.copy(FILLED_TUBE.with_suffix("").with_suffix(".msh"), tmp_path)
    path = tmp_path / FILLED_TUBE.name
    path.write_text(json.dumps(payload), encoding="utf-8")
    project = headless_module.load_headless_project(path)
    prepared = prepare_headless_solve(project, load_headless_solve_spec(None), backend_id="beat_cpu")

    HeadlessResultWriter(
        tmp_path / "run", project=project, prepared=prepared, backend_id="beat_cpu", public_request={}
    ).finish(status="complete")
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))

    (warning,) = manifest["warnings"]
    assert (warning["code"], warning["region_id"]) == ("porous_thermal_length_below_viscous_length", "region:fill")
    assert "thermal characteristic length (60 um)" in warning["message"]


def test_plain_text_validate_prints_each_warning(tmp_path: Path, capsys) -> None:
    payload = json.loads(FILLED_TUBE.read_text(encoding="utf-8"))
    payload["physical_system"]["regions"][0]["loss_model"]["thermal_characteristic_length_m"] = 60e-6
    shutil.copy(FILLED_TUBE.with_suffix("").with_suffix(".msh"), tmp_path)
    path = tmp_path / FILLED_TUBE.name
    path.write_text(json.dumps(payload), encoding="utf-8")

    capsys.readouterr()
    project_main(["validate", str(path), "--backend", "beat_cpu"], prog="blab project")
    lines = capsys.readouterr().out.splitlines()

    assert any(line.startswith("Valid ") for line in lines)
    (warning,) = [line for line in lines if line.startswith("warning:")]
    assert "porous_thermal_length_below_viscous_length" in warning and "Region 'region:fill'" in warning


def test_validate_json_lists_no_warnings_for_a_regular_material(capsys) -> None:
    capsys.readouterr()
    project_main(["validate", str(FILLED_TUBE), "--backend", "beat_cpu", "--json"], prog="blab project")

    assert json.loads(capsys.readouterr().out)["warnings"] == []


SIMPLE_SEALED = Path(__file__).parents[1] / "examples" / "Simple_Sealed"


def _porous_simple_sealed(tmp_path: Path) -> Path:
    """Copy the coupled Simple_Sealed example with its bounded region filled with a JCA material."""

    for name in ("simple_sealed.blab.json", "Exterior.msh", "interior.msh"):
        (tmp_path / name).write_bytes((SIMPLE_SEALED / name).read_bytes())
    path = tmp_path / "simple_sealed.blab.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for region in payload["physical_system"]["regions"]:
        if region["kind"] == "bounded_air":
            region["loss_model"] = dict(FILLED_TUBE_MATERIAL)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("backend", ["rocm", "metal"])
def test_solve_plan_rejects_coupled_porous_regions_on_backends_without_region_materials(
    tmp_path: Path, backend: str
) -> None:
    project = headless_module.load_headless_project(_porous_simple_sealed(tmp_path))
    prepared = prepare_headless_solve(project, load_headless_solve_spec(None), backend_id="beat_cpu")

    with pytest.raises(
        ValueError, match=rf"not supported on the {backend} backend.*region:interior-air-1.*cpu or cuda"
    ):
        validate_solve_plan(prepared.request, bem_backend=backend)


@pytest.mark.parametrize("backend", ["cpu", "cuda"])
def test_solve_plan_accepts_coupled_porous_regions_on_cpu_and_cuda(tmp_path: Path, backend: str) -> None:
    project = headless_module.load_headless_project(_porous_simple_sealed(tmp_path))
    prepared = prepare_headless_solve(project, load_headless_solve_spec(None), backend_id="beat_cpu")

    validate_solve_plan(prepared.request, bem_backend=backend)


def test_project_validate_reports_porous_rejection_for_the_requested_backend(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    from blab.project_cli import main as project_main

    monkeypatch.setattr(headless_module, "packaged_backend_available", lambda _backend_id: True)
    path = _porous_simple_sealed(tmp_path)

    with pytest.raises(SystemExit):
        project_main(["validate", str(path), "--backend", "beat_metal", "--json"], prog="blab project")
    error = json.loads(capsys.readouterr().out)

    assert error["event"] == "error"
    assert "not supported on the metal backend" in error["message"]
    project_main(["validate", str(path), "--backend", "beat_cuda", "--json"], prog="blab project")
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_production_session_rejects_coupled_porous_regions_on_rocm_before_starting_a_worker(tmp_path: Path) -> None:
    project = headless_module.load_headless_project(_porous_simple_sealed(tmp_path))
    prepared = prepare_headless_solve(project, load_headless_solve_spec(None), backend_id="beat_cpu")
    backend = PhysicalSystemProductionBackend(bem_backend="rocm", julia_executable="julia-not-started")

    with pytest.raises(ValueError, match="not supported on the rocm backend"):
        backend.create_system_session(prepared.request)


def test_solve_plan_accepts_interior_porous_regions_on_any_backend() -> None:
    project = headless_module.load_headless_project(FILLED_TUBE)

    for backend_id in ("beat_rocm", "beat_metal"):
        prepare_headless_solve(project, load_headless_solve_spec(None), backend_id=backend_id)


RADIATING_FILLED_TUBE = (
    Path(__file__).parents[1] / "examples" / "radiating_filled_tube" / "radiating_filled_tube.blab.json"
)


def _coupled_request_with_seam(*, loss_factors: tuple[float, float]):
    """The radiating tube's coupled request, its bounded region split into two Air regions joined by a seam."""

    from blab.physical_model import RegionSeam

    project = headless_module.load_headless_project(RADIATING_FILLED_TUBE)
    request = prepare_headless_solve(project, load_headless_solve_spec(None), backend_id="beat_cpu").request
    exterior, bounded = request.compiled_system.regions
    regions = (
        exterior,
        replace(bounded, id="region:front", loss_model={"bulk_loss_factor": loss_factors[0]}),
        replace(bounded, id="region:back", loss_model={"bulk_loss_factor": loss_factors[1]}),
    )
    seam = RegionSeam(region_ids=("region:front", "region:back"), mesh_id="mesh:tube", face_count=8)
    return replace(request, compiled_system=replace(request.compiled_system, regions=regions, region_seams=(seam,)))


@pytest.mark.parametrize("backend", ["rocm", "metal"])
def test_coupled_seam_between_different_bulk_losses_is_rejected_on_per_node_backends(backend: str) -> None:
    from blab.solvers.coupled_backend import validate_backend_capabilities

    request = _coupled_request_with_seam(loss_factors=(0.01, 0.0))

    with pytest.raises(
        ValueError, match=rf"{backend} backend.*equal bulk loss.*'region:front' and 'region:back'.*cpu or cuda"
    ):
        validate_backend_capabilities(request, backend)


@pytest.mark.parametrize(
    ("backend", "loss_factors"), [("cpu", (0.01, 0.0)), ("cuda", (0.01, 0.0)), ("rocm", (0.01, 0.01))]
)
def test_coupled_seam_is_accepted_with_per_region_operators_or_equal_bulk_loss(
    backend: str, loss_factors: tuple[float, float]
) -> None:
    from blab.solvers.coupled_backend import validate_backend_capabilities

    validate_backend_capabilities(_coupled_request_with_seam(loss_factors=loss_factors), backend)
