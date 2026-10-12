"""
twin/model.py — Core data model for the digital twin.

Entities are inspired by Project Haystack semantics:
  - Each entity carries semantic tags ({ahu, equip, fan, supply, motor, …})
  - Sensor points are typed, tagged, and carry live readings
  - Health scores roll up from signal → component → system level

Nothing in this file mutates state; all classes are pure data containers.
State transitions are handled by the graph and simulator layers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class OperatingState(str, Enum):
    """Entity operating state — drives UI color and alert logic."""
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    FAULT = "fault"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"


class SensorKind(str, Enum):
    """Physical measurement type — maps to ISO / ASHRAE terminology."""
    VIBRATION = "vibration"       # mm/s RMS (ISO 10816)
    ACOUSTIC = "acoustic"         # dBA SPL
    TEMPERATURE = "temperature"   # °C
    CURRENT = "current"           # A (RMS)
    POWER = "power"               # kW
    PRESSURE_DIFF = "pressure_diff"  # Pa differential
    AIRFLOW = "airflow"           # m³/h
    SPEED = "speed"               # RPM


class FaultMode(str, Enum):
    """Named failure modes the analytics engine can diagnose."""
    NONE = "none"
    BEARING_WEAR = "bearing_wear"         # FM-1
    BELT_SLIPPAGE = "belt_slippage"       # FM-2
    COIL_FOULING = "coil_fouling"         # FM-3
    FILTER_CLOGGING = "filter_clogging"   # FM-4
    DAMPER_FAILURE = "damper_failure"     # FM-5


# ─────────────────────────────────────────────────────────────────────────────
# Sensor point
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SensorBaseline:
    """Normal operating parameters for a single sensor (engineering basis)."""
    mean: float              # Expected value at normal operation
    std: float               # Natural variation (1σ)
    unit: str                # Display unit string
    min_valid: float         # Physical lower bound (for validation)
    max_valid: float         # Physical upper bound (for validation)

    # ISO 10816 / ASHRAE alarm thresholds expressed as multiples of baseline mean
    warning_factor: float = 1.5   # > baseline_mean * factor → WARNING
    critical_factor: float = 2.5  # > baseline_mean * factor → CRITICAL


@dataclass
class SensorReading:
    """A single timestamped sensor observation."""
    timestamp: float          # Unix time
    sim_day: float            # Simulation day (may be fractional)
    value: float
    is_anomalous: bool = False
    anomaly_score: float = 0.0   # 0.0 = normal, 1.0 = maximally anomalous


@dataclass
class SensorPoint:
    """
    A sensor attached to a twin entity.

    Haystack-inspired: each point has tags, a kind, and carries its latest
    reading plus a rolling history buffer for analytics.
    """
    id: str                          # e.g. "ahu-01.supplyFan.vibration"
    dis: str                         # Display name
    kind: SensorKind
    tags: set[str] = field(default_factory=set)
    baseline: SensorBaseline = field(default_factory=lambda: SensorBaseline(0, 1, "", -999, 999))

    # Live state (updated by simulator)
    latest: Optional[SensorReading] = None
    history: list[SensorReading] = field(default_factory=list)

    # Per-signal health (0.0 → 1.0, computed by analytics engine)
    signal_health: float = 1.0

    # Maximum history to keep in memory (1 reading/sec × 90 sim-days → prune to 5000)
    _max_history: int = field(default=5000, repr=False)

    def push_reading(self, reading: SensorReading) -> None:
        """Append a new reading, pruning oldest if over limit."""
        self.latest = reading
        self.history.append(reading)
        if len(self.history) > self._max_history:
            self.history = self.history[-self._max_history:]

    @property
    def values(self) -> list[float]:
        """Raw value array for analytics consumption."""
        return [r.value for r in self.history]

    @property
    def current_value(self) -> Optional[float]:
        return self.latest.value if self.latest else None


# ─────────────────────────────────────────────────────────────────────────────
# Health score
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HealthScore:
    """
    Composite health for one entity (0.0 = failed, 1.0 = perfect).

    Computed bottom-up:
      signal_health  →  component_health  →  system_health
    """
    value: float = 1.0                # Current composite score
    state: OperatingState = OperatingState.NORMAL
    dominant_fault: FaultMode = FaultMode.NONE
    fault_confidence: float = 0.0     # 0.0 → 1.0

    # Signal-level breakdown (sensor_id → health)
    signal_breakdown: dict[str, float] = field(default_factory=dict)

    # Remaining Useful Life estimation
    rul_days: Optional[float] = None  # None = cannot estimate yet
    failure_probability: float = 0.0  # P(failure within RUL window)

    def update_state(self, warning_thresh: float, critical_thresh: float) -> None:
        if self.value >= warning_thresh:
            self.state = OperatingState.NORMAL
        elif self.value >= critical_thresh:
            self.state = OperatingState.WARNING
        else:
            self.state = OperatingState.CRITICAL


# ─────────────────────────────────────────────────────────────────────────────
# Twin entity
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TwinEntity:
    """
    One node in the digital twin graph.

    Inspired by Project Haystack equip/point model:
      - id:       unique dotted path  ("ahu-01.supplyFan.motor")
      - dis:      human display name  ("Supply Fan Motor")
      - tags:     semantic tag set    {"ahu", "equip", "fan", "supply", "motor"}
      - parent_id: graph edge to parent (None for root)

    The entity is intentionally a pure data container — the simulator writes
    readings into its sensor points, and the analytics engine updates health.
    """
    id: str
    dis: str
    tags: set[str] = field(default_factory=set)
    parent_id: Optional[str] = None

    # Attached sensor points (keyed by SensorKind for quick lookup)
    points: dict[str, SensorPoint] = field(default_factory=dict)

    # Current health (updated by analytics engine each tick)
    health: HealthScore = field(default_factory=HealthScore)

    # Metadata
    manufacturer: str = ""
    model_number: str = ""
    install_date: str = ""          # ISO date string
    rated_power_kw: float = 0.0
    rated_speed_rpm: float = 0.0

    # Degradation state (used internally by simulator)
    _degradation_level: float = 0.0  # 0.0 = new, 1.0 = failed

    def add_point(self, point: SensorPoint) -> None:
        self.points[point.id] = point

    def get_point_by_kind(self, kind: SensorKind) -> Optional[SensorPoint]:
        """Return first sensor point matching kind."""
        for p in self.points.values():
            if p.kind == kind:
                return p
        return None

    def to_dict(self) -> dict:
        """Serialise to JSON-safe dict for API responses."""
        return {
            "id": self.id,
            "dis": self.dis,
            "tags": list(self.tags),
            "parent_id": self.parent_id,
            "health": {
                "value": round(self.health.value, 4),
                "state": self.health.state.value,
                "dominant_fault": self.health.dominant_fault.value,
                "fault_confidence": round(self.health.fault_confidence, 3),
                "rul_days": round(self.health.rul_days, 1) if self.health.rul_days is not None else None,
                "failure_probability": round(self.health.failure_probability, 3),
                "signal_breakdown": {k: round(v, 4) for k, v in self.health.signal_breakdown.items()},
            },
            "points": {
                pid: {
                    "id": p.id,
                    "dis": p.dis,
                    "kind": p.kind.value,
                    "tags": list(p.tags),
                    "signal_health": round(p.signal_health, 4),
                    "current_value": round(p.current_value, 3) if p.current_value is not None else None,
                    "unit": p.baseline.unit,
                    "baseline_mean": p.baseline.mean,
                    "baseline_std": p.baseline.std,
                    "is_anomalous": p.latest.is_anomalous if p.latest else False,
                    "anomaly_score": round(p.latest.anomaly_score, 3) if p.latest else 0.0,
                    "timestamp": p.latest.timestamp if p.latest else None,
                    "sim_day": round(p.latest.sim_day, 2) if p.latest else None,
                }
                for pid, p in self.points.items()
            },
            "manufacturer": self.manufacturer,
            "install_date": self.install_date,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Alert
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Alert:
    """A fired alert from the analytics engine."""
    id: str
    entity_id: str
    entity_dis: str
    severity: OperatingState         # WARNING or CRITICAL
    fault_mode: FaultMode
    title: str
    description: str
    sim_day: float
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "entity_dis": self.entity_dis,
            "severity": self.severity.value,
            "fault_mode": self.fault_mode.value,
            "title": self.title,
            "description": self.description,
            "sim_day": round(self.sim_day, 1),
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Maintenance recommendation
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MaintenanceRecommendation:
    """Generated maintenance action tied to a specific fault diagnosis."""
    entity_id: str
    entity_dis: str
    fault_mode: FaultMode
    action: str                   # Short imperative: "Replace bearings"
    rationale: str                # Engineering basis
    priority: str                 # "critical" | "high" | "medium" | "low"
    estimated_downtime_hours: float
    rul_days: Optional[float]
    sim_day: float

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_dis": self.entity_dis,
            "fault_mode": self.fault_mode.value,
            "action": self.action,
            "rationale": self.rationale,
            "priority": self.priority,
            "estimated_downtime_hours": self.estimated_downtime_hours,
            "rul_days": round(self.rul_days, 1) if self.rul_days else None,
            "sim_day": round(self.sim_day, 1),
        }
