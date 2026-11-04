"""Physical acoustic-loss parameter helpers shared by the UI and solvers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

REGION_BULK_LOSS_FACTOR_KEY = "bulk_loss_factor"
REGION_MATERIAL_MODEL_KEY = "model"
REGION_MATERIAL_FRAME_KEY = "frame"
MATERIAL_MODEL_AIR = "air"
MATERIAL_MODEL_JCA = "jca"
MATERIAL_FRAME_RIGID = "rigid"


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
# Further models (JCAL) and frames (limp) are added to these tables.
POROUS_MATERIAL_PARAMETERS: dict[str, MaterialParameter] = {
    "porosity": MaterialParameter("porosity", 0.0, high=1.0),
    "flow_resistivity_pa_s_per_m2": MaterialParameter("flow resistivity", 0.0),
    "tortuosity": MaterialParameter("tortuosity", 1.0, low_inclusive=True),
    "viscous_characteristic_length_m": MaterialParameter("viscous characteristic length", 0.0),
    "thermal_characteristic_length_m": MaterialParameter("thermal characteristic length", 0.0),
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
}
REGION_MATERIAL_FRAMES: dict[str, tuple[str, ...]] = {MATERIAL_FRAME_RIGID: ()}
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

    @property
    def is_porous(self) -> bool:
        return self.model in POROUS_MATERIAL_MODELS

    def to_loss_model(self) -> dict[str, Any]:
        """Return the normalized region ``loss_model`` (explicit model, SI floats)."""

        if not self.is_porous:
            return {REGION_MATERIAL_MODEL_KEY: self.model, REGION_BULK_LOSS_FACTOR_KEY: self.bulk_loss_factor}
        return {REGION_MATERIAL_MODEL_KEY: self.model, REGION_MATERIAL_FRAME_KEY: self.frame, **dict(self.parameters)}


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
    known = {REGION_MATERIAL_MODEL_KEY, REGION_MATERIAL_FRAME_KEY, REGION_BULK_LOSS_FACTOR_KEY, *keys}
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
    return Material(model=model, frame=frame, parameters=tuple(parameters))


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
