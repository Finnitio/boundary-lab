import pytest

from blab.acoustic_materials import (
    Material,
    MaterialError,
    boundary_thermoviscous_wall_losses,
    miki_wall_impedance_parameters,
    region_bulk_loss_factor,
    region_material,
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


@pytest.mark.parametrize("model", ("jca", "", 3))
def test_region_material_rejects_unknown_models(model) -> None:
    with pytest.raises(MaterialError, match="unsupported material model"):
        region_material({"model": model}, region_id="region:box", bounded=True)


def test_region_material_rejects_bulk_loss_outside_bounded_air() -> None:
    assert region_material({"bulk_loss_factor": 0.0}, region_id="region:far", bounded=False) == Material()
    with pytest.raises(MaterialError, match="Region 'region:far' FEM bulk loss requires a bounded-air region"):
        region_material({"bulk_loss_factor": 0.01}, region_id="region:far", bounded=False)
