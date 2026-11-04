"""Analytical porous-media references for tests, written from Allard & Atalla independently of the engine.

Book form, e^{+j omega t} (Boundary Lab's result convention). ``parameters`` is a region
``loss_model`` in the wire layout (model, frame, SI parameters), so references for further
models and frames read the same keys as the project.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Any, Mapping

# The air constants the engine uses for porous materials and thermoviscous wall losses.
DYNAMIC_VISCOSITY_PA_S = 1.84e-5
THERMAL_CONDUCTIVITY_W_PER_M_K = 0.0257
SPECIFIC_HEAT_J_PER_KG_K = 1005.0
HEAT_CAPACITY_RATIO = 1.4


@dataclass(frozen=True)
class EquivalentFluid:
    """Equivalent fluid of a porous region: rho_eq = rho/phi and K_eq = K/phi (Eqs. 5.43/5.44)."""

    density_kg_per_m3: complex
    bulk_modulus_pa: complex

    def wavenumber(self, frequency_hz: float) -> complex:
        return 2.0 * math.pi * frequency_hz * cmath.sqrt(self.density_kg_per_m3 / self.bulk_modulus_pa)

    @property
    def characteristic_impedance(self) -> complex:
        return cmath.sqrt(self.density_kg_per_m3 * self.bulk_modulus_pa)


def equivalent_fluid(
    parameters: Mapping[str, Any], frequency_hz: float, *, density_kg_per_m3: float, sound_speed_m_per_s: float
) -> EquivalentFluid:
    """Johnson density (Eqs. 5.50/5.52) and simplified Lafarge bulk modulus (Eqs. 5.51/5.53).

    JCA uses the static thermal permeability k0' = phi Lambda'^2 / 8 (Eqs. 5.54/5.55).
    """

    if parameters["model"] != "jca" or parameters["frame"] != "rigid":
        raise NotImplementedError(f"No reference for {parameters['model']} with a {parameters['frame']} frame.")
    rho0, j = density_kg_per_m3, 1j
    omega = 2.0 * math.pi * frequency_hz
    eta, gamma = DYNAMIC_VISCOSITY_PA_S, HEAT_CAPACITY_RATIO
    prandtl = eta * SPECIFIC_HEAT_J_PER_KG_K / THERMAL_CONDUCTIVITY_W_PER_M_K
    p0 = rho0 * sound_speed_m_per_s**2 / gamma
    phi = parameters["porosity"]
    sigma = parameters["flow_resistivity_pa_s_per_m2"]
    alpha = parameters["tortuosity"]
    viscous_length = parameters["viscous_characteristic_length_m"]
    thermal_length = parameters["thermal_characteristic_length_m"]
    density = (
        rho0
        * alpha
        * (
            1.0
            + sigma
            * phi
            / (j * omega * rho0 * alpha)
            * cmath.sqrt(1.0 + 4.0 * j * alpha**2 * eta * rho0 * omega / (sigma**2 * viscous_length**2 * phi**2))
        )
    )
    k0 = phi * thermal_length**2 / 8.0
    nu_thermal = eta / (rho0 * prandtl)
    alpha_thermal = 1.0 + nu_thermal * phi / (j * omega * k0) * cmath.sqrt(
        1.0 + 4.0 * j * omega * k0**2 / (nu_thermal * thermal_length**2 * phi**2)
    )
    bulk = gamma * p0 / (gamma - (gamma - 1.0) / alpha_thermal)
    return EquivalentFluid(density_kg_per_m3=density / phi, bulk_modulus_pa=bulk / phi)


def closed_tube_input_impedance(fluid: EquivalentFluid, frequency_hz: float, length_m: float) -> complex:
    """Input impedance p/u of a rigidly closed tube of length L: Z = -j Z_c cot(k_c L)."""

    return -1j * fluid.characteristic_impedance / cmath.tan(fluid.wavenumber(frequency_hz) * length_m)


def air(*, density_kg_per_m3: float, sound_speed_m_per_s: float) -> EquivalentFluid:
    """Lossless air as a fluid layer: rho0 and K = rho0 c0^2."""

    return EquivalentFluid(
        density_kg_per_m3=complex(density_kg_per_m3),
        bulk_modulus_pa=complex(density_kg_per_m3 * sound_speed_m_per_s**2),
    )


def layer_transfer_matrix(
    fluid: EquivalentFluid, frequency_hz: float, thickness_m: float
) -> tuple[tuple[complex, complex], tuple[complex, complex]]:
    """Fluid-layer transfer matrix (Ch. 11): [p, v] on the front face = T [p, v] on the back face.

    v is the normal (macroscopic) velocity pointing from the front to the back face.
    """

    kd = fluid.wavenumber(frequency_hz) * thickness_m
    zc = fluid.characteristic_impedance
    return ((cmath.cos(kd), 1j * zc * cmath.sin(kd)), (1j * cmath.sin(kd) / zc, cmath.cos(kd)))


def driven_layer_pressure(
    fluid: EquivalentFluid,
    frequency_hz: float,
    *,
    layer_length_m: float,
    position_m: float,
    termination_impedance: complex,
    input_velocity: complex,
) -> complex:
    """Pressure at ``position_m`` in a layer driven at 0 with ``input_velocity`` and terminated at
    ``layer_length_m`` by ``termination_impedance`` (p / v on the back face)."""

    (a, b), (c, d) = layer_transfer_matrix(fluid, frequency_hz, layer_length_m)
    back_velocity = input_velocity / (c * termination_impedance + d)
    (a, b), _ = layer_transfer_matrix(fluid, frequency_hz, layer_length_m - position_m)
    return (a * termination_impedance + b) * back_velocity
