"""Physical acoustic-loss parameter helpers shared by the UI and solvers."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib import resources
from typing import Any, Mapping

from blab.physical_model import ValidationWarning

REGION_BULK_LOSS_FACTOR_KEY = "bulk_loss_factor"
REGION_MATERIAL_MODEL_KEY = "model"
REGION_MATERIAL_FRAME_KEY = "frame"
REGION_MATERIAL_PRESET_KEY = "preset"
MATERIAL_PRESET_CUSTOM = "custom"
MATERIAL_MODEL_AIR = "air"
MATERIAL_MODEL_JCA = "jca"
MATERIAL_MODEL_JCAL = "jcal"
MATERIAL_FRAME_RIGID = "rigid"
MATERIAL_FRAME_LIMP = "limp"


@dataclass(frozen=True)
class MaterialParameter:
    """Valid range of one SI material parameter: ``low < value`` (or ``<=``) and ``value <= high``."""

    label: str
    low: float
    low_inclusive: bool = False
    high: float | None = None

    def accepts(self, value: float) -> bool:
        above = value >= self.low if self.low_inclusive else value > self.low
        return math.isfinite(value) and above and (self.high is None or value <= self.high)

    def describe(self) -> str:
        bound = f"{'>=' if self.low_inclusive else '>'} {self.low:g}"
        return bound if self.high is None else f"{bound} and <= {self.high:g}"


# Region materials mirror the BEAT Engine region ``loss_model`` wire contract
# (``beat_contract.REGION_MATERIAL_MODELS``/``REGION_MATERIAL_FRAMES``/``_POROUS_PARAMETERS``):
# each model lists the keys it accepts besides ``model`` (and ``frame``), and each frame of
# a porous model lists the parameters it adds. A loss model without ``model`` is legacy Air.
POROUS_MATERIAL_PARAMETERS: dict[str, MaterialParameter] = {
    "porosity": MaterialParameter("porosity", 0.0, high=1.0),
    "flow_resistivity_pa_s_per_m2": MaterialParameter("flow resistivity", 0.0),
    "tortuosity": MaterialParameter("tortuosity", 1.0, low_inclusive=True),
    "viscous_characteristic_length_m": MaterialParameter("viscous characteristic length", 0.0),
    "thermal_characteristic_length_m": MaterialParameter("thermal characteristic length", 0.0),
    "static_thermal_permeability_m2": MaterialParameter("static thermal permeability", 0.0),
    "frame_density_kg_per_m3": MaterialParameter("frame density", 0.0),
}
_JCA_PARAMETERS = (
    "porosity",
    "flow_resistivity_pa_s_per_m2",
    "tortuosity",
    "viscous_characteristic_length_m",
    "thermal_characteristic_length_m",
)
REGION_MATERIAL_MODELS: dict[str, tuple[str, ...]] = {
    MATERIAL_MODEL_AIR: (REGION_BULK_LOSS_FACTOR_KEY,),
    MATERIAL_MODEL_JCA: _JCA_PARAMETERS,
    MATERIAL_MODEL_JCAL: (*_JCA_PARAMETERS, "static_thermal_permeability_m2"),
}
REGION_MATERIAL_FRAMES: dict[str, tuple[str, ...]] = {
    MATERIAL_FRAME_RIGID: (),
    MATERIAL_FRAME_LIMP: ("frame_density_kg_per_m3",),
}
POROUS_MATERIAL_MODELS = frozenset(set(REGION_MATERIAL_MODELS) - {MATERIAL_MODEL_AIR})
BOUNDARY_THERMOVISCOUS_LOSS_KEY = "thermoviscous_wall_losses"
FEM_BULK_LOSS_FACTOR_OPTIONS = (0.0, 0.002, 0.005, 0.01, 0.02, 0.05)
WALL_IMPEDANCE_KEY = "wall_impedance"
WALL_IMPEDANCE_MODEL_MIKI = "miki"

DEFAULT_WALL_LINING_THICKNESS_M = 0.03
DEFAULT_WALL_LINING_FLOW_RESISTIVITY_PA_S_PER_M2 = 5_000.0


def boundary_thermoviscous_wall_losses(parameters: Mapping[str, Any] | None) -> str:
    """Return the pressure FEM wall-loss model; old projects remain lossless."""
    model = "off" if not parameters else parameters.get(BOUNDARY_THERMOVISCOUS_LOSS_KEY, "off")
    if model not in ("off", "thin_boundary_layer"):
        raise ValueError("Thermoviscous wall losses must be 'off' or 'thin_boundary_layer'.")
    return model


@dataclass(frozen=True)
class Material:
    """Normalized acoustic material of a region, keyed like the engine wire contract.

    Air carries only ``bulk_loss_factor``; a porous model carries its ``frame`` and its
    SI ``parameters`` as ``(wire key, value)`` pairs in table order.
    """

    model: str = MATERIAL_MODEL_AIR
    bulk_loss_factor: float = 0.0
    frame: str | None = None
    parameters: tuple[tuple[str, float], ...] = ()
    preset: str | None = None
    """Porous only: the Material preset id the parameters still equal, or ``"custom"``."""

    @property
    def is_porous(self) -> bool:
        return self.model in POROUS_MATERIAL_MODELS

    def to_loss_model(self) -> dict[str, Any]:
        """Return the normalized engine ``loss_model`` (explicit model, SI floats, no preset name)."""

        if not self.is_porous:
            return {REGION_MATERIAL_MODEL_KEY: self.model, REGION_BULK_LOSS_FACTOR_KEY: self.bulk_loss_factor}
        return {REGION_MATERIAL_MODEL_KEY: self.model, REGION_MATERIAL_FRAME_KEY: self.frame, **dict(self.parameters)}

    def to_project_loss_model(self) -> dict[str, Any]:
        """Return the project ``loss_model``: the engine form plus, for porous models, the preset name."""

        loss_model = self.to_loss_model()
        if self.is_porous:
            loss_model[REGION_MATERIAL_PRESET_KEY] = self.preset or MATERIAL_PRESET_CUSTOM
        return loss_model


@dataclass(frozen=True)
class MaterialPreset:
    """A named porous parameter set from the built-in library, in SI.

    ``parameters`` holds the JCA parameters and the limp frame density; JCAL derives its
    static thermal permeability from them (no preset carries a measured value).
    """

    id: str
    name: str
    source: str
    parameters: dict[str, float]

    def loss_model(self, *, model: str, frame: str) -> dict[str, Any]:
        """Return the project loss model of this preset for a porous ``model`` and ``frame``."""

        if model not in POROUS_MATERIAL_MODELS or frame not in REGION_MATERIAL_FRAMES:
            raise ValueError(f"Material presets describe porous models, not {model!r} with frame {frame!r}.")
        values = dict(self.parameters)
        values["static_thermal_permeability_m2"] = jcal_static_thermal_permeability(
            porosity=values["porosity"], thermal_characteristic_length_m=values["thermal_characteristic_length_m"]
        )
        keys = (*REGION_MATERIAL_MODELS[model], *REGION_MATERIAL_FRAMES[frame])
        return {
            REGION_MATERIAL_MODEL_KEY: model,
            REGION_MATERIAL_FRAME_KEY: frame,
            **{key: values[key] for key in keys},
            REGION_MATERIAL_PRESET_KEY: self.id,
        }

    def matches(self, model: str, frame: str, parameters: Mapping[str, float]) -> bool:
        """Whether every parameter of a porous material equals this preset's value for that model and frame."""

        expected = self.loss_model(model=model, frame=frame)
        return set(parameters) == set(expected) - {
            REGION_MATERIAL_MODEL_KEY,
            REGION_MATERIAL_FRAME_KEY,
            REGION_MATERIAL_PRESET_KEY,
        } and all(
            math.isclose(value, expected[key], rel_tol=_PRESET_RELATIVE_TOLERANCE) for key, value in parameters.items()
        )


