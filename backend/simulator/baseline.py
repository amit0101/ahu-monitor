"""
simulator/baseline.py — Normal operating baseline profiles.

Each sensor's baseline is a Gaussian distribution parameterised from the
engineering specs in twin/factory.py. The simulator samples from these
during the normal phase and uses them as the starting point for degradation.

Also provides the EWMA seed values used by the analytics engine.
"""
from __future__ import annotations

import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from twin.model import SensorPoint


class BaselineProfile:
    """
    Generates realistic normal operating readings for a sensor point.

    Adds:
    - Gaussian noise (natural mechanical variation)
    - Slow sinusoidal drift (thermal cycling, load variation)
    - Occasional impulses (< 1% rate) to simulate brief load spikes
    """

    def __init__(self, rng: np.random.Generator) -> None:
        self._rng = rng
        self._tick: int = 0   # Total ticks elapsed (for drift calculation)

    def sample(self, point: "SensorPoint", sim_day: float) -> float:
        """
        Return a single realistic baseline reading for the given sensor.

        Args:
            point:    The SensorPoint (carries baseline params)
            sim_day:  Current simulation day (for thermal cycle drift)

        Returns:
            float: Sampled sensor value in engineering units
        """
        bl = point.baseline
        self._tick += 1

        # 1. Core Gaussian noise
        value = self._rng.normal(bl.mean, bl.std)

        # 2. Slow sinusoidal drift (24-hour thermal cycle at 1 Hz sim rate)
        #    Amplitude = 0.5σ to stay well within normal band
        drift_amplitude = bl.std * 0.5
        drift = drift_amplitude * np.sin(2 * np.pi * sim_day / 1.0)
        value += drift

        # 3. Rare impulse events (0.5% probability per tick)
        if self._rng.random() < 0.005:
            value += self._rng.normal(0, bl.std * 2.0)

        # 4. Clip to physical bounds
        value = float(np.clip(value, bl.min_valid, bl.max_valid))

        return value
