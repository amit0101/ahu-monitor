"""
simulator/degradation.py — Physics-based fault degradation models.

Each failure mode is implemented as a function that returns a
DegradationEffect: the multiplicative or additive deltas to apply to
each affected sensor's baseline reading.

Degradation curves are grounded in real bearing/belt/coil physics:
  FM-1 Bearing Wear:    exponential (Arrhenius-like fatigue accumulation)
  FM-2 Belt Slippage:   quadratic acceleration → sudden failure
  FM-3 Coil Fouling:    linear fouling buildup (Dittus-Boelter analogy)
  FM-4 Filter Clogging: sub-exponential ΔP rise (Darcy-Weisbach)
  FM-5 Damper Failure:  random drift → stuck position

References:
  - ISO 10816-3: Vibration severity for industrial machines
  - ASHRAE Handbook of Fundamentals (heat transfer degradation)
  - Mobley, R.K. — "Introduction to Predictive Maintenance" (fault signatures)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from twin.model import FaultMode, SensorKind


# ─────────────────────────────────────────────────────────────────────────────
# Degradation effect container
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SignalDelta:
    """
    How a fault changes one signal.

    Two modes:
    - Multiplicative: new_value = baseline * factor    (e.g. vibration ×3)
    - Additive:       new_value = baseline + offset    (e.g. temp +25°C)
    """
    sensor_kind: SensorKind
    sensor_id_fragment: str       # Substring match against full sensor ID
    factor: float = 1.0          # Multiplicative (applied first)
    offset: float = 0.0          # Additive (applied after factor)
    noise_scale: float = 1.0     # Inflate noise by this factor (degraded = noisier)


@dataclass
class DegradationEffect:
    """Output of a degradation model: all signal deltas at a given severity."""
    fault_mode: FaultMode
    severity: float                         # 0.0 (onset) → 1.0 (failure)
    signal_deltas: list[SignalDelta] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Degradation functions (one per fault mode)
# ─────────────────────────────────────────────────────────────────────────────

def bearing_wear_effect(elapsed_days: float, onset_day: float) -> DegradationEffect:
    """
    FM-1: Fan Bearing Wear (Progressive, Exponential)

    Physics: Spalling fatigue follows exponential growth once initiated.
    The vibration signature is the primary indicator; bearing temperature
    rises from friction; current increases from mechanical drag.

    Curve: degradation(t) = α × (e^(β×t) - 1)
    Parameters tuned so severity reaches ~1.0 at 60 days post-onset.
    """
    t = max(0.0, elapsed_days - onset_day)
    # Tuned so severity ≈ 1.0 at t=60d from onset (plan: "+180% over 60 days")
    alpha, beta = 0.0008, 0.130
    severity = min(1.0, alpha * (math.exp(beta * t) - 1))

    # Vibration: +180% at full severity (ISO 10816: Zone A → D)
    vib_factor = 1.0 + severity * 1.80

    # Bearing temperature: +25°C at full severity (friction heating)
    temp_offset = severity * 25.0

    # Current: +8% (increased mechanical load from degraded bearings)
    current_factor = 1.0 + severity * 0.08

    # Acoustic: +40% broadband noise increase
    acoustic_factor = 1.0 + severity * 0.40

    return DegradationEffect(
        fault_mode=FaultMode.BEARING_WEAR,
        severity=severity,
        signal_deltas=[
            SignalDelta(SensorKind.VIBRATION, "vibration",
                        factor=vib_factor, noise_scale=1.0 + severity * 2.0),
            SignalDelta(SensorKind.TEMPERATURE, "bearingTemp",
                        factor=1.0, offset=temp_offset),
            SignalDelta(SensorKind.CURRENT, "current",
                        factor=current_factor),
            SignalDelta(SensorKind.ACOUSTIC, "acoustic",
                        factor=acoustic_factor, noise_scale=1.0 + severity * 1.5),
        ],
    )


def belt_slippage_effect(elapsed_days: float, onset_day: float) -> DegradationEffect:
    """
    FM-2: Belt Wear & Slippage (Quadratic → Sudden)

    Physics: Belt wear is gradual then accelerates as surface degrades.
    Current shows characteristic 'dip then spike' as belt slips then catches.
    Fan speed drops (slip) before motor compensates and current rises.

    Curve: degradation(t) = γ × t²   (quadratic acceleration)
    """
    t = max(0.0, elapsed_days - onset_day)
    gamma = 0.0008
    severity = min(1.0, gamma * t * t)

    vib_factor = 1.0 + severity * 0.60       # Misalignment harmonics

    # Acoustic: distinctive squealing tone (sharper increase)
    acoustic_factor = 1.0 + severity * 0.25

    # Current: dip in early phase (slip), rise in late phase
    if severity < 0.5:
        current_factor = 1.0 - severity * 0.15   # Slipping → less load
    else:
        current_factor = 1.0 + (severity - 0.5) * 0.40  # Catching → high load

    # Speed: drops as belt slips
    speed_factor = 1.0 - severity * 0.10

    return DegradationEffect(
        fault_mode=FaultMode.BELT_SLIPPAGE,
        severity=severity,
        signal_deltas=[
            SignalDelta(SensorKind.VIBRATION, "vibration",
                        factor=vib_factor, noise_scale=1.0 + severity * 1.0),
            SignalDelta(SensorKind.ACOUSTIC, "acoustic",
                        factor=acoustic_factor, noise_scale=1.0 + severity * 2.0),
            SignalDelta(SensorKind.CURRENT, "current",
                        factor=current_factor),
            SignalDelta(SensorKind.SPEED, "speed",
                        factor=speed_factor),
        ],
    )


def coil_fouling_effect(elapsed_days: float, onset_day: float) -> DegradationEffect:
    """
    FM-3: Cooling Coil Fouling (Slow Linear Buildup)

    Physics: Biofilm/mineral scale deposits reduce heat transfer coefficient
    (fouling resistance Rf accumulates linearly with time per TEMA standards).
    Primary indicators are discharge air temperature deviation and reduced coil ΔT.
    Power rises as system runs longer to meet setpoint.

    Curve: degradation(t) = δ × t   (linear)
    """
    t = max(0.0, elapsed_days - onset_day)
    delta = 0.022
    severity = min(1.0, delta * t)

    # Discharge temp: +4°C above setpoint at full severity
    discharge_offset = severity * 4.0

    # Coil ΔT: drops 30% (reduced heat transfer effectiveness)
    coil_dt_factor = 1.0 - severity * 0.30

    # Power: +15% (system compensates by running longer)
    power_factor = 1.0 + severity * 0.15

    return DegradationEffect(
        fault_mode=FaultMode.COIL_FOULING,
        severity=severity,
        signal_deltas=[
            SignalDelta(SensorKind.TEMPERATURE, "dischargeTemp",
                        factor=1.0, offset=discharge_offset),
            SignalDelta(SensorKind.TEMPERATURE, "coilDeltaT",
                        factor=coil_dt_factor),
            SignalDelta(SensorKind.POWER, "power",
                        factor=power_factor),
        ],
    )


def filter_clogging_effect(elapsed_days: float, onset_day: float) -> DegradationEffect:
    """
    FM-4: Filter Clogging (Progressive Sub-Exponential)

    Physics: Particulate accumulation follows Darcy-Weisbach law where
    ΔP rise is sub-exponential as filter cake builds. Airflow drops as
    resistance increases; fan motor current rises to maintain setpoint.

    Curve: degradation(t) = ε × t^1.5   (sub-exponential)
    Service threshold: filter ΔP > 250 Pa (ASHRAE 52.2)
    """
    t = max(0.0, elapsed_days - onset_day)
    epsilon = 0.018
    severity = min(1.0, epsilon * (t ** 1.5))

    # Filter ΔP: +200% at full severity (120 Pa → 360 Pa)
    dp_factor = 1.0 + severity * 2.00

    # Airflow: -20% reduction
    airflow_factor = 1.0 - severity * 0.20

    # Current: +12% (fan works harder against increased static pressure)
    current_factor = 1.0 + severity * 0.12

    return DegradationEffect(
        fault_mode=FaultMode.FILTER_CLOGGING,
        severity=severity,
        signal_deltas=[
            SignalDelta(SensorKind.PRESSURE_DIFF, "pressureDiff",
                        factor=dp_factor, noise_scale=1.0 + severity * 0.5),
            SignalDelta(SensorKind.AIRFLOW, "airflow",
                        factor=airflow_factor),
            SignalDelta(SensorKind.CURRENT, "current",
                        factor=current_factor),
        ],
    )


def damper_failure_effect(
    elapsed_days: float,
    onset_day: float,
    rng: np.random.Generator,
) -> DegradationEffect:
    """
    FM-5: Damper Actuator Failure (Intermittent → Stuck Position)

    Physics: Actuator motor winding failure causes intermittent positioning
    errors that worsen until the damper sticks at a fixed position.
    Mixed air temperature becomes erratic (wrong OA/RA mix ratio) and
    discharge temp deviates from setpoint, increasing energy use.

    Curve: random drift amplitude grows linearly; eventually stuck
    """
    t = max(0.0, elapsed_days - onset_day)
    severity = min(1.0, t / 40.0)  # Takes ~40 days to fully fail

    # Mixed air temp: increasingly erratic deviation
    # Early: random drift ±2°C; late: biased stuck position (+8°C)
    if severity < 0.7:
        temp_offset = rng.uniform(-severity * 3.0, severity * 3.0)
    else:
        # Stuck position — consistently wrong
        temp_offset = (severity - 0.7) / 0.3 * 8.0

    # Energy: +25% from overcooling/overheating
    power_factor = 1.0 + severity * 0.25

    return DegradationEffect(
        fault_mode=FaultMode.DAMPER_FAILURE,
        severity=severity,
        signal_deltas=[
            SignalDelta(SensorKind.TEMPERATURE, "mixedAirTemp",
                        factor=1.0, offset=temp_offset,
                        noise_scale=1.0 + severity * 3.0),
            SignalDelta(SensorKind.POWER, "power",
                        factor=power_factor),
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Apply degradation to a raw baseline reading
# ─────────────────────────────────────────────────────────────────────────────

def apply_degradation(
    baseline_value: float,
    point_id: str,
    point_kind: SensorKind,
    effects: list[DegradationEffect],
    rng: np.random.Generator,
    baseline_std: float,
) -> float:
    """
    Apply all active degradation effects to a baseline reading.

    Effects are additive in severity space — concurrent faults each
    contribute their signal deltas independently.
    """
    value = baseline_value
    noise_scale = 1.0

    for effect in effects:
        for delta in effect.signal_deltas:
            # Match by kind AND id fragment (e.g. "bearingTemp" matches
            # "ahu-01.supplyFan.bearingTemp" but not "ahu-01.coolingCoil.dischargeTemp")
            if delta.sensor_kind == point_kind and delta.sensor_id_fragment in point_id:
                value = value * delta.factor + delta.offset
                noise_scale = max(noise_scale, delta.noise_scale)

    # Add scaled noise (degraded components are noisier)
    value += rng.normal(0, baseline_std * (noise_scale - 1.0)) if noise_scale > 1.0 else 0.0
    return float(value)