_PRESET_RELATIVE_TOLERANCE = 1e-9
_PRESET_FILE_KEYS = {
    "porosity": ("porosity", 1.0),
    "flow_resistivity": ("flow_resistivity_pa_s_per_m2", 1.0),
    "tortuosity": ("tortuosity", 1.0),
    "viscous_characteristic_length": ("viscous_characteristic_length_m", 1e6),
    "thermal_characteristic_length": ("thermal_characteristic_length_m", 1e6),
    "frame_density": ("frame_density_kg_per_m3", 1.0),
}


def _load_material_presets() -> tuple[MaterialPreset, ...]:
    """Read the preset library (literature units) and convert it to SI; divisors keep µm values exact."""

    raw = json.loads(resources.files("blab").joinpath("material_presets.json").read_text(encoding="utf-8"))
    return tuple(
        MaterialPreset(
            id=item["id"],
            name=item["name"],
            source=f"{raw['reference']}, {item['table']}",
            parameters={key: float(item[file_key]) / divisor for file_key, (key, divisor) in _PRESET_FILE_KEYS.items()},
        )
        for item in raw["presets"]
    )


MATERIAL_PRESETS: tuple[MaterialPreset, ...] = _load_material_presets()
_PRESETS_BY_ID = {preset.id: preset for preset in MATERIAL_PRESETS}


