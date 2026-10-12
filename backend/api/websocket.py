"""
api/websocket.py — WebSocket handlers for real-time data streaming.

Two channels:
  /ws/live   — streams sensor readings + health every tick (high-frequency)
  /ws/alerts — streams new alerts as they fire (event-driven)

Uses FastAPI's native WebSocket support. Handles multiple concurrent
connections with a simple broadcast registry pattern.
Implements graceful disconnection and exponential-backoff hints to clients.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from simulator.engine import SimulationEngine

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Registry of active WebSocket connections per channel."""

    def __init__(self) -> None:
        self._live: set[WebSocket] = set()
        self._alerts: set[WebSocket] = set()

    async def connect_live(self, ws: WebSocket) -> None:
        await ws.accept()
        self._live.add(ws)
        logger.info("WS /live connected (total: %d)", len(self._live))

    async def connect_alerts(self, ws: WebSocket) -> None:
        await ws.accept()
        self._alerts.add(ws)
        logger.info("WS /alerts connected (total: %d)", len(self._alerts))

    def disconnect(self, ws: WebSocket) -> None:
        self._live.discard(ws)
        self._alerts.discard(ws)

    async def broadcast_live(self, payload: dict) -> None:
        await self._broadcast(self._live, payload)

    async def broadcast_alert(self, payload: dict) -> None:
        await self._broadcast(self._alerts, payload)

    async def _broadcast(self, connections: set[WebSocket], payload: dict) -> None:
        dead: set[WebSocket] = set()
        message = json.dumps(payload)
        for ws in connections.copy():
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def ws_live(websocket: WebSocket, engine: "SimulationEngine") -> None:
    """
    Stream live sensor readings + health scores.
    Sends one message per engine tick containing the full snapshot.
    """
    await manager.connect_live(websocket)
    try:
        # Send current state immediately on connect
        snapshot = engine.get_live_snapshot()
        await websocket.send_text(json.dumps(snapshot))

        # Then listen for client messages (ping/pong or control commands)
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Client can send {"cmd": "ping"} to keep connection alive
                if data:
                    msg = json.loads(data)
                    if msg.get("cmd") == "ping":
                        await websocket.send_text(json.dumps({"cmd": "pong"}))
            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_text(json.dumps({"cmd": "keepalive"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WS /live disconnected")


async def ws_alerts(websocket: WebSocket) -> None:
    """
    Event-driven alert stream.
    Alerts are pushed by the analytics engine via manager.broadcast_alert().
    """
    await manager.connect_alerts(websocket)
    try:
        while True:
            # Just keep connection open; analytics broadcasts to all /alerts clients
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                if data:
                    msg = json.loads(data)
                    if msg.get("cmd") == "ping":
                        await websocket.send_text(json.dumps({"cmd": "pong"}))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"cmd": "keepalive"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WS /alerts disconnected")
