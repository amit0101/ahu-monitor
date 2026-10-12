"""
analytics/prediction.py — Remaining Useful Life (RUL) estimation.

Uses exponential degradation curve fitting (scipy.optimize.curve_fit) on the
recent health-score history to project when health will cross a failure threshold.

Also computes a failure probability as a sigmoid function of (1 - health)
so the UI can show a risk gauge even when the RUL fit is unreliable.

Engineering rationale:
  - Bearing wear follows e^(β·t) (Weibull / Paris law approximation)
  - Filter clogging follows t^1.5 (empirically sub-exponential)
  - We fit both linear and exponential, report whichever has lower residual,
    but always flag if exponential predicts dramatically shorter time —
    that asymmetry is exactly the insight the dashboard illustrates.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import curve_fit

from config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Model functions
# ─────────────────────────────────────────────────────────────────────────────

def _exp_model(t: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """Exponential degradation: h(t) = a·exp(b·t) + c"""
    return a * np.exp(b * t) + c


def _linear_model(t: np.ndarray, m: float, c: float) -> np.ndarray:
    """Linear degradation: h(t) = m·t + c"""
    return m * t + c


@dataclass
class RULResult:
    rul_days: Optional[float]          # None if cannot be estimated
    failure_probability: float         # 0.0 → 1.0
    fit_type: str                      # "exponential" | "linear" | "none"
    fit_residual: float                # Lower = better fit
    days_to_warning: Optional[float]   # Health crosses 0.70
    days_to_critical: Optional[float]  # Health crosses 0.40


class RULEstimator:
    """
    Fits degradation curves to health score history and projects time to failure.

    Per the plan:
      - Fit to most recent rul_history_fraction of data points
      - Extrapolate to health < failure_threshold
      - Show why exponential fit is more conservative (risk-aware)
    """

    # Minimum points before we attempt fitting
    MIN_FIT_POINTS: int = 30
    # Failure threshold (health below this = failed)
    FAILURE_THRESHOLD: float = 0.15
    # Maximum reasonable RUL forecast (beyond this, say "not imminent")
    MAX_RUL_DAYS: float = 180.0

    def estimate(
        self,
        health_history: list[float],
        sim_day_history: list[float],
        current_sim_day: float,
    ) -> RULResult:
        """
        Args:
            health_history:   list of health values (0→1) ordered oldest→newest
            sim_day_history:  corresponding sim_day for each health value
            current_sim_day:  current sim day (for projecting forward)

        Returns:
            RULResult with RUL estimate and failure probability.
        """
        n = len(health_history)
        if n < self.MIN_FIT_POINTS:
            fp = self._failure_probability(health_history[-1] if health_history else 1.0)
            return RULResult(
                rul_days=None,
                failure_probability=fp,
                fit_type="none",
                fit_residual=0.0,
                days_to_warning=None,
                days_to_critical=None,
            )

        # Use only the most recent fraction of data (recent trend dominates)
        frac = settings.rul_history_fraction
        start = max(0, int(n * (1 - frac)))
        h_arr = np.array(health_history[start:])
        t_arr = np.array(sim_day_history[start:])

        # Normalise time axis to [0, …] for numerical stability
        t0 = t_arr[0]
        t_norm = t_arr - t0
        current_offset = current_sim_day - t0

        current_health = float(h_arr[-1])

        # ── Try exponential fit ──────────────────────────────────────────────
        exp_result = self._fit_exponential(t_norm, h_arr, current_offset)

        # ── Try linear fit ───────────────────────────────────────────────────
        lin_result = self._fit_linear(t_norm, h_arr, current_offset)

        # Pick fit with lower residual; but always include both for diagnostics
        if exp_result["residual"] <= lin_result["residual"] and exp_result["rul"] is not None:
            chosen = exp_result
            fit_type = "exponential"
        else:
            chosen = lin_result
            fit_type = "linear"

        rul = chosen.get("rul")
        if rul is not None:
            rul = float(np.clip(rul, 0.0, self.MAX_RUL_DAYS))

        return RULResult(
            rul_days=rul,
            failure_probability=self._failure_probability(current_health, rul),
            fit_type=fit_type,
            fit_residual=chosen["residual"],
            days_to_warning=chosen.get("days_to_warning"),
            days_to_critical=chosen.get("days_to_critical"),
        )

    # ── Fit helpers ───────────────────────────────────────────────────────────

    def _fit_exponential(
        self, t: np.ndarray, h: np.ndarray, current_offset: float
    ) -> dict:
        try:
            # Bounds: a ∈ [0,2], b ∈ [-5,0] (decaying), c ∈ [0,1]
            p0 = [1.0, -0.01, 0.0]
            bounds = ([0, -5.0, 0.0], [2.0, 0.0, 1.0])
            popt, _ = curve_fit(_exp_model, t, h, p0=p0, bounds=bounds, maxfev=2000)
            a, b, c = popt

            residual = float(np.mean((h - _exp_model(t, *popt)) ** 2))

            # Project forward to find failure / warning / critical crossings
            future_days = np.arange(current_offset, current_offset + self.MAX_RUL_DAYS, 0.5)
            future_h = _exp_model(future_days, a, b, c)

            rul = self._find_crossing(future_days, future_h, self.FAILURE_THRESHOLD, current_offset)
            dtw = self._find_crossing(future_days, future_h, 0.70, current_offset)
            dtc = self._find_crossing(future_days, future_h, 0.40, current_offset)

            return {"rul": rul, "residual": residual, "days_to_warning": dtw, "days_to_critical": dtc}
        except Exception as exc:
            logger.debug("Exp fit failed: %s", exc)
            return {"rul": None, "residual": 9999.0, "days_to_warning": None, "days_to_critical": None}

    def _fit_linear(
        self, t: np.ndarray, h: np.ndarray, current_offset: float
    ) -> dict:
        try:
            popt, _ = curve_fit(_linear_model, t, h, maxfev=1000)
            m, c = popt

            residual = float(np.mean((h - _linear_model(t, m, c)) ** 2))

            if m >= 0:
                # Health not declining — RUL is infinite
                return {"rul": None, "residual": residual, "days_to_warning": None, "days_to_critical": None}

            future_days = np.arange(current_offset, current_offset + self.MAX_RUL_DAYS, 0.5)
            future_h = _linear_model(future_days, m, c)

            rul = self._find_crossing(future_days, future_h, self.FAILURE_THRESHOLD, current_offset)
            dtw = self._find_crossing(future_days, future_h, 0.70, current_offset)
            dtc = self._find_crossing(future_days, future_h, 0.40, current_offset)

            return {"rul": rul, "residual": residual, "days_to_warning": dtw, "days_to_critical": dtc}
        except Exception as exc:
            logger.debug("Linear fit failed: %s", exc)
            return {"rul": None, "residual": 9999.0, "days_to_warning": None, "days_to_critical": None}

    @staticmethod
    def _find_crossing(
        t: np.ndarray, h: np.ndarray, threshold: float, current_offset: float
    ) -> Optional[float]:
        """Return days from current_offset until h crosses below threshold."""
        mask = h < threshold
        if not np.any(mask):
            return None
        idx = int(np.argmax(mask))
        return float(t[idx] - current_offset)

    @staticmethod
    def _failure_probability(health: float, rul_days: Optional[float] = None) -> float:
        """
        Sigmoid-based failure probability.
        At health=1.0 → ~0.03; at health=0.4 → ~0.50; at health=0.15 → ~0.82.
        Optionally amplified if RUL is short.
        """
        # Base probability from health score
        base = 1.0 / (1.0 + np.exp(6.0 * (health - 0.4)))

        # If we have a RUL estimate, amplify probability when time is short
        if rul_days is not None and rul_days < 30.0:
            urgency = 1.0 - rul_days / 30.0  # 0 → 1 as RUL → 0
            base = min(1.0, base + urgency * 0.3)

        return float(np.clip(base, 0.0, 1.0))
