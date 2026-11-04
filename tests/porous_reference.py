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

    JCAL reads the static thermal permeability k0'; JCA uses k0' = phi Lambda'^2 / 8 (Eqs. 5.54/5.55).
    A limp frame replaces the rigid-frame equivalent density by Panneton's approximation (Eq. 11.55).
    """

    if parameters["model"] not in ("jca", "jcal") or parameters["frame"] not in ("rigid", "limp"):
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
    k0 = (
        parameters["static_thermal_permeability_m2"] if parameters["model"] == "jcal" else phi * thermal_length**2 / 8.0
    )
    nu_thermal = eta / (rho0 * prandtl)
    alpha_thermal = 1.0 + nu_thermal * phi / (j * omega * k0) * cmath.sqrt(
        1.0 + 4.0 * j * omega * k0**2 / (nu_thermal * thermal_length**2 * phi**2)
    )
    bulk = gamma * p0 / (gamma - (gamma - 1.0) / alpha_thermal)
    density_eq = density / phi
    if parameters["frame"] == "limp":
        total = parameters["frame_density_kg_per_m3"] + phi * rho0
        density_eq = (total * density_eq - rho0**2) / (total + density_eq - 2.0 * rho0)
    return EquivalentFluid(density_kg_per_m3=density_eq, bulk_modulus_pa=bulk / phi)


def closed_tube_input_impedance(fluid: EquivalentFluid, frequency_hz: float, length_m: float) -> complex:
    """Input impedance p/u of a rigidly closed tube of length L: Z = -j Z_c cot(k_c L)."""

    return -1j * fluid.characteristic_impedance / cmath.tan(fluid.wavenumber(frequency_hz) * length_m)


@dataclass(frozen=True)
class SectionResponse:
    """Plane-wave response of a uniform section driven at its inlet: Z_in = p_0/v_0 and v_L/v_0."""

    input_impedance: complex
    velocity_ratio: complex


def loaded_section(fluid: EquivalentFluid, frequency_hz: float, length_m: float, load: complex) -> SectionResponse:
    """Transfer matrix of a uniform section of length L terminated by Z_L = p_L/v_L.

    [p_0, v_0] = T [p_L, v_L] with T = [[cos kL, j Z_c sin kL], [j sin kL / Z_c, cos kL]].
    """

    k, zc = fluid.wavenumber(frequency_hz), fluid.characteristic_impedance
    t11, t12 = cmath.cos(k * length_m), 1j * zc * cmath.sin(k * length_m)
    t21, t22 = 1j * cmath.sin(k * length_m) / zc, cmath.cos(k * length_m)
    return SectionResponse(
        input_impedance=(t11 * load + t12) / (t21 * load + t22),
        velocity_ratio=1.0 / (t21 * load + t22),
    )
