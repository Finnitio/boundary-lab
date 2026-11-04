"""Headless porous-material example projects solved through the CLI against analytical references."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import meshio
import numpy as np
import pytest

from blab.project_cli import main as project_main
from porous_reference import closed_tube_input_impedance, equivalent_fluid, loaded_section

EXAMPLES = Path(__file__).parents[1] / "examples"
FILLED_TUBE = EXAMPLES / "filled_tube" / "filled_tube.blab.json"
FILLED_TUBE_LENGTH_M = 0.1
RADIATING_TUBE = EXAMPLES / "radiating_filled_tube" / "radiating_filled_tube.blab.json"
RADIATING_TUBE_LENGTH_M = 0.05
# The unit normal-velocity port moves the piston along its outward normal (-z), out of the
# tube, so the velocity into the tube is -1 m/s. The interface velocity is outward of the
# bounded region (+z).
INLET_VELOCITY = -1.0
FAR_POINT_M = [0.01, 0.01, 0.55]


def _cli_json(capsys, *argv: str) -> dict:
    capsys.readouterr()
    project_main(list(argv), prog="blab project")
    return json.loads(capsys.readouterr().out)


@pytest.mark.slow
def test_filled_tube_input_impedance_matches_closed_tube_reference(tmp_path: Path, capsys) -> None:
    summary = _cli_json(capsys, "validate", str(FILLED_TUBE), "--backend", "beat_cpu", "--json")
    assert summary["valid"] and summary["solve_kind"] == "interior_fem"
    assert {
        "status": "included",
        "statement": "Region-specific acoustic material loss models: porous equivalent fluid (JCA, rigid frame)",
    } in summary["assumptions"]

    run = tmp_path / "run"
    capsys.readouterr()
    project_main(
        ["solve", str(FILLED_TUBE), "--backend", "beat_cpu", "--output", str(run), "--julia-threads", "2"],
        prog="blab project",
    )

    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and all(manifest["completion_mask"])
    assert manifest["phasor_convention"] == "exp(+i omega t)"
    (region,) = json.loads(FILLED_TUBE.read_text(encoding="utf-8"))["physical_system"]["regions"]
    material = manifest["region_materials"][0]["material"]
    points = np.load(run / "domains.npz")[_domain_array(run, "domain:fem-volume", "points_m")]
    piston = np.isclose(points[:, 2], 0.0)
    errors = []
    for entry in manifest["results"]:
        metadata = json.loads((run / entry["metadata_file"]).read_text(encoding="utf-8"))
        (quantity,) = (item for item in metadata["quantities"] if item["quantity"] == "fem_nodal_pressure")
        pressure = np.load(run / entry["arrays_file"])[quantity["key"]][0]
        # The unit normal-velocity port moves the piston along its outward normal, out of the
        # tube, so the velocity into the fill is -1 m/s.
        impedance = -pressure[piston].mean()
        fluid = equivalent_fluid(
            material,
            entry["freq_hz"],
            density_kg_per_m3=region["density_kg_per_m3"],
            sound_speed_m_per_s=region["sound_speed_m_per_s"],
        )
        expected = closed_tube_input_impedance(fluid, entry["freq_hz"], FILLED_TUBE_LENGTH_M)
        errors.append(abs(impedance - expected) / abs(expected))

    # Stated tolerance: 1e-4 relative input-impedance error from 100 Hz to 2 kHz on the
    # example's 1.25 mm P1 slabs (about 80 elements per porous wavelength at 2 kHz; measured 2.1e-5).
    assert len(errors) == 20
    assert max(errors) < 1e-4, errors


def _domain_array(run: Path, domain_id: str, coordinate: str) -> str:
    domains = json.loads((run / "domains.json").read_text(encoding="utf-8"))["domains"]
    return next(domain for domain in domains if domain["id"] == domain_id)["coordinates"][coordinate]


@pytest.mark.slow
def test_radiating_filled_tube_matches_transfer_matrix_with_air_radiation_load(tmp_path: Path, capsys) -> None:
    """Porous fill at an FEM-BEM interface against an independent reference.

    The JCA transfer matrix of the filled section, loaded by the radiation impedance of the same
    opening taken from an air-only coupled solve of the same meshes, predicts the porous solve's
    input impedance and opening velocity.
    """

    summary = _cli_json(capsys, "validate", str(RADIATING_TUBE), "--backend", "beat_cpu", "--json")
    assert summary["valid"] and summary["solve_kind"] == "coupled_bem_fem"
    porous = _solve_radiating_tube(RADIATING_TUBE, tmp_path / "porous", capsys)
    air = _solve_radiating_tube(_air_filled_copy(tmp_path / "air"), tmp_path / "air-run", capsys)

    project = json.loads(RADIATING_TUBE.read_text(encoding="utf-8"))
    fill = next(region for region in project["physical_system"]["regions"] if region["id"] == "region:fill")
    assert porous["region_materials"]["region:fill"] == fill["loss_model"]
    assert air["region_materials"]["region:fill"]["model"] == "air"
    assert porous["frequencies"] == air["frequencies"] == [200.0, 700.0, 1500.0]
    for index, frequency in enumerate(porous["frequencies"]):
        # Radiation load p/v of the opening, from the air-only solve.
        load = air["opening_pressure"][index] / air["opening_velocity"][index]
        fluid = equivalent_fluid(
            fill["loss_model"],
            frequency,
            density_kg_per_m3=fill["density_kg_per_m3"],
            sound_speed_m_per_s=fill["sound_speed_m_per_s"],
        )
        expected = loaded_section(fluid, frequency, RADIATING_TUBE_LENGTH_M, load)
        impedance = porous["inlet_pressure"][index] / INLET_VELOCITY
        velocity_ratio = porous["opening_velocity"][index] / INLET_VELOCITY
        impedance_error = abs(impedance - expected.input_impedance) / abs(expected.input_impedance)
        velocity_error = abs(velocity_ratio - expected.velocity_ratio) / abs(expected.velocity_ratio)
        far_ratio = porous["far_pressure"][index] / air["far_pressure"][index]
        velocity_change = porous["opening_velocity"][index] / air["opening_velocity"][index]
        far_error = abs(far_ratio - velocity_change) / abs(velocity_change)
        # Stated tolerance (as in BEAT Engine porous_coupled_tests.jl on the same meshes): 0.5 % on the
        # input impedance, 1.5 % on the opening velocity and 2 % on the exterior pressure, which the
        # opening's velocity radiates in both solves (measured at most 0.25 %, 0.85 % and 1.1 %, at 1.5 kHz).
        # The residual is the plane-wave model of the
        # opening (the near field differs between air and porous fill), not discretization.
        assert impedance_error < 5e-3, (frequency, impedance_error)
        assert velocity_error < 1.5e-2, (frequency, velocity_error)
        assert far_error < 2e-2, (frequency, far_error)
        # The reference resolves the radiation load: an ideal open end moves the opening velocity
        # by much more than the observed disagreement.
        open_end = loaded_section(fluid, frequency, RADIATING_TUBE_LENGTH_M, 0.0)
        assert (
            abs(open_end.velocity_ratio - expected.velocity_ratio) / abs(expected.velocity_ratio) > 5 * velocity_error
        )


def _air_filled_copy(directory: Path) -> Path:
    shutil.copytree(RADIATING_TUBE.parent, directory)
    path = directory / RADIATING_TUBE.name
    project = json.loads(path.read_text(encoding="utf-8"))
    for region in project["physical_system"]["regions"]:
        region["loss_model"] = {}
    path.write_text(json.dumps(project), encoding="utf-8")
    return path


def _solve_radiating_tube(project: Path, run: Path, capsys) -> dict:
    overlay = run.with_suffix(".request.json")
    overlay.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "frequencies_hz": [200.0, 700.0, 1500.0],
                "include_project_observations": False,
                "probes": [{"id": "far", "coordinate_frame": "project", "points_m": [FAR_POINT_M]}],
                "retain": ["fem_nodal_pressure"],
                "solver_options": {"precision": "float64"},
            }
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    project_main(
        ["solve", str(project), "--backend", "beat_cpu", "--request", str(overlay), "--output", str(run)]
        + ["--julia-threads", "2"],
        prog="blab project",
    )
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and all(manifest["completion_mask"])
    assert manifest["phasor_convention"] == "exp(+i omega t)"

    points = np.load(run / "domains.npz")[_domain_array(run, "domain:fem-volume", "points_m")]
    piston, opening = _end_weights(project.parent / "tube.msh", points)
    observed = {"frequencies": [], "inlet_pressure": [], "opening_pressure": [], "opening_velocity": []}
    observed["far_pressure"] = []
    for entry in manifest["results"]:
        metadata = json.loads((run / entry["metadata_file"]).read_text(encoding="utf-8"))
        arrays = np.load(run / entry["arrays_file"])

        def values(quantity: str) -> np.ndarray:
            (item,) = (item for item in metadata["quantities"] if item["quantity"] == quantity)
            return arrays[item["key"]][0]

        pressure = values("fem_nodal_pressure")
        observed["frequencies"].append(entry["freq_hz"])
        observed["inlet_pressure"].append(piston @ pressure)
        observed["opening_pressure"].append(opening @ pressure)
        (velocity,) = values("interface_average_normal_velocity")
        observed["opening_velocity"].append(velocity)
        (far,) = values("exterior_pressure")
        observed["far_pressure"].append(far)
    observed["region_materials"] = {item["region_id"]: item["material"] for item in manifest["region_materials"]}
    return observed


def _end_weights(mesh_path: Path, points_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """P1 area-average weights of the piston and opening faces on the result's FEM nodes."""

    mesh = meshio.read(mesh_path)
    triangles = mesh.cells_dict["triangle"]
    tags = mesh.cell_data_dict["gmsh:physical"]["triangle"]
    node_of = {tuple(np.round(point, 9)): index for index, point in enumerate(points_m)}
    nodes = np.array([node_of[tuple(np.round(point * 1e-3, 9))] for point in mesh.points])
    weights = []
    for name in ("Piston", "Opening"):
        tag = mesh.field_data[name][0]
        weight = np.zeros(len(points_m))
        for triangle in triangles[tags == tag]:
            a, b, c = mesh.points[triangle]
            weight[nodes[triangle]] += np.linalg.norm(np.cross(b - a, c - a)) / 6.0
        weights.append(weight / weight.sum())
    return weights[0], weights[1]
