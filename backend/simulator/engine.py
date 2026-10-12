"""
simulator/engine.py — Main simulation loop.

Runs as an async background task (asyncio). Each tick:
  1. Advance sim_day by (speed_multiplier / tick_hz / 86400)
  2. For each entity, sample all sensor points:
     a. Draw baseline reading
     b. Apply active degradation effects
     c. Push SensorReading onto the point's history buffer
  3. Notify registered observers (analytics engine, WebSocket broadcaster)

The engine is completely decoupled from FastAPI — it communicates via
an asyncio.Queue that the API layer subscribes to.
"""
from __future__ import annotations

import asyncio
import time
import uuid
import logging
from typing import Callable, Optional

import numpy as np

from config import settings
from twin.model import SensorReading, FaultMode
from twin.graph import DigitalTwinGraph
from twin.factory import build_ahu_01
from .baseline import BaselineProfile
from .degradation import apply_degradation, DegradationEffect
from .scenarios import ScenarioEvent, build_default_scenario

logger = logging.getLogger(__name__)


# Type alias for tick observers
TickObserver = Callable[["SimulationEngine"], None]


class SimulationState:
    """Mutable simulation control state (thread-safe via asyncio)."""

    def __init__(self) -> None:
        self.running: bool = False
        self.sim_day: float = 0.0
        self.speed_multiplier: float = settings.sim_speed_multiplier
        self.total_days: int = settings.sim_total_days
        self.tick_count: int = 0
        self.started_at: Optional[float] = None
        self.scenario_events: list[ScenarioEvent] = []
        self.fast_forwarding: bool = False   # True during silent pre-roll
        self.ff_target_day: float = 0.0      # day the pre-roll is heading to

    @property
    def progress_pct(self) -> float:
        return min(100.0, (self.sim_day / self.total_days) * 100)

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "sim_day": round(self.sim_day, 2),
            "total_days": self.total_days,
            "progress_pct": round(self.progress_pct, 1),
            "speed_multiplier": self.speed_multiplier,
            "tick_count": self.tick_count,
            "fast_forwarding": self.fast_forwarding,
            "target_day": self.ff_target_day if self.fast_forwarding else round(self.sim_day, 2),
        }


