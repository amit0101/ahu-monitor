"""
analytics/fusion.py — Multi-signal health scoring + alert generation.

This is the top-level analytics orchestrator.  On every simulation tick it:
  1. Runs AnomalyDetector on every sensor point → per-signal health score
  2. Rolls signal health up to component health (weighted average)
  3. Rolls component health up to system health
  4. Runs FaultDiagnoser → identifies dominant fault mode
  5. Runs RULEstimator on degraded components → remaining useful life
  6. Fires Alert objects when health transitions cross thresholds
  7. Generates MaintenanceRecommendation records for actionable faults

All state is kept inside this engine; the SimulationEngine calls
  analytics_engine.on_tick(sim_engine)
as a registered observer, then exposes active_alerts / recommendations
through the analytics reference stored in engine._analytics.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing import Optional

import numpy as np

from config import settings
from twin.model import (
    FaultMode, OperatingState, SensorKind,
    Alert, MaintenanceRecommendation, TwinEntity,
)
from analytics.anomaly import AnomalyDetector
from analytics.diagnosis import FaultDiagnoser, DiagnosisResult
from analytics.prediction import RULEstimator, RULResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Component health weights (mirrors config.py)
# ─────────────────────────────────────────────────────────────────────────────

ENTITY_WEIGHTS: dict[str, float] = {
    "ahu-01.supplyFan":    settings.weight_supply_fan,
    "ahu-01.coolingCoil":  settings.weight_cooling_coil,
    "ahu-01.filterBank":   settings.weight_filter,
    "ahu-01.returnFan":    settings.weight_return_fan,
    "ahu-01.heatingCoil":  settings.weight_heating_coil,
    "ahu-01.damper":       settings.weight_damper,
}

# ─────────────────────────────────────────────────────────────────────────────
# Maintenance action templates (per fault mode)
# ─────────────────────────────────────────────────────────────────────────────

MAINTENANCE_TEMPLATES: dict[FaultMode, dict] = {
    FaultMode.BEARING_WEAR: {
        "action": "Replace fan bearings",
        "rationale": (
            "Progressive bearing wear detected via vibration rise (ISO 10816 bands), "
            "broadband acoustic noise, and bearing housing temperature elevation. "
            "Exponential degradation trajectory indicates accelerating wear."
        ),
        "estimated_downtime_hours": 4.0,
    },
    FaultMode.BELT_SLIPPAGE: {
        "action": "Inspect and replace drive belt",
        "rationale": (
            "Belt slippage detected via distinctive tonal acoustic signature, "
            "reduced fan speed, and current drop during slip phase. "
            "Risk of sudden belt failure causing AHU shutdown."
        ),
        "estimated_downtime_hours": 2.0,
    },
    FaultMode.COIL_FOULING: {
        "action": "Chemical clean cooling coil",
        "rationale": (
            "Coil fouling detected via reduced heat transfer effectiveness: "
            "discharge air temperature above setpoint while coil ΔT has decreased. "
            "ASHRAE recommends cleaning when coil effectiveness drops >10%."
        ),
        "estimated_downtime_hours": 6.0,
    },
    FaultMode.FILTER_CLOGGING: {
        "action": "Replace filter media",
        "rationale": (
            "Filter differential pressure exceeds 250 Pa service limit. "
            "Increased static pressure causes fan to overwork (elevated current), "
            "reducing airflow volume and system efficiency."
        ),
        "estimated_downtime_hours": 0.5,
    },
    FaultMode.DAMPER_FAILURE: {
        "action": "Inspect and recalibrate mixed air damper actuator",
        "rationale": (
            "Damper actuator showing erratic position control: mixed air temperature "
            "deviating from setpoint. Risk of uncontrolled free-cooling or excessive "
            "reheat energy consumption."
        ),
        "estimated_downtime_hours": 3.0,
    },
}


class AnalyticsEngine:
    """
    Observer-pattern analytics engine wired into the SimulationEngine.

    Register with:
        engine.register_observer(analytics.on_tick)
        engine._analytics = analytics
    """

    def __init__(self) -> None:
        self._detector = AnomalyDetector()
        self._diagnoser = FaultDiagnoser()
        self._rul_estimator = RULEstimator()

        # Per-entity health history for RUL fitting {entity_id: [(sim_day, health), ...]}
        self._health_history: dict[str, list[tuple[float, float]]] = defaultdict(list)
        # Track previous health states to detect transitions
        self._prev_states: dict[str, OperatingState] = {}
        # Debounce: count consecutive ticks in each degraded state before firing alert
        # Prevents noise-driven alert storms during detector warm-up.
        self._state_tick_count: dict[str, int] = {}
        # Number of consecutive ticks in a degraded state required before firing
        ALERT_DEBOUNCE_TICKS = 5
        self._debounce_ticks = ALERT_DEBOUNCE_TICKS
        # Track the state at which each entity last fired an alert (edge-triggered)
        self._last_fired_state: dict[str, OperatingState] = {}
        # Minimum sim-day gap between alerts for the same entity (cooldown)
        self._ALERT_COOLDOWN_DAYS = 3.0
        self._last_alert_day: dict[str, float] = {}

        # Public collections consumed by API routes
        self.active_alerts: list[Alert] = []
        self.alert_history: list[Alert] = []
        self.recommendations: list[MaintenanceRecommendation] = []
        # Sticky recommendations: keyed by entity_id, persists until entity returns to NORMAL.
        # This prevents recommendations from flickering on/off as health oscillates.
        self._active_rec_entities: dict[str, MaintenanceRecommendation] = {}

    # ── Observer entry point ─────────────────────────────────────────────────

    def on_tick(self, sim_engine) -> None:
        """
        Called by SimulationEngine on every tick.
        sim_engine: SimulationEngine (typed loosely to avoid circular import)
        """
        sim_day = sim_engine.state.sim_day
        fast_forwarding = sim_engine.state.fast_forwarding

        # ── Pass 1: per-sensor anomaly detection ─────────────────────────────
        for entity in sim_engine.twin.all_entities():
            if not entity.points:
                continue
            self._process_entity_sensors(entity, sim_day, fast_forwarding)

        # ── Pass 2: roll-up health + diagnosis + RUL ─────────────────────────
        for entity in sim_engine.twin.all_entities():
            if not entity.points:
                continue
            self._update_entity_health(entity, sim_day)

        # ── Pass 3: system-level health roll-up ──────────────────────────────
        self._update_system_health(sim_engine.twin)

        # ── Pass 4: alert generation (suppressed during baseline training) ────
        # Don't fire alerts until detectors have trained on enough baseline data.
        # baseline_training_days comes from config (default: 20 sim-days).
        if sim_day >= settings.baseline_training_days:
            self._check_alerts(sim_engine.twin, sim_day)

        # ── Pass 5: maintenance recommendations ───────────────────────────────
        self._update_recommendations(sim_engine.twin, sim_day)

    def reset(self) -> None:
        """Called when simulation restarts."""
        self._detector.reset()
        self._health_history.clear()
        self._prev_states.clear()
        self._state_tick_count.clear()
        self._last_fired_state.clear()
        self._last_alert_day.clear()
        self.active_alerts.clear()
        self.alert_history.clear()
        self.recommendations.clear()
        self._active_rec_entities.clear()

    # ── Pass 1: per-sensor anomaly detection ──────────────────────────────────

    def _process_entity_sensors(self, entity: TwinEntity, sim_day: float, fast_forwarding: bool = False) -> None:
        for point in entity.points.values():
            if point.latest is None:
                continue
            score, is_anom = self._detector.update(
                sensor_id=point.id,
                value=point.latest.value,
                baseline_mean=point.baseline.mean,
                baseline_std=point.baseline.std,
                sim_day=sim_day,
                fast_forwarding=fast_forwarding,
            )
            # Write back into the reading (in-place, the latest reading object)
            point.latest.anomaly_score = score
            point.latest.is_anomalous = is_anom
            # Per-signal health: 1 - anomaly_score, smoothed
            point.signal_health = float(np.clip(1.0 - score, 0.0, 1.0))

    # ── Pass 2: entity-level health roll-up + diagnosis + RUL ─────────────────

    def _update_entity_health(self, entity: TwinEntity, sim_day: float) -> None:
        if not entity.points:
            return

        # Weighted average of signal healths (equal weight within entity)
        signal_healths = {pid: p.signal_health for pid, p in entity.points.items()}
        avg_health = float(np.mean(list(signal_healths.values())))

        # ── Fault diagnosis ───────────────────────────────────────────────────
        deviations = self._compute_signal_deviations(entity)
        diagnosis: DiagnosisResult = self._diagnoser.diagnose(deviations)

        # ── RUL estimation (only for degraded entities) ───────────────────────
        self._health_history[entity.id].append((sim_day, avg_health))
        # Keep manageable history (last 5000 ticks)
        if len(self._health_history[entity.id]) > 5000:
            self._health_history[entity.id] = self._health_history[entity.id][-5000:]

        rul_result = self._maybe_estimate_rul(entity.id, avg_health, sim_day)

        # ── Update entity health object ───────────────────────────────────────
        entity.health.value = avg_health
        entity.health.signal_breakdown = signal_healths
        entity.health.dominant_fault = diagnosis.fault_mode
        entity.health.fault_confidence = diagnosis.confidence
        entity.health.rul_days = rul_result.rul_days if rul_result else None
        entity.health.failure_probability = rul_result.failure_probability if rul_result else 0.0
        entity.health.update_state(
            settings.health_warning_threshold,
            settings.health_critical_threshold,
        )

    def _compute_signal_deviations(self, entity: TwinEntity) -> dict[SensorKind, float]:
        """Compute z-score deviations for each sensor kind in the entity.

        When multiple sensors share a SensorKind (e.g. two TEMPERATURE points
        on the cooling coil), keep the one with the largest absolute z-score —
        the most deviated signal is more informative for fault matching.
        """
        deviations: dict[SensorKind, float] = {}
        for point in entity.points.values():
            if point.latest is None:
                continue
            std = max(point.baseline.std, 1e-6)
            z = (point.latest.value - point.baseline.mean) / std
            existing = deviations.get(point.kind)
            if existing is None or abs(z) > abs(existing):
                deviations[point.kind] = float(z)
        return deviations

    def _maybe_estimate_rul(
        self, entity_id: str, current_health: float, sim_day: float
    ) -> Optional[RULResult]:
        """Only estimate RUL if health is degrading (below warning threshold)."""
        if current_health > settings.health_warning_threshold:
            return None
        history = self._health_history[entity_id]
        health_vals = [h for _, h in history]
        day_vals = [d for d, _ in history]
        return self._rul_estimator.estimate(health_vals, day_vals, sim_day)

    # ── Pass 3: system-level roll-up ──────────────────────────────────────────

    def _update_system_health(self, twin) -> None:
        """Weighted roll-up from component health to AHU system health."""
        root = twin.get("ahu-01")
        if root is None:
            return

        total_weight = 0.0
        weighted_sum = 0.0
        for entity_id, weight in ENTITY_WEIGHTS.items():
            entity = twin.get(entity_id)
            if entity is not None:
                weighted_sum += entity.health.value * weight
                total_weight += weight

        if total_weight > 0:
            system_health = weighted_sum / total_weight
            root.health.value = float(np.clip(system_health, 0.0, 1.0))
            root.health.update_state(
                settings.health_warning_threshold,
                settings.health_critical_threshold,
            )

    # ── Pass 4: alert generation ──────────────────────────────────────────────

    def _check_alerts(self, twin, sim_day: float) -> None:
        """
        Fire alerts on health state transitions with debounce + cooldown.

        Alert fires only when ALL of the following are true:
          1. Entity has been in a degraded state for >= _debounce_ticks consecutive ticks
          2. The current state is *different* from the state at last alert (edge-triggered)
          3. At least _ALERT_COOLDOWN_DAYS sim-days have passed since the last alert
             for this entity (prevents re-fires during sustained degradation)
        """
        for entity in twin.all_entities():
            entity_id = entity.id
            current_state = entity.health.state

            is_degraded = current_state in (OperatingState.WARNING, OperatingState.CRITICAL)

            if is_degraded:
                count = self._state_tick_count.get(entity_id, 0) + 1
                self._state_tick_count[entity_id] = count

                if count >= self._debounce_ticks:
                    last_state = self._last_fired_state.get(entity_id)
                    last_day   = self._last_alert_day.get(entity_id, -999.0)
                    state_changed = current_state != last_state
                    cooled_down   = (sim_day - last_day) >= self._ALERT_COOLDOWN_DAYS

                    if state_changed and cooled_down:
                        self._fire_alert(entity, current_state, sim_day)
                        self._last_fired_state[entity_id] = current_state
                        self._last_alert_day[entity_id] = sim_day
            else:
                # Recovery to NORMAL — reset debounce counter and last-fired state
                # so we alert again if entity re-degrades later
                self._state_tick_count[entity_id] = 0
                self._last_fired_state.pop(entity_id, None)

            self._prev_states[entity_id] = current_state

    def _fire_alert(self, entity: TwinEntity, state: OperatingState, sim_day: float) -> None:
        fault = entity.health.dominant_fault
        template = MAINTENANCE_TEMPLATES.get(fault)

        if state == OperatingState.WARNING:
            title = f"{entity.dis} — Health degrading"
            severity_word = "WARNING"
        else:
            title = f"{entity.dis} — Critical condition"
            severity_word = "CRITICAL"

        rul_str = (
            f" RUL ~{entity.health.rul_days:.0f} days."
            if entity.health.rul_days is not None
            else ""
        )
        fault_str = (
            f" Probable fault: {fault.value.replace('_', ' ').title()} "
            f"(confidence {entity.health.fault_confidence:.0%})."
            if fault != FaultMode.NONE
            else ""
        )
        description = (
            f"{severity_word}: {entity.dis} health at {entity.health.value:.0%}."
            f"{fault_str}{rul_str}"
        )

        alert = Alert(
            id=str(uuid.uuid4()),
            entity_id=entity.id,
            entity_dis=entity.dis,
            severity=state,
            fault_mode=fault,
            title=title,
            description=description,
            sim_day=sim_day,
            timestamp=time.time(),
        )
        self.active_alerts.insert(0, alert)
        self.alert_history.insert(0, alert)
        # Cap lists
        self.active_alerts = self.active_alerts[:50]
        self.alert_history = self.alert_history[:200]
        logger.info("Alert fired: %s (day %.1f)", title, sim_day)

    # ── Pass 5: maintenance recommendations ───────────────────────────────────

    def _update_recommendations(self, twin, sim_day: float) -> None:
        """Maintain a sticky set of maintenance recommendations.

        Design intent:
          - A recommendation is RAISED when an entity first enters WARNING or CRITICAL
            and a known fault template exists.
          - A recommendation is RETIRED only when the entity's state returns to NORMAL
            (i.e. maintenance has been performed or health genuinely recovered).
          - Between those two events, the card persists and is updated each tick with
            the latest rul_days / priority so it always shows current data.

        This prevents recommendations from flickering on/off due to normal health
        score oscillation around the WARNING threshold, which would make the panel
        useless for operators.
        """
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

        for entity in twin.all_entities():
            eid = entity.id
            fault = entity.health.dominant_fault
            state = entity.health.state

            # ── Retire: entity returned to NORMAL → remove sticky rec ─────────
            if state == OperatingState.NORMAL:
                self._active_rec_entities.pop(eid, None)
                continue

            # ── Skip entities with no known fault or no template ──────────────
            if fault == FaultMode.NONE:
                continue
            template = MAINTENANCE_TEMPLATES.get(fault)
            if template is None:
                continue

            # ── Priority: always re-evaluated from current state ──────────────
            if state == OperatingState.CRITICAL:
                priority = "critical"
            elif entity.health.rul_days is not None and entity.health.rul_days < 15:
                priority = "high"
            elif state == OperatingState.WARNING:
                priority = "medium"
            else:
                priority = "low"

            if eid in self._active_rec_entities:
                # Update existing sticky rec in-place (keep original raise time)
                existing = self._active_rec_entities[eid]
                existing.priority = priority
                existing.rul_days = entity.health.rul_days
                existing.sim_day = sim_day
            else:
                # First time this entity entered a degraded state — raise new rec
                self._active_rec_entities[eid] = MaintenanceRecommendation(
                    entity_id=eid,
                    entity_dis=entity.dis,
                    fault_mode=fault,
                    action=template["action"],
                    rationale=template["rationale"],
                    priority=priority,
                    estimated_downtime_hours=template["estimated_downtime_hours"],
                    rul_days=entity.health.rul_days,
                    sim_day=sim_day,
                )

        # Rebuild sorted recommendations list from sticky dict
        recs = list(self._active_rec_entities.values())
        recs.sort(key=lambda r: (
            priority_order.get(r.priority, 9),
            r.rul_days if r.rul_days is not None else 9999,
        ))
        self.recommendations = recs
