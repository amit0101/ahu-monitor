"""
evaluate.py — Headless evaluation of the analytics pipeline against ground truth.

Runs the 90-day simulation without a server, then compares what the analytics
detected against what the simulator actually injected.

Metrics:
  - Alert lead time: how many days before severity hits 1.0 the first alert fired
  - False alarms: alerts on entities with no active fault
  - Diagnosis accuracy: was the diagnosed fault the one actually injected?

Usage:
    cd backend && python3 evaluate.py
"""
from __future__ import annotations

import sys
import time
import warnings
import numpy as np

# Suppress scipy curve_fit warnings (expected when health hasn't changed enough)
warnings.filterwarnings("ignore", category=RuntimeWarning)
try:
    from scipy.optimize import OptimizeWarning
    warnings.filterwarnings("ignore", category=OptimizeWarning)
except ImportError:
    pass

from config import settings
from simulator.engine import SimulationEngine
from simulator.scenarios import build_default_scenario
from simulator.degradation import (
    bearing_wear_effect,
    filter_clogging_effect,
    coil_fouling_effect,
)
from analytics import AnalyticsEngine
from twin.model import FaultMode, OperatingState


# ─────────────────────────────────────────────────────────────────────────────
# Ground truth: which entity has which fault, starting when
# ─────────────────────────────────────────────────────────────────────────────

GROUND_TRUTH = [
    {
        "entity_id": "ahu-01.filterBank",
        "fault_mode": FaultMode.FILTER_CLOGGING,
        "onset_day": 20.0,
        "severity_fn": lambda d: filter_clogging_effect(d, 20.0).severity,
    },
    {
        "entity_id": "ahu-01.returnFan",
        "fault_mode": FaultMode.BEARING_WEAR,
        "onset_day": 35.0,
        "severity_fn": lambda d: bearing_wear_effect(d, 35.0).severity,
    },
    {
        "entity_id": "ahu-01.coolingCoil",
        "fault_mode": FaultMode.COIL_FOULING,
        "onset_day": 55.0,
        "severity_fn": lambda d: coil_fouling_effect(d, 55.0).severity,
    },
]

# Entities that should never fire an alert (no fault injected)
HEALTHY_ENTITIES = {"ahu-01.supplyFan", "ahu-01.heatingCoil", "ahu-01.damper"}


# ─────────────────────────────────────────────────────────────────────────────
# Headless simulation
# ─────────────────────────────────────────────────────────────────────────────

# Speed multiplier for headless: each tick at 1 Hz advances this many seconds
# of sim-time. 3600 → 1 tick = 1 sim-hour → 90 days ≈ 2160 ticks (~5s wall).
HEADLESS_SPEED = 3600


def run_simulation() -> tuple[SimulationEngine, AnalyticsEngine]:
    """Run the full 90-day scenario headlessly (fast-forwarded)."""
    rng = np.random.default_rng(seed=42)
    engine = SimulationEngine()
    analytics = AnalyticsEngine()

    # Build scenario and wire it in
    engine.state.scenario_events = build_default_scenario(rng)
    engine.state.running = True
    engine.state.speed_multiplier = HEADLESS_SPEED

    total_ticks = 0
    while engine.state.sim_day < engine.state.total_days:
        engine._tick()
        engine.state.tick_count += 1
        analytics.on_tick(engine)
        total_ticks += 1

        # Progress feedback every 500 ticks
        if total_ticks % 500 == 0:
            print(f"  day {engine.state.sim_day:.1f} / {engine.state.total_days} "
                  f"({total_ticks} ticks)", flush=True)

    engine.state.running = False
    print(f"  Finished: {total_ticks} ticks, {engine.state.sim_day:.1f} sim-days")
    return engine, analytics


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────

