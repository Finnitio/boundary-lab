"""Physical acoustic-loss parameter helpers shared by the UI and solvers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

REGION_BULK_LOSS_FACTOR_KEY = "bulk_loss_factor"
REGION_MATERIAL_MODEL_KEY = "model"
MATERIAL_MODEL_AIR = "air"
# Region materials mirror the BEAT Engine region ``loss_model`` wire contract
# (``beat_contract.REGION_MATERIAL_MODELS``/``REGION_MATERIAL_FRAMES``): each model
# lists the keys it accepts besides ``model``. A loss model without ``model`` is
# legacy Air. Porous models and their frames are added to these tables.
REGION_MATERIAL_MODELS: dict[str, tuple[str, ...]] = {
    MATERIAL_MODEL_AIR: (REGION_BULK_LOSS_FACTOR_KEY,),
}
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
    """Normalized acoustic material of a region, keyed like the engine wire contract."""

    model: str = MATERIAL_MODEL_AIR
    bulk_loss_factor: float = 0.0


class MaterialError(ValueError):
    """A region loss model that does not describe a valid Material."""

    def __init__(self, issues: tuple[str, ...]) -> None:
        super().__init__(" ".join(issues))
        self.issues = issues


def region_material(loss_model: Mapping[str, Any] | None, *, region_id: str, bounded: bool) -> Material:
    """Normalize a region loss model into a Material or raise every validation issue.

    ``bounded`` is whether the region is bounded air, the only kind that may be lossy.
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
