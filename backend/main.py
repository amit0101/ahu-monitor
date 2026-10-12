"""
main.py — FastAPI application entry point.

Wires together:
  - SimulationEngine (started on app startup)
  - AnalyticsEngine (registered as engine observer)
  - REST routes
  - WebSocket endpoints
  - CORS middleware

The engine broadcasts live snapshots to WebSocket clients on every tick
via the analytics observer callback.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from simulator.engine import SimulationEngine
from analytics import AnalyticsEngine
from api.routes import router
from api.assistant import router as assistant_router
from api.websocket import manager, ws_live, ws_alerts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://.*" if "*" in settings.cors_origins else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(assistant_router)


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan: start engine + analytics on startup
# ─────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup() -> None:
    engine = SimulationEngine()

    # ── Analytics engine (Phase 2) ────────────────────────────────────────────
    analytics = AnalyticsEngine()
    engine.register_observer(analytics.on_tick)
    engine._analytics = analytics

    # ── Observer: broadcast live snapshots to WebSocket clients on every tick ─
    # Registered AFTER analytics so the snapshot already has updated health scores
    def broadcast_observer(eng: SimulationEngine) -> None:
        if eng.state.fast_forwarding:
            return   # silent pre-roll — don't broadcast to WebSocket clients
        snapshot = eng.get_live_snapshot()
        asyncio.create_task(manager.broadcast_live(snapshot))

    engine.register_observer(broadcast_observer)

    app.state.engine = engine

    if settings.sim_auto_play:
        await engine.start(start_day=settings.sim_start_day)
        logger.info("Simulation auto-started (analytics engine active)")


@app.on_event("shutdown")
async def shutdown() -> None:
    if hasattr(app.state, "engine"):
        await app.state.engine.stop()
        logger.info("Simulation stopped on shutdown")


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket routes
# ─────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket) -> None:
    await ws_live(websocket, app.state.engine)


@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket) -> None:
    await ws_alerts(websocket)


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": settings.app_title,
        "version": settings.app_version,
        "docs": "/docs",
        "simulation": app.state.engine.state.to_dict() if hasattr(app.state, "engine") else {},
    }


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

