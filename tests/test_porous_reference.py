"""Limits of the analytical porous references that the solver-backed tests compare against."""

from __future__ import annotations

import pytest

from porous_reference import equivalent_fluid

RHO0, C0 = 1.205, 343.0
SOFT_FIBROUS_JCA = {
    "model": "jca",
    "frame": "rigid",
    "porosity": 0.98,
    "flow_resistivity_pa_s_per_m2": 25_000.0,
    "tortuosity": 1.02,
    "viscous_characteristic_length_m": 90e-6,
    "thermal_characteristic_length_m": 180e-6,
}


def _fluid(parameters, frequency_hz=1000.0):
    return equivalent_fluid(parameters, frequency_hz, density_kg_per_m3=RHO0, sound_speed_m_per_s=C0)


def test_jcal_with_the_jca_static_thermal_permeability_is_jca() -> None:
    phi, thermal_length = SOFT_FIBROUS_JCA["porosity"], SOFT_FIBROUS_JCA["thermal_characteristic_length_m"]
    jcal = {**SOFT_FIBROUS_JCA, "model": "jcal", "static_thermal_permeability_m2": phi * thermal_length**2 / 8.0}

    assert _fluid(jcal).density_kg_per_m3 == pytest.approx(_fluid(SOFT_FIBROUS_JCA).density_kg_per_m3, rel=1e-14)
    assert _fluid(jcal).bulk_modulus_pa == pytest.approx(_fluid(SOFT_FIBROUS_JCA).bulk_modulus_pa, rel=1e-14)


def test_jcal_static_thermal_permeability_changes_only_the_bulk_modulus() -> None:
    jcal = {**SOFT_FIBROUS_JCA, "model": "jcal", "static_thermal_permeability_m2": 2e-9}

    assert _fluid(jcal).density_kg_per_m3 == _fluid(SOFT_FIBROUS_JCA).density_kg_per_m3
    assert abs(_fluid(jcal).bulk_modulus_pa / _fluid(SOFT_FIBROUS_JCA).bulk_modulus_pa - 1.0) > 1e-3


def test_limp_frame_moves_with_the_air_at_low_frequency_and_is_rigid_when_heavy() -> None:
    frame_density = 30.0
    limp = {**SOFT_FIBROUS_JCA, "frame": "limp", "frame_density_kg_per_m3": frame_density}
    total_density = frame_density + SOFT_FIBROUS_JCA["porosity"] * RHO0
    heavy = {**limp, "frame_density_kg_per_m3": 1e12}

    assert _fluid(limp, 1e-3).density_kg_per_m3 == pytest.approx(total_density, rel=1e-4)
    assert _fluid(heavy).density_kg_per_m3 == pytest.approx(_fluid(SOFT_FIBROUS_JCA).density_kg_per_m3, rel=1e-8)
    assert _fluid(limp).bulk_modulus_pa == _fluid(SOFT_FIBROUS_JCA).bulk_modulus_pa
