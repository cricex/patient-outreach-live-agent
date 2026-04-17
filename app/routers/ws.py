"""WebSocket endpoints for real-time UI streaming.

Two endpoints:
- /ws/diagnostics — streams DiagnosticEvent objects from the event bus
- /ws/call-status — polls app_state.snapshot() every second for call status
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from ..auth import get_session_id, is_valid_token
from ..models.state import app_state
from ..services.event_bus import event_bus

logger = logging.getLogger("app.ws")
router = APIRouter(tags=["websocket"])


async def _ws_auth(ws: WebSocket) -> str | None:
    """Check auth token from query params before accepting WebSocket.

    BaseHTTPMiddleware only covers HTTP requests — WebSocket connections
    bypass it entirely, so each WS handler must auth independently.

    Returns the session_id on success, or None (and closes WS) on failure.
    """
    token = ws.query_params.get("token", "")
    if not is_valid_token(token):
        await ws.close(code=1008, reason="Authentication required")
        return None
    return get_session_id(token)


@router.websocket("/ws/diagnostics")
async def diagnostics_ws(ws: WebSocket) -> None:
    """Stream diagnostic events to the UI in real-time.

    On connect, sends recent event buffer so the UI can catch up.
    Then streams new events as they arrive from the event bus.
    Events are filtered to the requesting user's session.
    """
    session_id = await _ws_auth(ws)
    if session_id is None:
        return
    await ws.accept()
    sub_id, queue = event_bus.subscribe(session_id)
    logger.info("Diagnostics WS connected sub_id=%d session=%s", sub_id, session_id)

    try:
        # Send recent events so UI catches up
        recent = event_bus.get_recent(session_id)
        if recent:
            await ws.send_text(json.dumps({"type": "history", "events": recent}))

        # Stream new events
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                if ws.application_state != WebSocketState.CONNECTED:
                    break
                await ws.send_text(json.dumps(event.to_dict()))
            except asyncio.TimeoutError:
                # Send keepalive ping to detect dead connections
                try:
                    await ws.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("diagnostics ws error: %s", exc)
    finally:
        event_bus.unsubscribe(sub_id)
        logger.info("Diagnostics WS disconnected sub_id=%d", sub_id)


@router.websocket("/ws/call-status")
async def call_status_ws(ws: WebSocket) -> None:
    """Stream call status snapshots to the UI every second.

    Simpler than diagnostics — just polls app_state.snapshot()
    and sends the full state for this session.
    """
    session_id = await _ws_auth(ws)
    if session_id is None:
        return
    await ws.accept()
    logger.info("Call status WS connected session=%s", session_id)

    try:
        while True:
            if ws.application_state != WebSocketState.CONNECTED:
                break
            snapshot = app_state.snapshot(session_id)
            await ws.send_text(json.dumps(snapshot, default=str))
            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("call-status ws error: %s", exc)
    finally:
        logger.info("Call status WS disconnected")
