"""
analytics/anomaly.py — Three-layer anomaly detection for individual sensor signals.

Layers (run in order, combined into a single anomaly score):
  1. EWMA residual — catches slow monotonic drift that static thresholds miss.
  2. CUSUM — detects persistent mean shifts (not just transient spikes).
  3. Isolation Forest — multivariate; trained on clean baseline window.

Each sensor maintains its own DetectorState so we can track EWMA and CUSUM
per sensor without shared mutable global state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Per-sensor state (kept alive across ticks by the AnalyticsEngine)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DetectorState:
    """Mutable state for one sensor's detectors."""
    sensor_id: str

    # EWMA baseline (updated every tick)
    ewma: Optional[float] = None            # None until first reading

    # CUSUM accumulators (two-sided: upper & lower)
    cusum_pos: float = 0.0                  # Positive drift accumulator
    cusum_neg: float = 0.0                  # Negative drift accumulator

    # Isolation Forest (trained once, reused thereafter)
    _iso_forest: Optional[IsolationForest] = field(default=None, repr=False)
    _iso_trained: bool = False
    _training_buffer: list[float] = field(default_factory=list, repr=False)

    # How many sigma above baseline before CUSUM triggers
    cusum_slack_sigma: float = 1.0          # k — the allowable slack

    # Estimated baseline std (updated from training buffer)
    estimated_std: float = 1.0

    # IF score calibration: typical score for an inlier (used for normalisation)
    _iso_inlier_score: float = -0.1         # Default; overwritten after training


class AnomalyDetector:
    """
    Manages per-sensor DetectorState instances and runs the three detection layers.

    Usage (called once per tick per sensor):
        score, is_anomalous = detector.update(sensor_id, value, baseline_mean, baseline_std)
    """

    # Minimum samples before we train Isolation Forest
    MIN_TRAINING_SAMPLES: int = 100
    # Fraction of EWMA residual that triggers anomaly (in baseline σ)
    EWMA_ALERT_SIGMA: float = 3.0
    # CUSUM threshold (decision interval h)
    CUSUM_THRESHOLD_SIGMA: float = 5.0

    def __init__(self) -> None:
        self._states: dict[str, DetectorState] = {}
        self._alpha = settings.ewma_alpha
        self._contamination = settings.isolation_forest_contamination

    def get_state(self, sensor_id: str) -> DetectorState:
        if sensor_id not in self._states:
            self._states[sensor_id] = DetectorState(sensor_id=sensor_id)
        return self._states[sensor_id]

    # ── Public entry point ────────────────────────────────────────────────────

    def update(
        self,
        sensor_id: str,
        value: float,
        baseline_mean: float,
        baseline_std: float,
        sim_day: float,
        fast_forwarding: bool = False,
    ) -> tuple[float, bool]:
        """
        Process one sensor reading.

        Returns:
            (anomaly_score, is_anomalous)
            anomaly_score: 0.0 (nominal) → 1.0 (maximally anomalous)
        """
        state = self.get_state(sensor_id)

        # Use baseline_std as fallback until we have enough training data
        effective_std = max(baseline_std, 1e-6)

        # ── Layer 1: EWMA residual ─────────────────────────────────────────────
        if state.ewma is None:
            state.ewma = value
        ewma_score = self._ewma_score(state, value, effective_std)

        # ── Layer 2: CUSUM ─────────────────────────────────────────────────────
        cusum_score = self._cusum_score(state, value, baseline_mean, effective_std)

        # ── Layer 3: Isolation Forest (only after training window) ────────────
        # During fast-forward (pre-roll) we skip the expensive IF scoring —
        # the buffer still accumulates training data, but score_samples is not
        # called, which makes 80-day pre-rolls ~20× faster.
        iso_score = 0.0 if fast_forwarding else self._iso_score(state, value, sim_day)

        # ── Combine: max with a small blend of the others ─────────────────────
        combined = float(np.clip(
            max(ewma_score, cusum_score) * 0.7 + iso_score * 0.3,
            0.0,
            1.0,
        ))
        is_anomalous = combined > 0.5

        return combined, is_anomalous

    # ── Layer implementations ─────────────────────────────────────────────────

    def _ewma_score(self, state: DetectorState, value: float, std: float) -> float:
        """Slow-adapting EWMA: score = |residual| / (σ × alert_sigma)."""
        α = self._alpha
        state.ewma = α * value + (1 - α) * state.ewma  # type: ignore[operator]
        residual = abs(value - state.ewma)
        score = residual / (std * self.EWMA_ALERT_SIGMA)
        return float(np.clip(score, 0.0, 1.0))

    def _cusum_score(
        self, state: DetectorState, value: float, mean: float, std: float
    ) -> float:
        """
        Two-sided CUSUM for persistent mean shift detection.
        k = slack = 1σ; h = threshold = 5σ.
        Score = max(cusum_pos, abs(cusum_neg)) / h
        """
        k = state.cusum_slack_sigma * std
        h = self.CUSUM_THRESHOLD_SIGMA * std

        deviation = value - mean
        state.cusum_pos = max(0.0, state.cusum_pos + deviation - k)
        state.cusum_neg = min(0.0, state.cusum_neg + deviation + k)

        peak = max(state.cusum_pos, abs(state.cusum_neg))
        score = peak / (h if h > 0 else 1.0)
        return float(np.clip(score, 0.0, 1.0))

    def _iso_score(self, state: DetectorState, value: float, sim_day: float) -> float:
        """
        Isolation Forest anomaly score.
        Returns 0.0 until MIN_TRAINING_SAMPLES collected.
        Trains once on first MIN_TRAINING_SAMPLES, then scores each reading.
        """
        state._training_buffer.append(value)

        if not state._iso_trained:
            if len(state._training_buffer) >= self.MIN_TRAINING_SAMPLES:
                self._train_isolation_forest(state)
            return 0.0  # No score yet — assume normal during training phase

        # sklearn IF score_samples: higher (less negative) = more normal
        # After training, _iso_inlier_score is the median training score.
        # We map: inlier_score → 0.0, very anomalous (inlier − 3×spread) → 1.0
        arr = np.array([[value]])
        raw = state._iso_forest.score_samples(arr)[0]  # type: ignore[union-attr]
        # normalise relative to the inlier baseline
        spread = max(abs(state._iso_inlier_score) * 0.5, 0.01)
        normalized = float(np.clip((state._iso_inlier_score - raw) / (spread * 3.0), 0.0, 1.0))
        return normalized

    def _train_isolation_forest(self, state: DetectorState) -> None:
        """Fit Isolation Forest on buffered training data."""
        try:
            X = np.array(state._training_buffer).reshape(-1, 1)
            state.estimated_std = float(np.std(X))
            state._iso_forest = IsolationForest(
                contamination=self._contamination,
                n_estimators=50,
                random_state=42,
                n_jobs=1,    # single worker: avoids fork/OOM overhead in cloud containers
            )
            state._iso_forest.fit(X)
            # Calibrate: record median score on training data (the "normal" baseline)
            train_scores = state._iso_forest.score_samples(X)
            state._iso_inlier_score = float(np.median(train_scores))
            state._iso_trained = True
            logger.debug(
                "IF trained for %s on %d samples (σ=%.3f, inlier_score=%.3f)",
                state.sensor_id,
                len(state._training_buffer),
                state.estimated_std,
                state._iso_inlier_score,
            )
        except Exception as exc:
            logger.warning("IF training failed for %s: %s", state.sensor_id, exc)

    def reset(self) -> None:
        """Clear all detector states (used on simulation restart)."""
        self._states.clear()
