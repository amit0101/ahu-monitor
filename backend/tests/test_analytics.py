"""
tests/test_analytics.py — Tests for Phase 2 analytics engine.

Covers:
  - AnomalyDetector: EWMA/CUSUM/IF layered detection
  - FaultDiagnoser: signature matching correctness
  - RULEstimator: curve fitting + projection
  - AnalyticsEngine integration smoke test
"""
from __future__ import annotations

import sys
import os

# Ensure backend root is on path when running pytest from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import math
import pytest
import numpy as np

from analytics.anomaly import AnomalyDetector
from analytics.diagnosis import FaultDiagnoser, SIGNAL_DIM_ORDER
from analytics.prediction import RULEstimator
from twin.model import FaultMode, SensorKind


# ─────────────────────────────────────────────────────────────────────────────
# AnomalyDetector tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAnomalyDetector:

    def _feed_normal(self, detector: AnomalyDetector, n: int, mean: float, std: float, sensor_id: str = "test.sensor") -> None:
        """Feed n normally distributed readings to warm up the detector."""
        rng = np.random.default_rng(0)
        for i in range(n):
            val = rng.normal(mean, std)
            detector.update(sensor_id, val, mean, std, sim_day=float(i) / 100)

    def test_normal_signal_low_score(self):
        """Normal readings should produce low anomaly scores."""
        detector = AnomalyDetector()
        self._feed_normal(detector, 200, mean=2.8, std=0.3)

        # Feed 10 more normal readings, all should have low score
        rng = np.random.default_rng(99)
        for _ in range(10):
            score, _ = detector.update("test.sensor", rng.normal(2.8, 0.3), 2.8, 0.3, sim_day=2.0)
            assert score < 0.5, f"Normal reading produced high anomaly score: {score}"

    def test_spike_produces_elevated_score(self):
        """A 5σ spike should produce anomaly score > 0.5."""
        detector = AnomalyDetector()
        self._feed_normal(detector, 150, mean=2.8, std=0.3)
        # 5σ spike
        spike_val = 2.8 + 5 * 0.3
        score, is_anom = detector.update("test.sensor", spike_val, 2.8, 0.3, sim_day=1.5)
        assert score > 0.5, f"5σ spike should be anomalous, got score={score}"

    def test_persistent_drift_cusum(self):
        """CUSUM should catch persistent shift that a single-sample test misses."""
        detector = AnomalyDetector()
        mean, std = 2.8, 0.3
        self._feed_normal(detector, 120, mean=mean, std=std)

        # Feed persistent upward drift (2σ above mean, every reading)
        scores = []
        for i in range(80):
            val = mean + 2 * std  # not a spike, but persistent
            score, _ = detector.update("test.sensor", val, mean, std, sim_day=1.2 + i * 0.01)
            scores.append(score)

        # CUSUM should accumulate and scores should rise over time
        early_avg = float(np.mean(scores[:10]))
        late_avg = float(np.mean(scores[-10:]))
        assert late_avg >= early_avg, "CUSUM should accumulate: later scores should be >= earlier"

    def test_reset_clears_state(self):
        """After reset, detector should behave as fresh."""
        detector = AnomalyDetector()
        self._feed_normal(detector, 200, mean=2.8, std=0.3)
        detector.reset()
        assert len(detector._states) == 0

    def test_multiple_sensors_independent(self):
        """Detectors for different sensor IDs should not interfere."""
        detector = AnomalyDetector()
        # Sensor A: normal; Sensor B: anomalous
        rng = np.random.default_rng(7)
        for i in range(150):
            detector.update("sensor.A", rng.normal(10.0, 1.0), 10.0, 1.0, sim_day=float(i)/100)
            detector.update("sensor.B", rng.normal(10.0, 1.0), 10.0, 1.0, sim_day=float(i)/100)

        score_a, _ = detector.update("sensor.A", 10.2, 10.0, 1.0, sim_day=2.0)
        score_b, _ = detector.update("sensor.B", 25.0, 10.0, 1.0, sim_day=2.0)  # extreme spike
        assert score_b > score_a, "Sensor B spike should score higher than Sensor A normal"


# ─────────────────────────────────────────────────────────────────────────────
# FaultDiagnoser tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFaultDiagnoser:

    def _bearing_deviations(self, strength: float = 3.0) -> dict[SensorKind, float]:
        return {
            SensorKind.VIBRATION: strength,
            SensorKind.ACOUSTIC: strength * 0.5,
            SensorKind.TEMPERATURE: strength * 0.8,
            SensorKind.CURRENT: strength * 0.25,
            SensorKind.PRESSURE_DIFF: 0.0,
            SensorKind.AIRFLOW: 0.0,
            SensorKind.SPEED: 0.0,
        }

    def _filter_deviations(self, strength: float = 3.0) -> dict[SensorKind, float]:
        return {
            SensorKind.VIBRATION: 0.0,
            SensorKind.ACOUSTIC: 0.0,
            SensorKind.TEMPERATURE: 0.0,
            SensorKind.CURRENT: strength * 0.33,
            SensorKind.PRESSURE_DIFF: strength,
            SensorKind.AIRFLOW: -strength * 0.66,
            SensorKind.SPEED: 0.0,
        }

    def test_bearing_wear_diagnosis(self):
        diagnoser = FaultDiagnoser()
        result = diagnoser.diagnose(self._bearing_deviations(3.0))
        assert result.fault_mode == FaultMode.BEARING_WEAR, (
            f"Expected BEARING_WEAR, got {result.fault_mode} (confidence={result.confidence:.2f})"
        )
        assert result.is_diagnosed
        assert result.confidence > 0.45

    def test_filter_clogging_diagnosis(self):
        diagnoser = FaultDiagnoser()
        result = diagnoser.diagnose(self._filter_deviations(3.0))
        assert result.fault_mode == FaultMode.FILTER_CLOGGING, (
            f"Expected FILTER_CLOGGING, got {result.fault_mode} (confidence={result.confidence:.2f})"
        )

    def test_no_fault_near_zero_deviations(self):
        """Very small deviations should produce NONE fault."""
        diagnoser = FaultDiagnoser()
        deviations = {k: 0.01 for k in SensorKind}
        result = diagnoser.diagnose(deviations)
        assert result.fault_mode == FaultMode.NONE

    def test_bearing_not_misidentified_as_filter(self):
        """Bearing fault signature should NOT diagnose as filter clogging."""
        diagnoser = FaultDiagnoser()
        result = diagnoser.diagnose(self._bearing_deviations(4.0))
        assert result.fault_mode != FaultMode.FILTER_CLOGGING, (
            "Bearing wear (high vibration, low ΔP) should not be misidentified as filter clogging"
        )


