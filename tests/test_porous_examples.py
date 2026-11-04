"""Headless porous-material example projects solved through the CLI against analytical references."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from blab.project_cli import main as project_main
from porous_reference import air, closed_tube_input_impedance, driven_layer_pressure, equivalent_fluid

EXAMPLES = Path(__file__).parents[1] / "examples"
FILLED_TUBE = EXAMPLES / "filled_tube" / "filled_tube.blab.json"
FILLED_TUBE_LENGTH_M = 0.1


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


POROUS_LAYER_TUBE = EXAMPLES / "porous_layer_tube" / "porous_layer_tube.blab.json"
AIR_LENGTH_M = 0.05
LAYER_LENGTH_M = 0.05


@pytest.mark.slow
def test_porous_layer_tube_matches_transfer_matrix_through_the_region_seam(tmp_path: Path, capsys) -> None:
    summary = _cli_json(capsys, "validate", str(POROUS_LAYER_TUBE), "--backend", "beat_cpu", "--json")
    assert summary["valid"] and summary["solve_kind"] == "interior_fem"
    assert summary["region_seams"] == [
        {"region_ids": ["region:air", "region:layer"], "mesh_id": "mesh:tube", "face_count": 8}
    ]

    run = tmp_path / "run"
    capsys.readouterr()
    project_main(
        ["solve", str(POROUS_LAYER_TUBE), "--backend", "beat_cpu", "--output", str(run), "--julia-threads", "2"],
        prog="blab project",
    )

    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and all(manifest["completion_mask"])
    assert manifest["phasor_convention"] == "exp(+i omega t)"
    regions = {
        region["id"]: region
        for region in json.loads(POROUS_LAYER_TUBE.read_text(encoding="utf-8"))["physical_system"]["regions"]
    }
    materials = {entry["region_id"]: entry["material"] for entry in manifest["region_materials"]}
    air_region = regions["region:air"]
    rho0, c0 = air_region["density_kg_per_m3"], air_region["sound_speed_m_per_s"]
    air_fluid = air(density_kg_per_m3=rho0, sound_speed_m_per_s=c0)
    air_z = _region_node_coordinates(run, "region:air")[:, 2]

    impedance_errors, pressure_errors = [], []
    for entry in manifest["results"]:
        frequency = entry["freq_hz"]
        metadata = json.loads((run / entry["metadata_file"]).read_text(encoding="utf-8"))
        (quantity,) = (item for item in metadata["quantities"] if item["quantity"] == "fem_nodal_pressure")
        pressure = np.load(run / entry["arrays_file"])[quantity["key"]][0][_region_node_slice(run, "region:air")]

        layer = equivalent_fluid(materials["region:layer"], frequency, density_kg_per_m3=rho0, sound_speed_m_per_s=c0)
        surface_impedance = closed_tube_input_impedance(layer, frequency, LAYER_LENGTH_M)
        # Surface impedance from the air field, as in an impedance tube: fit the two plane
        # waves p = A e^{-jkz} + B e^{+jkz} to every air node, then evaluate p / v at the seam.
        k0 = air_fluid.wavenumber(frequency)
        waves = np.stack([np.exp(-1j * k0 * air_z), np.exp(1j * k0 * air_z)], axis=1)
        (forward, backward), *_ = np.linalg.lstsq(waves, pressure, rcond=None)
        at_seam = forward * np.exp(-1j * k0 * AIR_LENGTH_M), backward * np.exp(1j * k0 * AIR_LENGTH_M)
        measured = (at_seam[0] + at_seam[1]) / ((at_seam[0] - at_seam[1]) / air_fluid.characteristic_impedance)
        impedance_errors.append(abs(measured - surface_impedance) / abs(surface_impedance))

        # The unit normal-velocity port moves the piston along its outward normal, out of the
        # tube, so the velocity into the air is -1 m/s.
        expected = np.array(
            [
                driven_layer_pressure(
                    air_fluid,
                    frequency,
                    layer_length_m=AIR_LENGTH_M,
                    position_m=z,
                    termination_impedance=surface_impedance,
                    input_velocity=-1.0,
                )
                for z in air_z
            ]
        )
        pressure_errors.append(np.max(np.abs(pressure - expected)) / np.max(np.abs(expected)))

    assert len(impedance_errors) == 20
    # Stated tolerances from 100 Hz to 2 kHz on the example's 1.25 mm P1 slabs: 5e-4 relative
    # surface-impedance error (measured 1.3e-4) and 4e-3 pressure error in the air relative to
    # the largest air pressure (measured 2.0e-3 at 2 kHz, growing with frequency as the
    # discretization error of the layer and the air column accumulates).
    assert max(impedance_errors) < 5e-4, impedance_errors
    assert max(pressure_errors) < 4e-3, pressure_errors


def _fem_volume_domain(run: Path) -> dict:
    domains = json.loads((run / "domains.json").read_text(encoding="utf-8"))["domains"]
    return next(domain for domain in domains if domain["id"] == "domain:fem-volume")


def _region_node_slice(run: Path, region_id: str) -> slice:
    metadata = _fem_volume_domain(run)["metadata"]
    index = metadata["region_ids"].index(region_id)
    offset = metadata["node_offsets"][index]
    return slice(offset, offset + metadata["node_counts"][index])


def _region_node_coordinates(run: Path, region_id: str) -> np.ndarray:
    points = np.load(run / "domains.npz")[_domain_array(run, "domain:fem-volume", "points_m")]
    return points[_region_node_slice(run, region_id)]