class SimulationEngine:
    """
    Async simulation engine.

    Usage:
        engine = SimulationEngine()
        await engine.start()
        engine.register_observer(my_callback)
        await engine.stop()
    """

    def __init__(self) -> None:
        self._rng = np.random.default_rng(seed=42)  # Reproducible seed
        self.twin: DigitalTwinGraph = build_ahu_01()
        self.state = SimulationState()
        self._baseline = BaselineProfile(self._rng)
        self._observers: list[TickObserver] = []
        self._task: Optional[asyncio.Task] = None

        # Active degradation effects indexed by entity_id
        self._active_effects: dict[str, list[DegradationEffect]] = {}
        self._pending_speed: Optional[float] = None   # speed change requested during pre-roll

    # ── Observer pattern ─────────────────────────────────────────────────────

    def register_observer(self, observer: TickObserver) -> None:
        self._observers.append(observer)

    def _notify_observers(self) -> None:
        for obs in self._observers:
            try:
                obs(self)
            except Exception as exc:
                logger.warning("Observer error: %s", exc)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(
        self,
        scenario: Optional[list[ScenarioEvent]] = None,
        start_day: int = 0,
    ) -> None:
        """Start (or restart) the simulation, optionally fast-forwarding to start_day."""
        await self.stop()
        prev_speed = self.state.speed_multiplier   # keep the user's chosen speed across restarts/jumps
        self._pending_speed = None
        self.twin = build_ahu_01()          # Fresh twin
        self._rng = np.random.default_rng(seed=42)
        self._baseline = BaselineProfile(self._rng)
        self._active_effects = {}
        self.state = SimulationState()
        self.state.speed_multiplier = prev_speed
        self.state.scenario_events = scenario or build_default_scenario(self._rng)
        self.state.running = True
        self.state.started_at = time.time()
        # Reset analytics engine so stale alerts/health history don't persist
        if hasattr(self, "_analytics") and self._analytics is not None:
            self._analytics.reset()

        # Pre-roll + live loop run in ONE background task, so start() returns
        # immediately and a newer start()/stop() can cancel a pre-roll in progress.
        start_day = max(0, min(int(start_day), self.state.total_days - 1))
        self._task = asyncio.create_task(self._preroll_then_run(start_day))
        logger.info("Simulation starting (speed=%.0f×, start_day=%d)",
                    self.state.speed_multiplier, start_day)

    async def _preroll_then_run(self, start_day: int) -> None:
        """Silent fast-forward to start_day (no WS broadcast), then the live loop.

        Observers still run during the pre-roll so analytics warm up. Uses coarse
        30-sim-minute ticks to keep the pre-roll fast.
        """
        st = self.state
        if start_day > 0:
            logger.info("Fast-forwarding to day %d (silent pre-roll)…", start_day)
            live_speed = st.speed_multiplier
            st.speed_multiplier = 1800.0 * settings.sim_tick_hz  # 30 sim-min / tick
            st.ff_target_day = float(start_day)
            st.fast_forwarding = True
            n = 0
            try:
                while st.sim_day < start_day:
                    self._tick()
                    st.tick_count += 1
                    for obs in self._observers:
                        try:
                            obs(self)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Observer error during fast-forward: %s", exc)
                    n += 1
                    if n % 20 == 0:
                        await asyncio.sleep(0.001)   # yield; ensures server responds to incoming connections
            finally:
                st.fast_forwarding = False
                # A speed change requested mid-pre-roll wins over the pre-roll value
                st.speed_multiplier = self._pending_speed or live_speed
                self._pending_speed = None
            logger.info("Fast-forward complete — live at day %.1f", st.sim_day)
        await self._run()

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.state.running = False

    async def resume(self) -> None:
        """Resume from the current sim_day without resetting anything."""
        if self.state.running:
            return  # already running
        if self.state.sim_day >= self.state.total_days:
            return  # completed — use start() to restart
        self.state.running = True
        self._task = asyncio.create_task(self._run())
        logger.info("Simulation resumed at day %.2f", self.state.sim_day)

    def set_speed(self, multiplier: float) -> None:
        multiplier = max(0.1, min(500.0, multiplier))
        if self.state.fast_forwarding:
            self._pending_speed = multiplier   # applied when the pre-roll finishes
        else:
            self.state.speed_multiplier = multiplier

    def inject_fault(self, events: list[ScenarioEvent]) -> None:
        """Add new fault events to the running scenario."""
        self.state.scenario_events.extend(events)

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        """
        Simulation tick loop.

        Wall-clock tick interval = 1 / tick_hz seconds.
        Each tick advances sim_day by speed_multiplier / (tick_hz × 86400).

        DISPLAY RATE vs COMPUTE RATE:
        At high speeds (e.g. 100×), internal ticks fire up to 100× per second.
        But broadcasting a WebSocket snapshot on every tick at 100 Hz makes
        the UI unreadable (numbers strobe). We cap _notify_observers() at
        DISPLAY_HZ (8 Hz) so the UI always updates at a human-readable pace
        regardless of the chosen speed multiplier.
        """
        DISPLAY_HZ = 8.0                         # Max UI updates per real second
        DISPLAY_INTERVAL = 1.0 / DISPLAY_HZ      # 0.125 s between broadcasts

        tick_interval = 1.0 / settings.sim_tick_hz
        last_broadcast = time.monotonic()

        while self.state.running and self.state.sim_day < self.state.total_days:
            tick_start = time.monotonic()

            # Always advance simulation state every tick
            self._tick()
            self.state.tick_count += 1

            # Only push to observers (WS + analytics) at the display rate cap.
            # This keeps sensor cards readable at any speed multiplier.
            now = time.monotonic()
            if now - last_broadcast >= DISPLAY_INTERVAL:
                self._notify_observers()
                last_broadcast = now

            # Sleep the remainder of the (speed-scaled) tick interval, but in
            # small chunks so a speed change takes effect within ~50 ms for
            # speed increases (deadline already past) and within ~150 ms for
            # speed decreases (cap the extra wait so 50x→1x feels instant).
            elapsed = time.monotonic() - tick_start
            deadline = tick_start + tick_interval / self.state.speed_multiplier
            CHUNK = 0.05           # 50 ms max per sleep slice
            MAX_SPEED_DOWN = 0.15  # cap wait after a speed decrease
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(remaining, CHUNK))
                # Recompute deadline in case speed changed while sleeping
                new_deadline = tick_start + tick_interval / self.state.speed_multiplier
                # Speed decreased → deadline moved further out. Cap the extra
                # wait so the next tick fires within MAX_SPEED_DOWN of now.
                if new_deadline > deadline:
                    new_deadline = min(new_deadline, time.monotonic() + MAX_SPEED_DOWN)
                deadline = new_deadline

        # Final broadcast so UI reflects the terminal state
        self._notify_observers()
        self.state.running = False
        logger.info("Simulation complete at day %.1f", self.state.sim_day)

    def _tick(self) -> None:
        """Process one simulation tick: advance time, sample sensors, apply degradation."""
        # Advance simulation time
        day_increment = self.state.speed_multiplier / (settings.sim_tick_hz * 86400)
        self.state.sim_day = min(
            self.state.total_days,
            self.state.sim_day + day_increment,
        )
        sim_day = self.state.sim_day

        # Collect active degradation effects per entity
        self._active_effects = {}
        for event in self.state.scenario_events:
            effect = event.effect_at(sim_day)
            if effect is not None:
                entity_effects = self._active_effects.setdefault(event.target_entity_id, [])
                entity_effects.append(effect)

        # Sample all sensor points
        now = time.time()
        for entity in self.twin.all_entities():
            entity_effects = self._active_effects.get(entity.id, [])
            for point in entity.points.values():
                # 1. Sample baseline
                baseline_val = self._baseline.sample(point, sim_day)
                # 2. Apply degradation
                final_val = apply_degradation(
                    baseline_value=baseline_val,
                    point_id=point.id,
                    point_kind=point.kind,
                    effects=entity_effects,
                    rng=self._rng,
                    baseline_std=point.baseline.std,
                )
                # 3. Push reading (anomaly fields filled by analytics engine)
                reading = SensorReading(
                    timestamp=now,
                    sim_day=sim_day,
                    value=final_val,
                )
                point.push_reading(reading)

    def get_live_snapshot(self) -> dict:
        """
        Compact snapshot of current sensor values for WebSocket broadcast.
        Designed to be small and fast to serialise.
        """
        snapshot: dict = {
            "sim_day": round(self.state.sim_day, 2),
            "tick": self.state.tick_count,
            "speed_multiplier": self.state.speed_multiplier,
            "sensors": {},
            "health": self.twin.health_summary(),
        }
        for entity in self.twin.all_entities():
            for pid, point in entity.points.items():
                if point.latest:
                    snapshot["sensors"][pid] = {
                        "v": round(point.latest.value, 3),
                        "anom": point.latest.is_anomalous,
                        "score": round(point.latest.anomaly_score, 3),
                        "health": round(point.signal_health, 4),
                        "day": round(point.latest.sim_day, 2),
                    }
        return snapshot

    def get_history_for_entity(self, entity_id: str, max_points: int = 500) -> dict:
        """Return time-series history for all sensors of an entity (for charts)."""
        entity = self.twin.get(entity_id)
        if not entity:
            return {}

        result: dict[str, list] = {}
        for pid, point in entity.points.items():
            history = point.history[-max_points:]
            result[pid] = [
                {
                    "t": round(r.sim_day, 2),
                    "v": round(r.value, 3),
                    "anom": r.is_anomalous,
                }
                for r in history
            ]
        return result
