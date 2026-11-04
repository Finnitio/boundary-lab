import pytest

from blab.acoustic_materials import (
    Material,
    MaterialError,
    boundary_thermoviscous_wall_losses,
    miki_wall_impedance_parameters,
    region_bulk_loss_factor,
    region_material,
    region_material_warnings,
    wall_impedance_parameters,
)


def test_thermoviscous_losses_default_off_and_validate() -> None:
    assert boundary_thermoviscous_wall_losses({}) == "off"
    assert (
        boundary_thermoviscous_wall_losses({"thermoviscous_wall_losses": "thin_boundary_layer"})
        == "thin_boundary_layer"
    )
    for invalid in (True, None, "unknown", {}, []):
        with pytest.raises(ValueError, match="Thermoviscous"):
            boundary_thermoviscous_wall_losses({"thermoviscous_wall_losses": invalid})


def test_region_bulk_loss_factor_defaults_and_validates() -> None:
    assert region_bulk_loss_factor({}) == 0.0
    assert region_bulk_loss_factor({"bulk_loss_factor": 0.02}) == pytest.approx(0.02)
    with pytest.raises(ValueError, match="between 0 and 1"):
        region_bulk_loss_factor({"bulk_loss_factor": 1.01})


def test_miki_wall_parameters_use_polyfill_defaults_and_round_trip() -> None:
    parameters = miki_wall_impedance_parameters()
    treatment = wall_impedance_parameters(parameters)

    assert treatment is not None
    assert treatment["model"] == "miki"
    assert treatment["thickness_m"] == pytest.approx(0.03)
    assert treatment["flow_resistivity_pa_s_per_m2"] == pytest.approx(5000.0)


@pytest.mark.parametrize(
    "parameters",
    (
        {"wall_impedance": {"model": "unknown"}},
        {"wall_impedance": {"thickness_m": 0.0}},
        {"wall_impedance": {"flow_resistivity_pa_s_per_m2": -1.0}},
    ),
)
def test_wall_impedance_parameters_reject_invalid_values(parameters) -> None:
    with pytest.raises(ValueError):
        wall_impedance_parameters(parameters)


@pytest.mark.parametrize(
    ("loss_model", "bulk_loss_factor"),
    (
        (None, 0.0),
        ({}, 0.0),
        ({"bulk_loss_factor": 0.02}, 0.02),
        ({"model": "air"}, 0.0),
        ({"model": "air", "bulk_loss_factor": 0.005}, 0.005),
    ),
)
def test_region_material_reads_legacy_and_explicit_air(loss_model, bulk_loss_factor) -> None:
    material = region_material(loss_model, region_id="region:box", bounded=True)

    assert material == Material(model="air", bulk_loss_factor=bulk_loss_factor)


def test_region_material_reports_every_issue_with_the_region() -> None:
    with pytest.raises(MaterialError) as caught:
        region_material(
            {"bulk_loss_factor": 1.5, "flow_resistivity": 5000.0, "foo": 1},
            region_id="region:box",
            bounded=True,
        )

    assert caught.value.issues == (
        "Region 'region:box' uses unsupported loss parameters: flow_resistivity, foo.",
        "Region 'region:box' FEM bulk loss factor must be a finite number between 0 and 1.",
    )


@pytest.mark.parametrize("model", ("biot", "", 3))
def test_region_material_rejects_unknown_models(model) -> None:
    with pytest.raises(MaterialError, match="unsupported material model"):
        region_material({"model": model}, region_id="region:box", bounded=True)


def test_region_material_rejects_bulk_loss_outside_bounded_air() -> None:
    assert region_material({"bulk_loss_factor": 0.0}, region_id="region:far", bounded=False) == Material()
    with pytest.raises(MaterialError, match="Region 'region:far' FEM bulk loss requires a bounded-air region"):
        region_material({"bulk_loss_factor": 0.01}, region_id="region:far", bounded=False)


# Soft fibrous material, Allard & Atalla 2nd ed. Table 11.2, in SI.
SOFT_FIBROUS_JCA = {
    "model": "jca",
    "frame": "rigid",
    "porosity": 0.98,
    "flow_resistivity_pa_s_per_m2": 25_000,
    "tortuosity": 1.02,
    "viscous_characteristic_length_m": 90e-6,
    "thermal_characteristic_length_m": 180e-6,
}


def test_region_material_normalizes_a_rigid_jca_material() -> None:
    material = region_material(SOFT_FIBROUS_JCA, region_id="region:fill", bounded=True)

    assert material.is_porous
    assert (material.model, material.frame) == ("jca", "rigid")
    assert material.to_loss_model() == SOFT_FIBROUS_JCA
    assert isinstance(material.to_loss_model()["flow_resistivity_pa_s_per_m2"], float)
    assert region_material({}, region_id="region:box", bounded=True).to_loss_model() == {
        "model": "air",
        "bulk_loss_factor": 0.0,
    }


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"porosity": 0.0}, r"porosity \(porosity\) must be a finite number > 0 and <= 1\."),
        ({"porosity": 1.01}, r"porosity \(porosity\) must be a finite number > 0 and <= 1\."),
        ({"flow_resistivity_pa_s_per_m2": 0.0}, r"flow resistivity .* must be a finite number > 0\."),
        ({"tortuosity": 0.99}, r"tortuosity \(tortuosity\) must be a finite number >= 1\."),
        ({"viscous_characteristic_length_m": -1e-6}, r"viscous characteristic length .* > 0\."),
        ({"thermal_characteristic_length_m": float("nan")}, r"thermal characteristic length .* > 0\."),
        ({"tortuosity": "1.02"}, r"tortuosity \(tortuosity\) must be a finite number"),
        ({"porosity": None}, r"porosity \(porosity\) must be a finite number"),
        ({"frame": "elastic"}, r"unsupported JCA frame 'elastic'; expected one of: limp, rigid\."),
        ({"frame": None}, r"unsupported JCA frame None"),
        ({"bulk_loss_factor": 0.0}, r"FEM bulk loss factor is only available for Air, not JCA\."),
        ({"static_thermal_permeability_m2": 1e-9}, r"unsupported JCA parameters: static_thermal_permeability_m2\."),
    ),
)
def test_region_material_rejects_invalid_jca_materials(change, message) -> None:
    with pytest.raises(MaterialError, match=f"^Region 'region:fill' .*{message}"):
        region_material({**SOFT_FIBROUS_JCA, **change}, region_id="region:fill", bounded=True)