def material_preset(preset_id: str) -> MaterialPreset | None:
    """Return the built-in Material preset with this id, or ``None`` (``"custom"`` or unknown)."""

    return _PRESETS_BY_ID.get(preset_id)


def preset_loss_model(preset_id: str, *, model: str, frame: str) -> dict[str, Any]:
    """Return the project loss model that fills every parameter of ``model``/``frame`` from a preset."""

    preset = material_preset(preset_id)
    if preset is None:
        raise ValueError(f"Unknown material preset {preset_id!r}.")
    return preset.loss_model(model=model, frame=frame)


def jcal_static_thermal_permeability(*, porosity: float, thermal_characteristic_length_m: float) -> float:
    """Return k0' = phi * Lambda'^2 / 8, the value for which JCAL equals JCA (book Eqs. 5.54/5.55)."""

    return porosity * thermal_characteristic_length_m**2 / 8.0


class MaterialError(ValueError):
    """A region loss model that does not describe a valid Material."""

    def __init__(self, issues: tuple[str, ...]) -> None:
        super().__init__(" ".join(issues))
        self.issues = issues


def region_material(loss_model: Mapping[str, Any] | None, *, region_id: str, bounded: bool) -> Material:
    """Normalize a region loss model into a Material or raise every validation issue.

    ``bounded`` is whether the region is bounded air, the only kind that may be lossy or porous.
    """

    owner = f"Region '{region_id}'"
    loss_model = loss_model or {}
    model = loss_model.get(REGION_MATERIAL_MODEL_KEY, MATERIAL_MODEL_AIR)
    if not isinstance(model, str) or model not in REGION_MATERIAL_MODELS:
        raise MaterialError(
            (
                f"{owner} uses unsupported material model {model!r}; expected one of: "
                + ", ".join(sorted(REGION_MATERIAL_MODELS))
                + ".",
            )
        )
    if model in POROUS_MATERIAL_MODELS:
        return _porous_material(loss_model, model, owner=owner, bounded=bounded)
    issues: list[str] = []
    unknown = sorted(set(loss_model) - {REGION_MATERIAL_MODEL_KEY, *REGION_MATERIAL_MODELS[model]})
    if unknown:
        issues.append(f"{owner} uses unsupported loss parameters: " + ", ".join(unknown) + ".")
    bulk_loss_factor = _bulk_loss_factor(loss_model.get(REGION_BULK_LOSS_FACTOR_KEY, 0.0))
    if bulk_loss_factor is None:
        issues.append(f"{owner} FEM bulk loss factor must be a finite number between 0 and 1.")
    elif bulk_loss_factor != 0.0 and not bounded:
        issues.append(f"{owner} FEM bulk loss requires a bounded-air region.")
    if issues:
        raise MaterialError(tuple(issues))
    return Material(model=model, bulk_loss_factor=bulk_loss_factor)


def _porous_material(loss_model: Mapping[str, Any], model: str, *, owner: str, bounded: bool) -> Material:
    issues: list[str] = []
    if not bounded:
        issues.append(f"{owner} porous material {model!r} requires a bounded-air region.")
    frame = loss_model.get(REGION_MATERIAL_FRAME_KEY)
    if not isinstance(frame, str) or frame not in REGION_MATERIAL_FRAMES:
        issues.append(
            f"{owner} uses unsupported {model.upper()} frame {frame!r}; expected one of: "
            + ", ".join(sorted(REGION_MATERIAL_FRAMES))
            + "."
        )
        frame_keys: tuple[str, ...] = ()
    else:
        frame_keys = REGION_MATERIAL_FRAMES[frame]
    keys = (*REGION_MATERIAL_MODELS[model], *frame_keys)
    if REGION_BULK_LOSS_FACTOR_KEY in loss_model:
        issues.append(f"{owner} FEM bulk loss factor is only available for Air, not {model.upper()}.")
    preset_id = loss_model.get(REGION_MATERIAL_PRESET_KEY, MATERIAL_PRESET_CUSTOM)
    if not isinstance(preset_id, str):
        issues.append(f"{owner} material preset must be a preset name or '{MATERIAL_PRESET_CUSTOM}'.")
    known = {
        REGION_MATERIAL_MODEL_KEY,
        REGION_MATERIAL_FRAME_KEY,
        REGION_MATERIAL_PRESET_KEY,
        REGION_BULK_LOSS_FACTOR_KEY,
        *keys,
    }
    unknown = sorted(set(loss_model) - known)
    if unknown:
        issues.append(f"{owner} uses unsupported {model.upper()} parameters: " + ", ".join(unknown) + ".")
    parameters: list[tuple[str, float]] = []
    for key in keys:
        spec = POROUS_MATERIAL_PARAMETERS[key]
        if key not in loss_model:
            issues.append(f"{owner} {model.upper()} material is missing {spec.label} ({key}).")
            continue
        value = _finite_number(loss_model[key])
        if value is None or not spec.accepts(value):
            issues.append(f"{owner} {model.upper()} {spec.label} ({key}) must be a finite number {spec.describe()}.")
            continue
        parameters.append((key, value))
    if issues:
        raise MaterialError(tuple(issues))
    preset = material_preset(preset_id)
    if preset is None or not preset.matches(model, frame, dict(parameters)):
        preset_id = MATERIAL_PRESET_CUSTOM
    return Material(model=model, frame=frame, parameters=tuple(parameters), preset=preset_id)