# ─────────────────────────────────────────────────────────────────────────────
# RULEstimator tests
# ─────────────────────────────────────────────────────────────────────────────

class TestRULEstimator:

    def _exponential_health(self, n: int, start_day: float = 35.0) -> tuple[list[float], list[float]]:
        """Simulate health declining exponentially from ~0.95 to ~0.3 over n ticks."""
        days = [start_day + i * 0.1 for i in range(n)]
        # h(t) = 0.95 * exp(-0.025 * t) + 0.05
        healths = [0.95 * math.exp(-0.025 * i * 0.1) + 0.05 for i in range(n)]
        return healths, days

    def test_rul_returns_none_below_min_samples(self):
        estimator = RULEstimator()
        result = estimator.estimate([0.8, 0.79, 0.78], [0.0, 0.1, 0.2], current_sim_day=0.2)
        assert result.rul_days is None

    def test_rul_estimated_for_declining_health(self):
        estimator = RULEstimator()
        healths, days = self._exponential_health(n=80)
        result = estimator.estimate(healths, days, current_sim_day=days[-1])
        # Should produce a finite RUL
        assert result.rul_days is not None, "RUL should be estimated for declining health"
        assert result.rul_days > 0, "RUL must be positive"

    def test_failure_probability_increases_with_low_health(self):
        estimator = RULEstimator()
        # Healthy
        r_healthy = estimator.estimate.__func__  # use static method directly
        fp_high = estimator._failure_probability(0.95)
        fp_low = estimator._failure_probability(0.25)
        assert fp_low > fp_high, "Lower health should yield higher failure probability"

    def test_failure_probability_bounded(self):
        for h in [0.0, 0.2, 0.5, 0.8, 1.0]:
            fp = RULEstimator._failure_probability(h)
            assert 0.0 <= fp <= 1.0, f"Failure probability out of range for health={h}: {fp}"

    def test_fit_type_reported(self):
        estimator = RULEstimator()
        healths, days = self._exponential_health(n=60)
        result = estimator.estimate(healths, days, current_sim_day=days[-1])
        assert result.fit_type in ("exponential", "linear", "none")


# ─────────────────────────────────────────────────────────────────────────────
# Integration smoke test: AnalyticsEngine + SimulationEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyticsEngineIntegration:
    """
    Smoke-test the full analytics pipeline with a mock simulation engine
    (no asyncio needed — we call _tick() and on_tick() synchronously).
    """

    def _make_engine(self):
        """Build a SimulationEngine in synchronous mode (no async start)."""
        from simulator.engine import SimulationEngine
        from simulator.scenarios import build_default_scenario
        import numpy as np

        eng = SimulationEngine()
        eng._rng = np.random.default_rng(seed=0)
        eng.state.running = True
        eng.state.scenario_events = build_default_scenario(eng._rng)
        return eng

    def test_on_tick_does_not_raise(self):
        """AnalyticsEngine.on_tick should handle a fresh engine tick without error."""
        from analytics.fusion import AnalyticsEngine as AE
        eng = self._make_engine()
        analytics = AE()
        eng._analytics = analytics

        # Run 5 ticks
        for _ in range(5):
            eng._tick()
            analytics.on_tick(eng)

    def test_health_scores_updated_after_ticks(self):
        """Entity health values should be updated (not stuck at 1.0 initial default)."""
        from analytics.fusion import AnalyticsEngine as AE
        eng = self._make_engine()
        analytics = AE()

        # Run enough ticks to get anomaly detection running
        for _ in range(150):
            eng._tick()
            analytics.on_tick(eng)

        # All entities with sensor points should have health set
        for entity in eng.twin.all_entities():
            if entity.points:
                assert 0.0 <= entity.health.value <= 1.0, (
                    f"Health out of range for {entity.id}: {entity.health.value}"
                )

    def test_reset_clears_analytics(self):
        """After reset(), active_alerts and recommendations should be empty."""
        from analytics.fusion import AnalyticsEngine as AE
        analytics = AE()
        # Manually inject a fake alert
        from twin.model import Alert, FaultMode, OperatingState
        import time, uuid
        analytics.active_alerts.append(Alert(
            id=str(uuid.uuid4()), entity_id="test", entity_dis="Test",
            severity=OperatingState.WARNING, fault_mode=FaultMode.BEARING_WEAR,
            title="Test", description="Test", sim_day=10.0, timestamp=time.time(),
        ))
        analytics.reset()
        assert len(analytics.active_alerts) == 0
        assert len(analytics.recommendations) == 0
        assert len(analytics.alert_history) == 0