def test_region_material_reports_missing_jca_parameters_and_unbounded_regions() -> None:
    with pytest.raises(MaterialError) as caught:
        region_material({"model": "jca", "frame": "rigid", "porosity": 0.9}, region_id="region:far", bounded=False)

    assert caught.value.issues == (
        "Region 'region:far' porous material 'jca' requires a bounded-air region.",
        "Region 'region:far' JCA material is missing flow resistivity (flow_resistivity_pa_s_per_m2).",
        "Region 'region:far' JCA material is missing tortuosity (tortuosity).",
        "Region 'region:far' JCA material is missing viscous characteristic length (viscous_characteristic_length_m).",
        "Region 'region:far' JCA material is missing thermal characteristic length (thermal_characteristic_length_m).",
    )


def test_region_material_normalizes_jcal_with_its_static_thermal_permeability() -> None:
    jcal = {**SOFT_FIBROUS_JCA, "model": "jcal", "static_thermal_permeability_m2": 2e-9}

    material = region_material(jcal, region_id="region:fill", bounded=True)

    assert material.is_porous
    assert (material.model, material.frame) == ("jcal", "rigid")
    assert material.to_loss_model() == jcal


def test_region_material_normalizes_a_limp_frame_with_its_frame_density() -> None:
    limp = {**SOFT_FIBROUS_JCA, "frame": "limp", "frame_density_kg_per_m3": 30}

    material = region_material(limp, region_id="region:fill", bounded=True)

    assert (material.model, material.frame) == ("jca", "limp")
    assert material.to_loss_model() == limp
    assert isinstance(material.to_loss_model()["frame_density_kg_per_m3"], float)


JCAL_LIMP = {
    **SOFT_FIBROUS_JCA,
    "model": "jcal",
    "frame": "limp",
    "static_thermal_permeability_m2": 2e-9,
    "frame_density_kg_per_m3": 30.0,
}


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"static_thermal_permeability_m2": 0.0}, r"JCAL static thermal permeability .* must be a finite number > 0\."),
        ({"static_thermal_permeability_m2": -1e-9}, r"JCAL static thermal permeability .* > 0\."),
        ({"frame_density_kg_per_m3": 0.0}, r"JCAL frame density .* must be a finite number > 0\."),
        ({"frame_density_kg_per_m3": float("inf")}, r"JCAL frame density .* > 0\."),
        ({"frame": "elastic"}, r"unsupported JCAL frame 'elastic'; expected one of: limp, rigid\."),
    ),
)
def test_region_material_rejects_invalid_jcal_and_limp_parameters(change, message) -> None:
    with pytest.raises(MaterialError, match=f"^Region 'region:fill' .*{message}"):
        region_material({**JCAL_LIMP, **change}, region_id="region:fill", bounded=True)


def test_region_material_requires_and_scopes_jcal_and_limp_parameters() -> None:
    with pytest.raises(MaterialError) as missing:
        region_material({**SOFT_FIBROUS_JCA, "model": "jcal", "frame": "limp"}, region_id="region:fill", bounded=True)
    with pytest.raises(MaterialError) as rigid:
        region_material({**SOFT_FIBROUS_JCA, "frame_density_kg_per_m3": 30.0}, region_id="region:fill", bounded=True)

    assert missing.value.issues == (
        "Region 'region:fill' JCAL material is missing static thermal permeability (static_thermal_permeability_m2).",
        "Region 'region:fill' JCAL material is missing frame density (frame_density_kg_per_m3).",
    )
    assert rigid.value.issues == ("Region 'region:fill' uses unsupported JCA parameters: frame_density_kg_per_m3.",)


def test_material_warns_but_does_not_reject_a_thermal_length_below_the_viscous_length() -> None:
    inverted = {**SOFT_FIBROUS_JCA, "thermal_characteristic_length_m": 60e-6}

    material = region_material(inverted, region_id="region:fill", bounded=True)

    assert [warning.as_dict() for warning in region_material_warnings(material, region_id="region:fill")] == [
        {
            "code": "porous_thermal_length_below_viscous_length",
            "region_id": "region:fill",
            "message": "Region 'region:fill' JCA thermal characteristic length (60 um) is smaller than its viscous "
            "characteristic length (90 um); measured data usually has thermal >= viscous. Check the values.",
        }
    ]
    for regular in (SOFT_FIBROUS_JCA, {**SOFT_FIBROUS_JCA, "thermal_characteristic_length_m": 90e-6}, {}):
        assert region_material_warnings(region_material(regular, region_id="r", bounded=True), region_id="r") == ()
