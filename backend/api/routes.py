"""
api/routes.py — REST API endpoints.

All endpoints are read-only observation of the twin + simulation control.
The engine is accessed via the FastAPI app state (app.state.engine).
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from twin.model import FaultMode
from simulator.scenarios import build_single_fault_scenario

router = APIRouter(prefix="/api")


# ── Dependency: engine from app state ────────────────────────────────────────

def get_engine(request: Request):
    return request.app.state.engine


# ── Request / response models ─────────────────────────────────────────────────

class SpeedRequest(BaseModel):
    multiplier: float

class StartRequest(BaseModel):
    start_day: int = 0

class InjectFaultRequest(BaseModel):
    fault_mode: FaultMode
    target_entity_id: str
    onset_at_current_day: bool = True


# ── Twin endpoints ────────────────────────────────────────────────────────────

@router.get("/twin")
async def get_twin(engine=Depends(get_engine)):
    """Full digital twin state (graph structure + all entity health)."""
    return engine.twin.to_dict()


@router.get("/twin/{entity_id:path}")
async def get_entity(entity_id: str, engine=Depends(get_engine)):
    """Single entity state + sensor points."""
    entity = engine.twin.get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return entity.to_dict()


@router.get("/history/{entity_id:path}")
async def get_entity_history(
    entity_id: str,
    max_points: int = 500,
    engine=Depends(get_engine),
):
    """Time-series history for all sensors of an entity."""
    entity = engine.twin.get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return engine.get_history_for_entity(entity_id, max_points)


# ── Health endpoints ──────────────────────────────────────────────────────────

@router.get("/health")
async def get_health(engine=Depends(get_engine)):
    """Compact health summary for all entities."""
    return engine.twin.health_summary()


# ── Alerts endpoints ──────────────────────────────────────────────────────────

@router.get("/alerts")
async def get_alerts(engine=Depends(get_engine)):
    """Active (unacknowledged) alerts."""
    analytics = engine._analytics if hasattr(engine, "_analytics") else None
    if analytics:
        return [a.to_dict() for a in analytics.active_alerts]
    return []


@router.get("/alerts/history")
async def get_alerts_history(engine=Depends(get_engine)):
    """Full historical alert log."""
    analytics = engine._analytics if hasattr(engine, "_analytics") else None
    if analytics:
        return [a.to_dict() for a in analytics.alert_history]
    return []


# ── Predictions endpoint ──────────────────────────────────────────────────────

@router.get("/predictions")
async def get_predictions(engine=Depends(get_engine)):
    """RUL estimates and failure probabilities for all entities."""
    result = {}
    for entity in engine.twin.all_entities():
        h = entity.health
        if h.rul_days is not None or h.failure_probability > 0:
            result[entity.id] = {
                "entity_dis": entity.dis,
                "health": round(h.value, 4),
                "state": h.state.value,
                "dominant_fault": h.dominant_fault.value,
                "fault_confidence": round(h.fault_confidence, 3),
                "rul_days": round(h.rul_days, 1) if h.rul_days is not None else None,
                "failure_probability": round(h.failure_probability, 3),
            }
    return result


# ── Maintenance recommendations ───────────────────────────────────────────────

@router.get("/maintenance")
async def get_maintenance(engine=Depends(get_engine)):
    """Current maintenance recommendations."""
    analytics = engine._analytics if hasattr(engine, "_analytics") else None
    if analytics:
        return [r.to_dict() for r in analytics.recommendations]
    return []


# ── Simulation control ────────────────────────────────────────────────────────

@router.post("/simulation/start")
async def start_simulation(
    body: Optional[StartRequest] = None,
    engine=Depends(get_engine),
):
    """Start or restart the simulation, optionally fast-forwarding to start_day."""
    start_day = body.start_day if body else 0
    await engine.start(start_day=start_day)
    return {"status": "started", "sim_day": round(engine.state.sim_day, 2)}


@router.post("/simulation/stop")
async def stop_simulation(engine=Depends(get_engine)):
    """Stop and RESET the simulation (returns to day 0)."""
    await engine.start()  # start() resets everything
    await engine.stop()   # then immediately stop before loop advances
    return {"status": "reset", "sim_day": 0}


@router.post("/simulation/pause")
async def pause_simulation(engine=Depends(get_engine)):
    """Pause the simulation, preserving current sim_day."""
    await engine.stop()
    return {"status": "paused", "sim_day": round(engine.state.sim_day, 2)}


@router.post("/simulation/resume")
async def resume_simulation(engine=Depends(get_engine)):
    """Resume the simulation from the current sim_day."""
    await engine.resume()
    return {"status": "running", "sim_day": round(engine.state.sim_day, 2)}


@router.post("/simulation/speed")
async def set_speed(body: SpeedRequest, engine=Depends(get_engine)):
    """Adjust simulation speed multiplier."""
    engine.set_speed(body.multiplier)
    return {"speed_multiplier": engine.state.speed_multiplier}


@router.post("/simulation/inject-fault")
async def inject_fault(body: InjectFaultRequest, engine=Depends(get_engine)):
    """Manually inject a fault mode for demo/testing."""
    import numpy as np
    onset = engine.state.sim_day if body.onset_at_current_day else 0.0
    rng = np.random.default_rng()
    events = build_single_fault_scenario(
        fault_mode=body.fault_mode,
        target_entity_id=body.target_entity_id,
        onset_day=onset,
        rng=rng,
    )
    if not events:
        raise HTTPException(status_code=400, detail="Unknown fault mode")
    engine.inject_fault(events)
    return {
        "injected": body.fault_mode.value,
        "target": body.target_entity_id,
        "onset_day": onset,
    }


@router.get("/simulation/status")
async def simulation_status(engine=Depends(get_engine)):
    """Current simulation state."""
    return engine.state.to_dict()
