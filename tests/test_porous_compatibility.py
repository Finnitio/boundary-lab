"""Porous regions combine with the existing air features: symmetry and air-region wall losses."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from blab.headless import load_headless_project, load_headless_solve_spec, prepare_headless_solve
from blab.system_contract import system_solve_request_to_dict

EXAMPLES = Path(__file__).parents[1] / "examples"
GLASS_WOOL_JCA = {
    "model": "jca",
    "frame": "rigid",
    "porosity": 0.94,
    "flow_resistivity_pa_s_per_m2": 40_000.0,
    "tortuosity": 1.06,
    "viscous_characteristic_length_m": 56e-6,
    "thermal_characteristic_length_m": 110e-6,
}


def _example_copy(tmp_path: Path, example: str, edit) -> Path:
    source = next((EXAMPLES / example).glob("*.blab.json"))
    for mesh in (EXAMPLES / example).glob("*.msh"):
        shutil.copy(mesh, tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    edit(payload["physical_system"])
    path = tmp_path / source.name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _request(path: Path) -> dict:
    project = load_headless_project(path)
    prepared = prepare_headless_solve(project, load_headless_solve_spec(None), backend_id="beat_cpu")
    request = system_solve_request_to_dict(prepared.request)
    return json.loads(json.dumps(request).replace(str(path.parent), "<example>"))


def test_a_symmetric_coupled_project_with_a_porous_region_compiles_like_air(tmp_path: Path) -> None:
    def fill(system: dict, loss_model: dict) -> None:
        for region in system["regions"]:
            if region["kind"] == "bounded_air":
                region["loss_model"] = dict(loss_model)

    (tmp_path / "air").mkdir()
    (tmp_path / "porous").mkdir()
    air = _request(_example_copy(tmp_path / "air", "Vented_Sub", lambda system: fill(system, {})))
    porous = _request(_example_copy(tmp_path / "porous", "Vented_Sub", lambda system: fill(system, GLASS_WOOL_JCA)))

    assert porous["solver_options"]["symmetry"] == "xy"
    (porous_region,) = [region for region in porous["compiled_system"]["regions"] if region["kind"] == "bounded_air"]
    assert porous_region["loss_model"] == GLASS_WOOL_JCA
    added = [
        item for item in porous["compiled_system"]["assumptions"] if item not in air["compiled_system"]["assumptions"]
    ]
    assert added == [
        {
            "status": "included",
            "statement": "Region-specific acoustic material loss models: porous equivalent fluid (JCA, rigid frame)",
        }
    ]
    for request in (air, porous):
        request["compiled_system"].pop("assumptions")
        for region in request["compiled_system"]["regions"]:
            region.pop("loss_model")
    assert porous == air


@pytest.mark.parametrize("porous_region", ["region:front", "region:rear"])
def test_thermoviscous_losses_on_air_walls_are_accepted_next_to_a_porous_region(
    tmp_path: Path, porous_region: str
) -> None:
    air_region = "region:rear" if porous_region == "region:front" else "region:front"

    def edit(system: dict) -> None:
        for region in system["regions"]:
            if region["id"] == porous_region:
                region["loss_model"] = dict(GLASS_WOOL_JCA)
        for boundary in system["boundaries"]:
            if boundary["region_id"] == porous_region and boundary["kind"] == "plane_wave_tube_termination":
                boundary["kind"] = "rigid"  # porous regions take no termination
            if boundary["region_id"] == air_region and boundary["id"].endswith("-wall"):
                boundary["parameters"] = {"thermoviscous_wall_losses": "thin_boundary_layer"}

    request = _request(_example_copy(tmp_path, "compression_driver", edit))

    boundaries = {boundary["id"]: boundary for boundary in request["compiled_system"]["boundaries"]}
    wall = boundaries[f"boundary:{air_region.removeprefix('region:')}-wall"]
    assert wall["parameters"]["thermoviscous_wall_losses"] == "thin_boundary_layer"
    regions = {region["id"]: region for region in request["compiled_system"]["regions"]}
    assert regions[porous_region]["loss_model"]["model"] == "jca"


@pytest.mark.slow
def test_a_symmetric_coupled_porous_project_solves(tmp_path: Path, capsys) -> None:
    from blab.project_cli import main as project_main

    def fill(system: dict) -> None:
        for region in system["regions"]:
            if region["kind"] == "bounded_air":
                region["loss_model"] = dict(GLASS_WOOL_JCA)

    project = _example_copy(tmp_path, "Vented_Sub", fill)
    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "frequencies_hz": [60.0],
                "include_project_observations": False,
                "probes": [{"id": "front", "coordinate_frame": "project", "points_m": [[0.0, 0.0, 2.0]]}],
            }
        ),
        encoding="utf-8",
    )
    run = tmp_path / "run"
    project_main(
        ["solve", str(project), "--backend", "beat_cpu", "--request", str(overlay), "--output", str(run)]
        + ["--julia-threads", "2"],
        prog="blab project",
    )
    capsys.readouterr()

    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and all(manifest["completion_mask"])
    (entry,) = manifest["results"]
    metadata = json.loads((run / entry["metadata_file"]).read_text(encoding="utf-8"))
    assert metadata["diagnostics"]["symmetry"] == "xy"
    (material,) = metadata["diagnostics"]["fem_region_materials"]
    assert material["region_id"] == "region:interior-air-1"
    arrays = np.load(run / entry["arrays_file"])
    (probe,) = (item for item in metadata["quantities"] if item["quantity"] == "exterior_pressure")
    assert np.all(np.isfinite(arrays[probe["key"]])) and np.any(arrays[probe["key"]] != 0)
