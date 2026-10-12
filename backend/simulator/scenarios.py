"""
simulator/scenarios.py — Pre-built 90-day degradation timeline.

Defines which fault modes are active at each simulation day and which
entity they affect. Designed to show overlapping concurrent faults —
the hardest test for multi-signal analytics.

Timeline (from plan Section 5.3):
  Day  0–20:  Normal operation (establish baseline, train Isolation Forest)
  Day 20–90:  FM-4 Filter clogging begins (filterBank)
  Day 35–90:  FM-1 Bearing wear begins (returnFan)
  Day 55–90:  FM-3 Coil fouling begins (coolingCoil)
  Day 70–90:  Bearing reaches critical state → predictive alert
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from twin.model import FaultMode
from .degradation import (
    bearing_wear_effect,
    belt_slippage_effect,
    coil_fouling_effect,
    filter_clogging_effect,
    damper_failure_effect,
    DegradationEffect,
)


@dataclass
class ScenarioEvent:
    """A single fault event active from onset_day onwards."""
    fault_mode: FaultMode
    target_entity_id: str          # Entity whose sensors are affected
    onset_day: float               # Sim-day when degradation begins
    # The degradation function signature varies (damper needs rng), so we
    # store a pre-bound callable for uniformity.
    _compute: Callable[[float], DegradationEffect]

    def effect_at(self, sim_day: float) -> Optional[DegradationEffect]:
        """Return degradation effect at given sim_day, or None if not yet onset."""
        if sim_day < self.onset_day:
            return None
        return self._compute(sim_day)


def build_default_scenario(rng: np.random.Generator) -> list[ScenarioEvent]:
    """
    Construct the default 90-day overlapping fault scenario.

    Returns a list of ScenarioEvents ordered by onset_day.
    """
    events: list[ScenarioEvent] = [
        # FM-4: Filter clogging — filterBank — starts day 20
        ScenarioEvent(
            fault_mode=FaultMode.FILTER_CLOGGING,
            target_entity_id="ahu-01.filterBank",
            onset_day=20.0,
            _compute=lambda d: filter_clogging_effect(d, onset_day=20.0),
        ),
        # FM-1: Bearing wear — returnFan — starts day 35
        ScenarioEvent(
            fault_mode=FaultMode.BEARING_WEAR,
            target_entity_id="ahu-01.returnFan",
            onset_day=35.0,
            _compute=lambda d: bearing_wear_effect(d, onset_day=35.0),
        ),
        # FM-3: Coil fouling — coolingCoil — starts day 55
        ScenarioEvent(
            fault_mode=FaultMode.COIL_FOULING,
            target_entity_id="ahu-01.coolingCoil",
            onset_day=55.0,
            _compute=lambda d: coil_fouling_effect(d, onset_day=55.0),
        ),
    ]
    return events


def build_single_fault_scenario(
    fault_mode: FaultMode,
    target_entity_id: str,
    onset_day: float,
    rng: np.random.Generator,
) -> list[ScenarioEvent]:
    """
    Build a minimal scenario for manual fault injection via the API.
    Used by POST /api/simulation/inject-fault.
    """
    dispatch = {
        FaultMode.BEARING_WEAR: lambda d: bearing_wear_effect(d, onset_day),
        FaultMode.BELT_SLIPPAGE: lambda d: belt_slippage_effect(d, onset_day),
        FaultMode.COIL_FOULING: lambda d: coil_fouling_effect(d, onset_day),
        FaultMode.FILTER_CLOGGING: lambda d: filter_clogging_effect(d, onset_day),
        FaultMode.DAMPER_FAILURE: lambda d: damper_failure_effect(d, onset_day, rng),
    }
    if fault_mode not in dispatch:
        return []
    return [ScenarioEvent(
        fault_mode=fault_mode,
        target_entity_id=target_entity_id,
        onset_day=onset_day,
        _compute=dispatch[fault_mode],
    )]
