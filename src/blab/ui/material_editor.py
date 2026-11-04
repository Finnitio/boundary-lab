"""Region Material dialog: Air, or a JCA/JCAL porous material from a preset or custom values."""

from __future__ import annotations

import math
from typing import Any, Mapping

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from blab.acoustic_materials import (
    MATERIAL_FRAME_LIMP,
    MATERIAL_FRAME_RIGID,
    MATERIAL_MODEL_AIR,
    MATERIAL_MODEL_JCA,
    MATERIAL_MODEL_JCAL,
    MATERIAL_MODEL_LABELS,
    MATERIAL_PRESET_CUSTOM,
    MATERIAL_PRESETS,
    POROUS_MATERIAL_MODELS,
    REGION_BULK_LOSS_FACTOR_KEY,
    REGION_MATERIAL_FRAME_KEY,
    REGION_MATERIAL_FRAMES,
    REGION_MATERIAL_MODEL_KEY,
    REGION_MATERIAL_MODELS,
    REGION_MATERIAL_PRESET_KEY,
    MaterialError,
    jcal_static_thermal_permeability,
    material_preset,
    region_material,
    region_material_warnings,
)
from blab.ui.numeric_locale import format_decimal_number, parse_decimal_number

_FRAME_LABELS = {MATERIAL_FRAME_RIGID: "Rigid", MATERIAL_FRAME_LIMP: "Limp"}

# (loss-model key, label, literature unit, display value per SI value)
_FIELDS: tuple[tuple[str, str, str, float], ...] = (
    (REGION_BULK_LOSS_FACTOR_KEY, "FEM bulk loss factor η", "", 1.0),
    ("porosity", "Porosity φ", "", 1.0),
    ("flow_resistivity_pa_s_per_m2", "Flow resistivity σ", "Pa·s/m²", 1.0),
    ("tortuosity", "Tortuosity α∞", "", 1.0),
    ("viscous_characteristic_length_m", "Viscous length Λ", "µm", 1e6),
    ("thermal_characteristic_length_m", "Thermal length Λ′", "µm", 1e6),
    ("static_thermal_permeability_m2", "Static thermal permeability k₀′", "m²", 1.0),
    ("frame_density_kg_per_m3", "Frame density ρ₁", "kg/m³", 1.0),
)
_STATIC_THERMAL_PERMEABILITY_KEY = "static_thermal_permeability_m2"
_FIELD_LABELS = {key: label for key, label, _unit, _scale in _FIELDS}
_DISPLAY_PER_SI = {key: scale for key, _label, _unit, scale in _FIELDS}


def region_material_label(loss_model: Mapping[str, Any] | None) -> str:
    """Return the System › Regions Material cell text: ``Air``, ``JCA – <preset>`` or ``… – Custom``."""

    try:
        material = region_material(loss_model, region_id="region", bounded=True)
    except MaterialError:
        return "Invalid material"
    if not material.is_porous:
        return "Air" if material.bulk_loss_factor == 0.0 else f"Air – loss {material.bulk_loss_factor:g}"
    preset = material_preset(material.preset or MATERIAL_PRESET_CUSTOM)
    return f"{MATERIAL_MODEL_LABELS[material.model]} – {'Custom' if preset is None else preset.name}"


