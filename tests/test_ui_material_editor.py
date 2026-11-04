import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from blab.ui.material_editor import RegionMaterialDialog, region_material_label

_APP = QApplication.instance() or QApplication([])

# Glass wool, Allard & Atalla 2nd ed. Table 11.8, as the project stores it (SI).
GLASS_WOOL_JCA = {
    "model": "jca",
    "frame": "rigid",
    "porosity": 0.94,
    "flow_resistivity_pa_s_per_m2": 40_000.0,
    "tortuosity": 1.06,
    "viscous_characteristic_length_m": 56e-6,
    "thermal_characteristic_length_m": 110e-6,
    "preset": "glass_wool",
}


def _choose(combo, data) -> None:
    index = combo.findData(data)
    assert index >= 0, data
    combo.setCurrentIndex(index)


def _type(dialog, key: str, text: str) -> None:
    edit = dialog.fields[key]
    edit.selectAll()
    edit.insert(text)  # emits textEdited like a user keystroke


def _shown(dialog, key: str) -> bool:
    return dialog.fields[key].isVisibleTo(dialog)


def test_opening_on_a_lossless_air_region_preselects_jca_with_a_preset() -> None:
    dialog = RegionMaterialDialog({"bulk_loss_factor": 0.0}, region_name="Box")

    assert dialog.model_combo.currentData() == "jca"
    assert dialog.frame_combo.currentData() == "rigid"
    assert dialog.preset_combo.currentData() == "soft_foam"
    assert [dialog.model_combo.itemText(i) for i in range(dialog.model_combo.count())] == ["Air", "JCA", "JCAL"]
    presets = [dialog.preset_combo.itemData(i) for i in range(dialog.preset_combo.count())]
    assert len(presets) == 10 and presets[-1] == "custom"
    assert "Table 11.5" in dialog.source_label.text()


def test_a_legacy_bulk_loss_region_opens_as_air_with_its_factor() -> None:
    dialog = RegionMaterialDialog({"bulk_loss_factor": 0.02}, region_name="Box")

    assert dialog.model_combo.currentData() == "air"
    assert dialog.fields["bulk_loss_factor"].text() == "0.02"
    assert _shown(dialog, "bulk_loss_factor")
    assert not _shown(dialog, "porosity")
    assert not dialog.preset_combo.isVisibleTo(dialog)
    assert dialog.loss_model() == {"bulk_loss_factor": 0.02}


def test_choosing_a_preset_fills_the_fields_in_literature_units() -> None:
    dialog = RegionMaterialDialog({}, region_name="Box")
    _type(dialog, "porosity", "0.5")

    _choose(dialog.preset_combo, "glass_wool")

    shown = {key: dialog.fields[key].text() for key in dialog.fields}
    assert shown["porosity"] == "0.94"
    assert shown["flow_resistivity_pa_s_per_m2"] == "40000"
    assert shown["tortuosity"] == "1.06"
    assert shown["viscous_characteristic_length_m"] == "56"
    assert shown["thermal_characteristic_length_m"] == "110"
    assert shown["frame_density_kg_per_m3"] == "130"
    assert "Table 11.8" in dialog.source_label.text()
    assert dialog.loss_model() == GLASS_WOOL_JCA


def test_editing_a_value_switches_the_preset_to_custom() -> None:
    dialog = RegionMaterialDialog(GLASS_WOOL_JCA, region_name="Box")
    assert dialog.preset_combo.currentData() == "glass_wool"

    _type(dialog, "viscous_characteristic_length_m", "60")

    assert dialog.preset_combo.currentData() == "custom"
    assert dialog.loss_model() == {**GLASS_WOOL_JCA, "viscous_characteristic_length_m": 60e-6, "preset": "custom"}
    _choose(dialog.preset_combo, "glass_wool")
    assert dialog.loss_model() == GLASS_WOOL_JCA


