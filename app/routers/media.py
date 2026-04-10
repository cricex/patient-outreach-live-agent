"""WebSocket media route for ACS audio bridge."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket

from ..models.state import app_state
from ..services.call_manager import call_manager
from ..services.media_bridge import handle_media_ws

router = APIRouter(tags=["media"])


@router.websocket("/media/{token}")
async def media_ws(ws: WebSocket, token: str):
    """Bidirectional ACS ↔ Voice Live audio bridge."""
    await handle_media_ws(
        ws=ws,
        token=token,
        get_speech=call_manager.get_speech,
        app_state=app_state,
    )