class RegionMaterialDialog(QDialog):
    """Edit one bounded region's Material; ``loss_model()`` returns the project loss model."""

    def __init__(
        self,
        loss_model: Mapping[str, Any] | None,
        parent: QWidget | None = None,
        *,
        region_name: str = "region",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Material – {region_name}")
        self._region_name = region_name
        self._values: dict[str, float | None] = {}
        self._parse_errors: dict[str, str] = {}
        # The k₀′ the dialog last derived as φΛ′²/8; a k₀′ that differs was entered or loaded and is kept.
        self._prefilled_static_thermal_permeability: float | None = None

        self.model_combo = QComboBox()
        for model, label in MATERIAL_MODEL_LABELS.items():
            self.model_combo.addItem(label, model)
        self.preset_combo = QComboBox()
        for preset in MATERIAL_PRESETS:
            self.preset_combo.addItem(preset.name, preset.id)
        self.preset_combo.addItem("Custom", MATERIAL_PRESET_CUSTOM)
        self.source_label = QLabel()
        self.source_label.setWordWrap(True)
        self.frame_combo = QComboBox()
        for frame, label in _FRAME_LABELS.items():
            self.frame_combo.addItem(label, frame)

        self.fields: dict[str, QLineEdit] = {}
        self._form = QFormLayout()
        self._form.addRow("Model", self.model_combo)
        self._form.addRow("Preset", self.preset_combo)
        self._form.addRow("", self.source_label)
        self._form.addRow("Frame", self.frame_combo)
        for key, label, unit, _scale in _FIELDS:
            edit = QLineEdit()
            edit.textEdited.connect(lambda text, k=key: self._edited(k, text))
            self.fields[key] = edit
            self._form.addRow(f"{label} [{unit}]" if unit else label, edit)
        self.decoupling_label = QLabel()
        self.decoupling_label.setWordWrap(True)
        self._form.addRow("", self.decoupling_label)

        self.validation_label = QLabel()
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #b3261e;")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        layout = QVBoxLayout(self)
        layout.addLayout(self._form)
        layout.addWidget(self.validation_label)
        layout.addWidget(buttons)

        self._load(loss_model or {})
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        self.frame_combo.currentIndexChanged.connect(self._refresh)
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        self._refresh()
        self.resize(460, 0)

    # -- state ---------------------------------------------------------------

    def _load(self, loss_model: Mapping[str, Any]) -> None:
        for key in self.fields:
            raw = loss_model.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                self._set_value(key, float(raw))
        try:
            material = region_material(loss_model, region_id=self._region_name, bounded=True)
        except MaterialError:
            model = loss_model.get(REGION_MATERIAL_MODEL_KEY)
            self._select(self.model_combo, model if model in REGION_MATERIAL_MODELS else MATERIAL_MODEL_JCA)
            self._select(self.frame_combo, loss_model.get(REGION_MATERIAL_FRAME_KEY, MATERIAL_FRAME_RIGID))
            self._select(self.preset_combo, MATERIAL_PRESET_CUSTOM)
            return
        if material.is_porous:
            self._select(self.model_combo, material.model)
            self._select(self.frame_combo, material.frame)
            self._select(self.preset_combo, material.preset)
            if material.preset != MATERIAL_PRESET_CUSTOM:
                self._fill_preset(material.preset)  # also fills ρ₁/k₀′ for later frame or model switches
            return
        self._set_value(REGION_BULK_LOSS_FACTOR_KEY, material.bulk_loss_factor)
        self._select(self.frame_combo, MATERIAL_FRAME_RIGID)
        if material.bulk_loss_factor > 0.0:
            self._select(self.model_combo, MATERIAL_MODEL_AIR)
            self._select(self.preset_combo, MATERIAL_PRESETS[0].id)
            self._fill_preset(MATERIAL_PRESETS[0].id)
            return
        # A lossless air region is opened to turn it into damping material.
        self._select(self.model_combo, MATERIAL_MODEL_JCA)
        self._select(self.preset_combo, MATERIAL_PRESETS[0].id)
        self._fill_preset(MATERIAL_PRESETS[0].id)

    @staticmethod
    def _select(combo: QComboBox, data: Any) -> None:
        index = combo.findData(data)
        combo.setCurrentIndex(max(index, 0))

    def _set_value(self, key: str, value: float | None) -> None:
        self._values[key] = value
        self._parse_errors.pop(key, None)
        edit = self.fields[key]
        edit.setText("" if value is None else format_decimal_number(value * _DISPLAY_PER_SI[key], edit.locale()))

    def _fill_preset(self, preset_id: str) -> None:
        preset = material_preset(preset_id)
        if preset is None:
            return
        for key, value in preset.parameters.items():
            self._set_value(key, value)
        self._prefill_static_thermal_permeability()

    def _prefill_static_thermal_permeability(self, *, keep_entered: bool = False) -> None:
        """Set k₀′ = φΛ′²/8; with ``keep_entered`` only when k₀′ is empty or still the last prefill."""

        current = self._values.get(_STATIC_THERMAL_PERMEABILITY_KEY)
        if keep_entered and current is not None and current != self._prefilled_static_thermal_permeability:
            return
        porosity = self._values.get("porosity")
        thermal = self._values.get("thermal_characteristic_length_m")
        if porosity is not None and thermal is not None:
            value = jcal_static_thermal_permeability(porosity=porosity, thermal_characteristic_length_m=thermal)
            self._set_value(_STATIC_THERMAL_PERMEABILITY_KEY, value)
            self._prefilled_static_thermal_permeability = value

    # -- reactions -----------------------------------------------------------

    def _edited(self, key: str, text: str) -> None:
        try:
            self._values[key] = parse_decimal_number(text, self.fields[key].locale()) / _DISPLAY_PER_SI[key]
            self._parse_errors.pop(key, None)
        except ValueError:
            self._values[key] = None
            self._parse_errors[key] = f"{_FIELD_LABELS[key]}: enter a number."
        if self.preset_combo.currentData() != MATERIAL_PRESET_CUSTOM:
            self.preset_combo.blockSignals(True)
            self._select(self.preset_combo, MATERIAL_PRESET_CUSTOM)
            self.preset_combo.blockSignals(False)
        self._refresh()

    def _preset_changed(self, _index: int) -> None:
        self._fill_preset(str(self.preset_combo.currentData()))
        self._refresh()

    def _model_changed(self, _index: int) -> None:
        if self.model_combo.currentData() == MATERIAL_MODEL_JCAL:
            self._prefill_static_thermal_permeability(keep_entered=True)
        if (
            self._values.get(REGION_BULK_LOSS_FACTOR_KEY) is None
            and self.model_combo.currentData() == MATERIAL_MODEL_AIR
        ):
            self._set_value(REGION_BULK_LOSS_FACTOR_KEY, 0.0)
        self._refresh()

    def _active_keys(self) -> tuple[str, ...]:
        model = str(self.model_combo.currentData())
        if model not in POROUS_MATERIAL_MODELS:
            return (REGION_BULK_LOSS_FACTOR_KEY,)
        return (*REGION_MATERIAL_MODELS[model], *REGION_MATERIAL_FRAMES[str(self.frame_combo.currentData())])

    def _refresh(self, *_args: Any) -> None:
        porous = self.model_combo.currentData() in POROUS_MATERIAL_MODELS
        active = set(self._active_keys())
        for key, edit in self.fields.items():
            self._form.setRowVisible(edit, key in active)
        for widget in (self.preset_combo, self.source_label, self.frame_combo):
            self._form.setRowVisible(widget, porous)
        preset = material_preset(str(self.preset_combo.currentData()))
        self.source_label.setText(
            "Your own values." if preset is None else f"Source: {preset.source}. Values stay editable."
        )
        self._refresh_decoupling_hint(porous)
        self._refresh_validation()

    def _refresh_decoupling_hint(self, porous: bool) -> None:
        limp = porous and self.frame_combo.currentData() == MATERIAL_FRAME_LIMP
        self._form.setRowVisible(self.decoupling_label, limp)
        sigma = self._values.get("flow_resistivity_pa_s_per_m2")
        porosity = self._values.get("porosity")
        rho1 = self._values.get("frame_density_kg_per_m3")
        if not limp or not sigma or not porosity or not rho1 or rho1 <= 0.0:
            self.decoupling_label.setText("")
            return
        decoupling_hz = sigma * porosity**2 / (2.0 * math.pi * rho1)
        self.decoupling_label.setText(
            f"Decoupling frequency F_d = σφ²/(2πρ₁) ≈ {decoupling_hz:.0f} Hz: below it the limp frame "
            "moves with the air, well above it the frame is effectively rigid."
        )

    def _refresh_validation(self) -> None:
        active = self._active_keys()
        errors = [message for key, message in self._parse_errors.items() if key in active]
        warnings: list[str] = []
        if not errors:
            try:
                material = region_material(self._raw_loss_model(), region_id=self._region_name, bounded=True)
            except MaterialError as exc:
                errors = list(exc.issues)
            else:
                warnings = [
                    warning.message for warning in region_material_warnings(material, region_id=self._region_name)
                ]
        self.validation_label.setText("\n".join(errors or [f"Warning: {message}" for message in warnings]))
        self.validation_label.setStyleSheet("color: #b3261e;" if errors else "color: #8a5a00;")
        self.ok_button.setEnabled(not errors)

    def _raw_loss_model(self) -> dict[str, Any]:
        model = str(self.model_combo.currentData())
        values = {key: self._values.get(key) for key in self._active_keys()}
        if model not in POROUS_MATERIAL_MODELS:
            return values
        return {
            REGION_MATERIAL_MODEL_KEY: model,
            REGION_MATERIAL_FRAME_KEY: str(self.frame_combo.currentData()),
            **values,
            REGION_MATERIAL_PRESET_KEY: str(self.preset_combo.currentData()),
        }

    def loss_model(self) -> dict[str, Any]:
        """Return the project loss model: legacy ``{bulk_loss_factor}`` for Air, else all SI values and preset."""

        material = region_material(self._raw_loss_model(), region_id=self._region_name, bounded=True)
        if not material.is_porous:
            return {REGION_BULK_LOSS_FACTOR_KEY: material.bulk_loss_factor}
        return material.to_project_loss_model()