def test_switching_to_jcal_prefills_the_static_thermal_permeability() -> None:
    dialog = RegionMaterialDialog(GLASS_WOOL_JCA, region_name="Box")
    assert not _shown(dialog, "static_thermal_permeability_m2")

    _choose(dialog.model_combo, "jcal")

    assert _shown(dialog, "static_thermal_permeability_m2")
    # 0.94 * (110 um)^2 / 8 = 1.42175e-9 m^2
    assert float(dialog.fields["static_thermal_permeability_m2"].text()) == pytest.approx(1.42175e-9)
    assert dialog.preset_combo.currentData() == "glass_wool"
    loss_model = dialog.loss_model()
    assert loss_model["model"] == "jcal"
    assert loss_model["static_thermal_permeability_m2"] == pytest.approx(1.42175e-9)
    assert loss_model["preset"] == "glass_wool"


def test_limp_frame_shows_the_frame_density_and_the_decoupling_frequency_hint() -> None:
    dialog = RegionMaterialDialog(GLASS_WOOL_JCA, region_name="Box")
    assert not _shown(dialog, "frame_density_kg_per_m3")
    assert not dialog.decoupling_label.isVisibleTo(dialog)

    _choose(dialog.frame_combo, "limp")

    assert _shown(dialog, "frame_density_kg_per_m3")
    assert dialog.decoupling_label.isVisibleTo(dialog)
    # F_d = sigma phi^2 / (2 pi rho_1) = 40000 * 0.94^2 / (2 pi 130) = 43.3 Hz
    assert "43 Hz" in dialog.decoupling_label.text()
    assert dialog.loss_model() == {**GLASS_WOOL_JCA, "frame": "limp", "frame_density_kg_per_m3": 130.0}


@pytest.mark.parametrize(
    ("key", "text", "message"),
    (
        ("porosity", "1.2", "porosity"),
        ("porosity", "0", "porosity"),
        ("flow_resistivity_pa_s_per_m2", "-5", "flow resistivity"),
        ("tortuosity", "0.9", "tortuosity"),
        ("viscous_characteristic_length_m", "0", "viscous characteristic length"),
        ("tortuosity", "abc", "Tortuosity"),
    ),
)
def test_impossible_values_are_rejected_inline(key, text, message) -> None:
    dialog = RegionMaterialDialog(GLASS_WOOL_JCA, region_name="Box")
    assert dialog.ok_button.isEnabled()

    _type(dialog, key, text)

    assert message in dialog.validation_label.text()
    assert not dialog.ok_button.isEnabled()


def test_impossible_air_and_limp_values_are_rejected_inline() -> None:
    dialog = RegionMaterialDialog({"bulk_loss_factor": 0.0}, region_name="Box")
    _choose(dialog.model_combo, "air")
    _type(dialog, "bulk_loss_factor", "1.5")
    assert "bulk loss" in dialog.validation_label.text()
    assert not dialog.ok_button.isEnabled()

    limp = RegionMaterialDialog({**GLASS_WOOL_JCA, "frame": "limp", "frame_density_kg_per_m3": 130.0})
    _type(limp, "frame_density_kg_per_m3", "0")
    assert "frame density" in limp.validation_label.text()
    assert not limp.ok_button.isEnabled()


def test_a_thermal_length_below_the_viscous_length_warns_without_rejecting() -> None:
    dialog = RegionMaterialDialog(GLASS_WOOL_JCA, region_name="Box")

    _type(dialog, "thermal_characteristic_length_m", "40")

    assert "smaller than its viscous characteristic length" in dialog.validation_label.text()
    assert dialog.ok_button.isEnabled()


def test_material_cell_labels_name_the_model_and_its_origin() -> None:
    assert region_material_label({}) == "Air"
    assert region_material_label({"bulk_loss_factor": 0.0}) == "Air"
    assert region_material_label({"bulk_loss_factor": 0.02}) == "Air – loss 0.02"
    assert region_material_label(GLASS_WOOL_JCA) == "JCA – Glass wool"
    assert region_material_label({**GLASS_WOOL_JCA, "model": "jcal", "static_thermal_permeability_m2": 1e-9}) == (
        "JCAL – Custom"
    )
    assert region_material_label({"model": "jca"}) == "Invalid material"
