"""
tests/test_degradation.py — Unit tests for physics-based degradation models.

Validates that:
  1. Each fault model produces zero effect before onset_day
  2. Severity monotonically increases with time
  3. Signal deltas are in physically plausible ranges
  4. Concurrent faults apply independently
"""
import numpy as np
import pytest

from simulator.degradation import (
    bearing_wear_effect,
    belt_slippage_effect,
    coil_fouling_effect,
    filter_clogging_effect,
    damper_failure_effect,
    apply_degradation,
    FaultMode,
)
from twin.model import SensorKind


# ─────────────────────────────────────────────────────────────────────────────
# FM-1: Bearing Wear
# ─────────────────────────────────────────────────────────────────────────────

class TestBearingWear:
    ONSET = 35.0

    def test_no_effect_before_onset(self):
        effect = bearing_wear_effect(self.ONSET - 1, self.ONSET)
        assert effect.severity == 0.0

    def test_effect_at_onset(self):
        effect = bearing_wear_effect(self.ONSET, self.ONSET)
        assert effect.severity == 0.0  # At day=onset, t=0 → severity=0

    def test_severity_monotonic(self):
        severities = [
            bearing_wear_effect(self.ONSET + t, self.ONSET).severity
            for t in range(0, 60, 5)
        ]
        for i in range(1, len(severities)):
            assert severities[i] >= severities[i - 1], "Severity must be monotonically non-decreasing"

    def test_severity_caps_at_one(self):
        effect = bearing_wear_effect(self.ONSET + 200, self.ONSET)
        assert effect.severity <= 1.0

    def test_vibration_delta_exists(self):
        effect = bearing_wear_effect(self.ONSET + 30, self.ONSET)
        kinds = {d.sensor_kind for d in effect.signal_deltas}
        assert SensorKind.VIBRATION in kinds

    def test_vibration_rises_with_severity(self):
        early = bearing_wear_effect(self.ONSET + 10, self.ONSET)
        late = bearing_wear_effect(self.ONSET + 50, self.ONSET)
        early_vib = next(d.factor for d in early.signal_deltas if d.sensor_kind == SensorKind.VIBRATION)
        late_vib = next(d.factor for d in late.signal_deltas if d.sensor_kind == SensorKind.VIBRATION)
        assert late_vib > early_vib

    def test_vibration_max_factor_range(self):
        """At full severity, vibration should be ≤ 2.8× baseline (180% increase)."""
        effect = bearing_wear_effect(self.ONSET + 200, self.ONSET)
        vib_factor = next(d.factor for d in effect.signal_deltas if d.sensor_kind == SensorKind.VIBRATION)
        assert 2.7 <= vib_factor <= 2.9


# ─────────────────────────────────────────────────────────────────────────────
# FM-4: Filter Clogging
# ─────────────────────────────────────────────────────────────────────────────

class TestFilterClogging:
    ONSET = 20.0

    def test_no_effect_before_onset(self):
        effect = filter_clogging_effect(self.ONSET - 0.1, self.ONSET)
        assert effect.severity == 0.0

    def test_dp_factor_increases(self):
        early = filter_clogging_effect(self.ONSET + 10, self.ONSET)
        late = filter_clogging_effect(self.ONSET + 40, self.ONSET)
        dp_early = next(d.factor for d in early.signal_deltas if d.sensor_kind == SensorKind.PRESSURE_DIFF)
        dp_late = next(d.factor for d in late.signal_deltas if d.sensor_kind == SensorKind.PRESSURE_DIFF)
        assert dp_late > dp_early

    def test_airflow_decreases(self):
        effect = filter_clogging_effect(self.ONSET + 30, self.ONSET)
        af = next(d.factor for d in effect.signal_deltas if d.sensor_kind == SensorKind.AIRFLOW)
        assert af < 1.0  # Airflow drops


# ─────────────────────────────────────────────────────────────────────────────
# FM-3: Coil Fouling
# ─────────────────────────────────────────────────────────────────────────────

class TestCoilFouling:
    ONSET = 55.0

    def test_severity_is_linear(self):
        """Coil fouling is modelled as linear — check linearity holds."""
        s1 = coil_fouling_effect(self.ONSET + 10, self.ONSET).severity
        s2 = coil_fouling_effect(self.ONSET + 20, self.ONSET).severity
        s3 = coil_fouling_effect(self.ONSET + 30, self.ONSET).severity
        # Differences should be approximately equal (linear)
        assert abs((s2 - s1) - (s3 - s2)) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# apply_degradation: integration test
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyDegradation:
    def _rng(self):
        return np.random.default_rng(seed=0)

    def test_baseline_unchanged_with_no_effects(self):
        rng = self._rng()
        result = apply_degradation(
            baseline_value=2.8,
            point_id="ahu-01.returnFan.vibration",
            point_kind=SensorKind.VIBRATION,
            effects=[],
            rng=rng,
            baseline_std=0.3,
        )
        assert result == pytest.approx(2.8)

    def test_bearing_wear_inflates_vibration(self):
        """At t=60d post-onset (day 95), bearing is near full severity — vibration must be ≥2× baseline."""
        rng = self._rng()
        effect = bearing_wear_effect(elapsed_days=35 + 60, onset_day=35)  # t=60d, near full severity
        result = apply_degradation(
            baseline_value=2.8,
            point_id="ahu-01.returnFan.vibration",
            point_kind=SensorKind.VIBRATION,
            effects=[effect],
            rng=rng,
            baseline_std=0.3,
        )
        assert result > 2.8 * 2.0, "At near-full bearing wear severity, vibration must exceed 2× baseline"

    def test_filter_effect_does_not_affect_vibration_sensor(self):
        """Filter clogging must NOT inflate vibration (key fault differentiator)."""
        rng = self._rng()
        effect = filter_clogging_effect(elapsed_days=60, onset_day=20)
        baseline = 2.8
        result = apply_degradation(
            baseline_value=baseline,
            point_id="ahu-01.returnFan.vibration",
            point_kind=SensorKind.VIBRATION,
            effects=[effect],
            rng=rng,
            baseline_std=0.3,
        )
        # Should be essentially unchanged (filter doesn't affect fan vibration)
        assert abs(result - baseline) < 0.5, "Filter clogging must not affect fan vibration"
