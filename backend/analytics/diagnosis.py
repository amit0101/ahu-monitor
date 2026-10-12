"""
analytics/diagnosis.py — Fault signature matching via cosine similarity.

Each fault mode has a known "signature" — a vector of expected signal deviations
(in normalised σ units). An incoming multi-signal snapshot is compared against
all signatures; the best match above a confidence threshold is reported.

This mirrors how real CMMS/BMS fault diagnostic rules work, but replaces
hand-coded if/else chains with a vectorised similarity calculation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from twin.model import FaultMode, SensorKind

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Fault signatures (expected normalised deviations per signal type)
#
# +2.0 = "this signal is expected to be ~2σ above baseline"
# -1.5 = "this signal is expected to be ~1.5σ below baseline"
#  0.0 = "this signal is unaffected by this fault" (neutral / key differentiator)
# ─────────────────────────────────────────────────────────────────────────────

# Signal dimension order used in all vectors (must be consistent)
SIGNAL_DIM_ORDER = [
    SensorKind.VIBRATION,       # 0
    SensorKind.ACOUSTIC,        # 1
    SensorKind.TEMPERATURE,     # 2 — bearing temperature
    SensorKind.CURRENT,         # 3
    SensorKind.PRESSURE_DIFF,   # 4 — filter ΔP
    SensorKind.AIRFLOW,         # 5
    SensorKind.SPEED,           # 6
    SensorKind.POWER,           # 7 — electrical power
]

# Maps FaultMode → expected normalised deviation vector (same dimension order)
FAULT_SIGNATURES: dict[FaultMode, np.ndarray] = {
    FaultMode.BEARING_WEAR: np.array([
        +3.0,   # vibration: strong rise (exponential bearing wear curve)
        +1.5,   # acoustic:  broadband noise increase
        +2.5,   # bearing_temp: friction heating (key indicator)
        +0.8,   # current:   slightly elevated (higher mechanical resistance)
        0.0,    # filter_dp: unaffected (key differentiator vs filter fault)
        0.0,    # airflow:   unaffected
        0.0,    # speed:     unaffected
        0.0,    # power:     negligible
    ]),
    FaultMode.BELT_SLIPPAGE: np.array([
        +1.5,   # vibration:  elevated (misalignment harmonics)
        +2.5,   # acoustic:   high — distinctive squealing tone
        +0.5,   # bearing_temp: mild secondary heating
        -1.0,   # current:   lower during slip phase (reduced load transfer)
        0.0,    # filter_dp: unaffected
        -1.0,   # airflow:   reduced fan speed → less airflow
        -1.5,   # speed:     lower RPM (slip)
        0.0,    # power:     mixed (slip wastes energy, lower load)
    ]),
    FaultMode.COIL_FOULING: np.array([
        0.0,    # vibration:  unaffected (key differentiator)
        0.0,    # acoustic:   unaffected
        +2.0,   # discharge_temp: poor heat transfer → higher supply air temp
        +1.2,   # current:   longer run time → elevated power
        0.0,    # filter_dp: unaffected
        0.0,    # airflow:   unaffected
        0.0,    # speed:     unaffected
        +1.5,   # power:     system compensates → elevated consumption
    ]),
    FaultMode.FILTER_CLOGGING: np.array([
        0.0,    # vibration:  unaffected (key differentiator vs bearing fault)
        0.0,    # acoustic:   marginally elevated but below threshold
        0.0,    # bearing_temp: unaffected
        +1.0,   # current:   fan working harder against higher static pressure
        +3.0,   # filter_dp: strong rise (primary indicator, sub-exponential)
        -2.0,   # airflow:   reduced flow volume (secondary indicator)
        0.0,    # speed:     RPM unaffected (fan tries to maintain setpoint)
        0.0,    # power:     slight rise but not a primary indicator
    ]),
    FaultMode.DAMPER_FAILURE: np.array([
        0.0,    # vibration:  mechanical damper — low vibration signature
        +0.5,   # acoustic:   servo hunting / chatter
        +1.5,   # temp:       wrong air mix → discharge temp deviation
        +1.5,   # current:   energy waste (overcooling/overheating)
        0.0,    # filter_dp: unaffected
        +0.5,   # airflow:   variable (depends on stuck position)
        0.0,    # speed:     unaffected
        +1.5,   # power:     energy waste from wrong OA/RA mix
    ]),
}


@dataclass
class DiagnosisResult:
    fault_mode: FaultMode
    confidence: float        # 0.0 → 1.0 (cosine similarity normalised)
    is_diagnosed: bool       # True only if confidence > threshold
    signal_deviations: dict[SensorKind, float]  # for UI / debugging


class FaultDiagnoser:
    """
    Compares observed multi-signal deviations against known fault signatures
    using cosine similarity.

    Inputs: {SensorKind → normalised deviation (z-score)}
    Output: DiagnosisResult with best-matching fault and confidence score
    """

    # Minimum confidence to report a diagnosis
    CONFIDENCE_THRESHOLD: float = 0.45

    def diagnose(
        self, signal_deviations: dict[SensorKind, float]
    ) -> DiagnosisResult:
        """
        Args:
            signal_deviations: sensor kind → (observed - baseline_mean) / baseline_std

        Returns:
            DiagnosisResult with the best-matching FaultMode and confidence.
        """
        # Build observed vector using the fixed dimension order
        obs = np.array([
            signal_deviations.get(kind, 0.0)
            for kind in SIGNAL_DIM_ORDER
        ])

        best_fault = FaultMode.NONE
        best_sim = 0.0

        obs_norm = np.linalg.norm(obs)
        if obs_norm < 0.1:
            # Near-zero observation vector → no fault
            return DiagnosisResult(
                fault_mode=FaultMode.NONE,
                confidence=0.0,
                is_diagnosed=False,
                signal_deviations=signal_deviations,
            )

        for fault, sig in FAULT_SIGNATURES.items():
            sig_norm = np.linalg.norm(sig)
            if sig_norm < 1e-9:
                continue
            cosine_sim = float(np.dot(obs, sig) / (obs_norm * sig_norm))
            # Clamp to [0, 1] — negative similarity means anti-correlated
            cosine_sim = max(0.0, cosine_sim)

            if cosine_sim > best_sim:
                best_sim = cosine_sim
                best_fault = fault

        # Normalise to [0, 1] — cosine_sim is already [0,1] after clamping
        confidence = float(np.clip(best_sim, 0.0, 1.0))

        return DiagnosisResult(
            fault_mode=best_fault if confidence >= self.CONFIDENCE_THRESHOLD else FaultMode.NONE,
            confidence=confidence,
            is_diagnosed=confidence >= self.CONFIDENCE_THRESHOLD,
            signal_deviations=signal_deviations,
        )