def evaluate(engine: SimulationEngine, analytics: AnalyticsEngine) -> dict:
    """Compare analytics output against ground truth."""
    results: dict = {"faults": [], "false_alarms": [], "summary": {}}

    all_alerts = analytics.alert_history

    for gt in GROUND_TRUTH:
        eid = gt["entity_id"]
        expected_fault = gt["fault_mode"]
        onset = gt["onset_day"]

        # Find the day severity reaches 1.0 (failure)
        failure_day = None
        for d in np.arange(onset, 90.0, 0.1):
            if gt["severity_fn"](d) >= 0.99:
                failure_day = round(float(d), 1)
                break

        # Alerts for this entity
        entity_alerts = [a for a in all_alerts if a.entity_id == eid]
        entity_alerts.sort(key=lambda a: a.sim_day)

        first_alert = entity_alerts[0] if entity_alerts else None
        first_warning = next(
            (a for a in entity_alerts if a.severity == OperatingState.WARNING), None
        )
        first_critical = next(
            (a for a in entity_alerts if a.severity == OperatingState.CRITICAL), None
        )

        # Lead time = days between first alert and failure (or end of sim)
        reference_day = failure_day or 90.0
        lead_time = round(reference_day - first_alert.sim_day, 1) if first_alert else None

        # Diagnosis accuracy: check dominant fault on the entity at end of sim
        entity = engine.twin.get(eid)
        diagnosed_fault = entity.health.dominant_fault if entity else FaultMode.NONE
        diagnosis_correct = diagnosed_fault == expected_fault

        results["faults"].append({
            "entity": eid.split(".")[-1],
            "fault": expected_fault.value,
            "onset_day": onset,
            "failure_day": failure_day,
            "first_alert_day": round(first_alert.sim_day, 1) if first_alert else None,
            "lead_time_days": lead_time,
            "warning_day": round(first_warning.sim_day, 1) if first_warning else None,
            "critical_day": round(first_critical.sim_day, 1) if first_critical else None,
            "diagnosed_fault": diagnosed_fault.value,
            "diagnosis_correct": diagnosis_correct,
            "total_alerts": len(entity_alerts),
        })

    # False alarms: alerts fired on entities with no active fault
    for alert in all_alerts:
        if alert.entity_id in HEALTHY_ENTITIES:
            results["false_alarms"].append({
                "entity": alert.entity_id.split(".")[-1],
                "day": round(alert.sim_day, 1),
                "severity": alert.severity.value,
            })

    # Summary
    faults_detected = sum(1 for f in results["faults"] if f["first_alert_day"] is not None)
    diagnoses_correct = sum(1 for f in results["faults"] if f["diagnosis_correct"])
    lead_times = [f["lead_time_days"] for f in results["faults"] if f["lead_time_days"] is not None]

    results["summary"] = {
        "faults_injected": len(GROUND_TRUTH),
        "faults_detected": faults_detected,
        "detection_rate": f"{faults_detected}/{len(GROUND_TRUTH)}",
        "diagnosis_accuracy": f"{diagnoses_correct}/{len(GROUND_TRUTH)}",
        "false_alarms": len(results["false_alarms"]),
        "mean_lead_time_days": round(np.mean(lead_times), 1) if lead_times else None,
    }
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def print_report(results: dict) -> None:
    """Print a human-readable scorecard."""
    print("\n" + "=" * 72)
    print("  ANALYTICS EVALUATION REPORT — 90-Day Default Scenario")
    print("=" * 72)

    s = results["summary"]
    print(f"\n  Detection rate:      {s['detection_rate']}")
    print(f"  Diagnosis accuracy:  {s['diagnosis_accuracy']}")
    print(f"  False alarms:        {s['false_alarms']}")
    print(f"  Mean lead time:      {s['mean_lead_time_days']} days")

    print(f"\n{'─' * 72}")
    print(f"  {'Entity':<14} {'Fault':<18} {'Onset':>6} {'Alert':>6} {'Lead':>6} "
          f"{'Diag':>14} {'OK':>4}")
    print(f"{'─' * 72}")

    for f in results["faults"]:
        alert_day = f["first_alert_day"] if f["first_alert_day"] is not None else "—"
        lead = f["lead_time_days"] if f["lead_time_days"] is not None else "—"
        diag = f["diagnosed_fault"].replace("_", " ")[:14]
        correct = "✓" if f["diagnosis_correct"] else "✗"
        print(f"  {f['entity']:<14} {f['fault']:<18} {f['onset_day']:>6.0f} "
              f"{str(alert_day):>6} {str(lead):>6} {diag:>14} {correct:>4}")

    if results["false_alarms"]:
        print(f"\n  False alarms ({len(results['false_alarms'])}):")
        for fa in results["false_alarms"][:10]:  # cap display at 10
            print(f"    {fa['entity']:<14} day {fa['day']:<6} {fa['severity']}")
        if len(results["false_alarms"]) > 10:
            print(f"    ... and {len(results['false_alarms']) - 10} more")
    else:
        print(f"\n  False alarms: none ✓")

    # Timeline
    print(f"\n{'─' * 72}")
    print("  Timeline:")
    for f in results["faults"]:
        onset = f["onset_day"]
        failure = f["failure_day"]
        warn = f["warning_day"]
        crit = f["critical_day"]
        line = f"    {f['entity']:<14} "
        line += f"onset d{onset:.0f}"
        if warn: line += f" → warn d{warn:.0f}"
        if crit: line += f" → crit d{crit:.0f}"
        if failure: line += f" → failure d{failure:.0f}"
        else: line += " → (no failure by d90)"
        print(line)

    print(f"\n{'=' * 72}\n")


if __name__ == "__main__":
    print("Running 90-day simulation headlessly...")
    t0 = time.time()
    engine, analytics = run_simulation()
    elapsed = time.time() - t0
    print(f"Simulation complete in {elapsed:.1f}s")

    results = evaluate(engine, analytics)
    print_report(results)
