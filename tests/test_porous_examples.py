"""Headless porous-material example projects solved through the CLI against analytical references."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from blab.project_cli import main as project_main
from porous_reference import closed_tube_input_impedance, equivalent_fluid

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