def region_material_warnings(material: Material, *, region_id: str) -> tuple[ValidationWarning, ...]:
    """Return the findings that make a valid Material suspicious without rejecting it."""

    parameters = dict(material.parameters)
    viscous = parameters.get("viscous_characteristic_length_m")
    thermal = parameters.get("thermal_characteristic_length_m")
    if viscous is None or thermal is None or thermal >= viscous:
        return ()
    return (
        ValidationWarning(
            code="porous_thermal_length_below_viscous_length",
            region_id=region_id,
            message=f"Region '{region_id}' {material.model.upper()} thermal characteristic length "
            f"({thermal * 1e6:g} um) is smaller than its viscous characteristic length ({viscous * 1e6:g} um); "
            "measured data usually has thermal >= viscous. Check the values.",
        ),
    )


def _finite_number(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def _bulk_loss_factor(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None


def region_bulk_loss_factor(loss_model: Mapping[str, Any] | None) -> float:
    """Return and validate a bounded-region bulk loss factor."""

    value = _bulk_loss_factor(0.0 if not loss_model else loss_model.get(REGION_BULK_LOSS_FACTOR_KEY, 0.0))
    if value is None:
        raise ValueError("Region FEM bulk loss factor must be a finite number between 0 and 1.")
    return value


def wall_impedance_parameters(parameters: Mapping[str, Any] | None) -> dict[str, float | str] | None:
    """Return a normalized Miki wall-lining description, or ``None``."""

    if not parameters or WALL_IMPEDANCE_KEY not in parameters:
        return None
    raw = parameters[WALL_IMPEDANCE_KEY]
    if not isinstance(raw, Mapping):
        raise ValueError("Wall impedance parameters must be an object.")
    model = str(raw.get("model", WALL_IMPEDANCE_MODEL_MIKI)).strip().lower()
    if model != WALL_IMPEDANCE_MODEL_MIKI:
        raise ValueError(f"Unsupported wall impedance model {model!r}; expected 'miki'.")
    try:
        thickness_m = float(raw.get("thickness_m", DEFAULT_WALL_LINING_THICKNESS_M))
        flow_resistivity = float(
            raw.get(
                "flow_resistivity_pa_s_per_m2",
                DEFAULT_WALL_LINING_FLOW_RESISTIVITY_PA_S_PER_M2,
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Wall lining thickness and airflow resistivity must be finite positive numbers.") from exc
    if not math.isfinite(thickness_m) or thickness_m <= 0.0:
        raise ValueError("Wall lining thickness must be a finite positive number.")
    if not math.isfinite(flow_resistivity) or flow_resistivity <= 0.0:
        raise ValueError("Wall lining airflow resistivity must be a finite positive number.")
    return {
        "model": WALL_IMPEDANCE_MODEL_MIKI,
        "thickness_m": thickness_m,
        "flow_resistivity_pa_s_per_m2": flow_resistivity,
    }


def miki_wall_impedance_parameters(
    *,
    thickness_m: float = DEFAULT_WALL_LINING_THICKNESS_M,
    flow_resistivity_pa_s_per_m2: float = DEFAULT_WALL_LINING_FLOW_RESISTIVITY_PA_S_PER_M2,
) -> dict[str, dict[str, float | str]]:
    """Build normalized boundary parameters for a rigid-backed Miki layer."""

    normalized = wall_impedance_parameters(
        {
            WALL_IMPEDANCE_KEY: {
                "model": WALL_IMPEDANCE_MODEL_MIKI,
                "thickness_m": thickness_m,
                "flow_resistivity_pa_s_per_m2": flow_resistivity_pa_s_per_m2,
            }
        }
    )
    assert normalized is not None
    return {WALL_IMPEDANCE_KEY: normalized}
