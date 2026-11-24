"""Mesh-resolution warning for porous regions, reported by `blab project validate --json`."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pytest

from blab.acoustic_materials import porous_wavelength_m, region_material
from blab.project_cli import main as project_main
from porous_reference import equivalent_fluid

FILLED_TUBE = Path(__file__).parents[1] / "examples" / "filled_tube" / "filled_tube.blab.json"
# Minimum elements per porous wavelength for 5 % input-impedance error, from the engine's
# filled-tube convergence study (docs/Porous Materials.md, Mesh resolution).
P1_ELEMENTS_PER_WAVELENGTH = 11


def _filled_tube(tmp_path: Path, *, freq_max_hz: float) -> Path:
    project = json.loads(FILLED_TUBE.read_text(encoding="utf-8"))
    project["project_preferences"]["freq_max_hz"] = freq_max_hz
    shutil.copy(FILLED_TUBE.with_suffix("").with_suffix(".msh"), tmp_path)
    path = tmp_path / FILLED_TUBE.name
    path.write_text(json.dumps(project), encoding="utf-8")
    return path


def _validate(capsys, path: Path, *extra: str) -> dict:
    capsys.readouterr()
    project_main(["validate", str(path), "--backend", "beat_cpu", "--json", *extra], prog="blab project")
    return json.loads(capsys.readouterr().out)


def _porous_wavelength_m(frequency_hz: float) -> float:
    (region,) = json.loads(FILLED_TUBE.read_text(encoding="utf-8"))["physical_system"]["regions"]
    fluid = equivalent_fluid(
        region["loss_model"],
        frequency_hz,
        density_kg_per_m3=region["density_kg_per_m3"],
        sound_speed_m_per_s=region["sound_speed_m_per_s"],
    )
    return 2.0 * math.pi / fluid.wavenumber(frequency_hz).real


def test_validate_warns_when_a_porous_region_is_too_coarse_at_the_maximum_frequency(tmp_path: Path, capsys) -> None:
    summary = _validate(capsys, _filled_tube(tmp_path, freq_max_hz=5000.0))

    assert summary["valid"]
    (warning,) = summary["warnings"]
    assert (warning["code"], warning["region_id"]) == ("porous_mesh_too_coarse", "region:fill")
    needed_mm = _porous_wavelength_m(5000.0) / P1_ELEMENTS_PER_WAVELENGTH * 1e3  # 5.34 mm
    assert f"{needed_mm:.2f} mm" in warning["message"]
    assert "volume mesh size" in warning["message"]


def test_validate_lists_no_mesh_warning_when_the_porous_mesh_resolves_the_maximum_frequency(
    tmp_path: Path, capsys
) -> None:
    # Mean edge 9.7 mm against 130.8 mm / 11 = 11.9 mm needed at 2 kHz.
    assert _validate(capsys, _filled_tube(tmp_path, freq_max_hz=2000.0))["warnings"] == []


def test_validate_checks_the_mesh_at_the_request_overlay_maximum_frequency(tmp_path: Path, capsys) -> None:
    path = _filled_tube(tmp_path, freq_max_hz=2000.0)
    coarse = tmp_path / "coarse.json"
    coarse.write_text(json.dumps({"schema_version": 1, "frequencies_hz": [500.0, 5000.0]}), encoding="utf-8")
    (tmp_path / "fine").mkdir()
    fine_path = _filled_tube(tmp_path / "fine", freq_max_hz=5000.0)
    fine = tmp_path / "fine.json"
    fine.write_text(json.dumps({"schema_version": 1, "frequencies_hz": [500.0, 2000.0]}), encoding="utf-8")

    coarse_warnings = _validate(capsys, path, "--request", str(coarse))["warnings"]
    fine_warnings = _validate(capsys, fine_path, "--request", str(fine))["warnings"]

    assert [(item["code"], item["region_id"]) for item in coarse_warnings] == [
        ("porous_mesh_too_coarse", "region:fill")
    ]
    assert "at 5000 Hz" in coarse_warnings[0]["message"]
    assert fine_warnings == []


def test_validate_applies_the_threshold_of_the_meshes_element_order(tmp_path: Path, capsys) -> None:
    gmsh = pytest.importorskip("gmsh")
    path = _filled_tube(tmp_path, freq_max_hz=5000.0)
    gmsh.initialize(["", "-v", "0"])
    try:
        gmsh.open(str(FILLED_TUBE.with_suffix("").with_suffix(".geo")))
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(path.with_suffix("").with_suffix(".msh")))
    finally:
        gmsh.finalize()

    # P2 needs 3 elements per porous wavelength: 58.7 mm / 3 = 19.6 mm, above the 9.7 mm mean edge
    # that is too coarse for P1 at 5 kHz.
    assert _validate(capsys, path)["warnings"] == []
    path.write_text(path.read_text(encoding="utf-8").replace('"freq_max_hz": 5000.0', '"freq_max_hz": 20000.0'))
    (warning,) = _validate(capsys, path)["warnings"]
    needed_mm = _porous_wavelength_m(20000.0) / 3 * 1e3
    assert "P2" in warning["message"] and f"{needed_mm:.2f} mm" in warning["message"]


SOFT_FOAM = {  # Allard & Atalla Table 11.5
    "model": "jca",
    "frame": "rigid",
    "porosity": 0.99,
    "flow_resistivity_pa_s_per_m2": 10_900.0,
    "tortuosity": 1.02,
    "viscous_characteristic_length_m": 100e-6,
    "thermal_characteristic_length_m": 130e-6,
}
GLASS_WOOL = {  # Allard & Atalla Table 11.8
    "model": "jca",
    "frame": "rigid",
    "porosity": 0.94,
    "flow_resistivity_pa_s_per_m2": 40_000.0,
    "tortuosity": 1.06,
    "viscous_characteristic_length_m": 56e-6,
    "thermal_characteristic_length_m": 110e-6,
}


@pytest.mark.parametrize(("loss_model", "wavelength_mm"), [(SOFT_FOAM, 57.5), (GLASS_WOOL, 52.6)])
def test_porous_wavelength_matches_the_convergence_study_values_at_5_khz(loss_model, wavelength_mm) -> None:
    # Values quoted in BEAT Engine docs/Porous Materials.md (Mesh resolution).
    material = region_material(loss_model, region_id="fill", bounded=True)
    wavelength = porous_wavelength_m(material, 5000.0, density_kg_per_m3=1.21, sound_speed_m_per_s=343.0)
    assert wavelength * 1e3 == pytest.approx(wavelength_mm, abs=0.05)


@pytest.mark.parametrize(
    "change",
    [{"model": "jcal", "static_thermal_permeability_m2": 2e-9}, {"frame": "limp", "frame_density_kg_per_m3": 30.0}],
)
def test_porous_wavelength_covers_jcal_and_limp_frames(change) -> None:
    loss_model = {**SOFT_FOAM, **change}
    material = region_material(loss_model, region_id="fill", bounded=True)
    fluid = equivalent_fluid(loss_model, 3000.0, density_kg_per_m3=1.2, sound_speed_m_per_s=343.0)
    expected = 2.0 * math.pi / fluid.wavenumber(3000.0).real
    wavelength = porous_wavelength_m(material, 3000.0, density_kg_per_m3=1.2, sound_speed_m_per_s=343.0)
    assert wavelength == pytest.approx(expected, rel=1e-12)
