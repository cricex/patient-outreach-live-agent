"""WebSocket media bridge for ACS ↔ Voice Live audio.

Accepts an ACS media WebSocket, runs concurrent inbound/outbound loops,
and bridges PCM audio between ACS and the active SpeechService.

In v2 this module has no global state — it receives the SpeechService
and AppState via the handle_media_ws() function parameters.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from ..config import settings
from ..models.state import AppState

logger = logging.getLogger("app.media")

FRAME_BYTES = settings.media_frame_bytes


async def handle_media_ws(
    ws: WebSocket,
    token: str,
    get_speech,  # Callable that returns the current SpeechService | None
    app_state: AppState,
    session_id: str = "default",
) -> None:
    """Main media WebSocket handler.

    Args:
        ws: The ACS WebSocket connection.
        token: Media session token from the URL path.
        get_speech: Callable returning the current SpeechService (or None).
            This avoids importing or referencing global state.
        app_state: Application state for recording media metrics.
        session_id: Auth session this media stream belongs to.
    """
    t0 = time.perf_counter_ns()

    # Accept with subprotocol negotiation
    offered = ws.headers.get("sec-websocket-protocol")
    subproto = offered.split(",")[0].strip() if offered else None
    await ws.accept(subprotocol=subproto)

    # Send ack to unlock ACS audio stream
    try:
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.send_text('{"type":"ack"}')
    except Exception as exc:
        logger.warning("ack send failed token=%s: %s", token, exc)
        return

    t1 = time.perf_counter_ns()
    logger.info("MEDIA open token=%s handshake_us=%d", token, (t1 - t0) // 1000)
    media = app_state.get_media(session_id)
    media.ws_connected_at = time.time()

    # Concurrent outbound loop (Voice Live → ACS) with wall-clock-aligned timing
    async def outbound_loop() -> None:
        interval = settings.media_frame_interval_ms / 1000.0
        loop = asyncio.get_running_loop()
        next_send = loop.time()
        while True:
            next_send += interval
            now = loop.time()
            delay = next_send - now
            if delay > 0:
                await asyncio.sleep(delay)
            elif delay < -1.0:
                # Clock jumped or massive lag — reset to avoid burst-sending
                next_send = loop.time()
                continue
            speech = get_speech()
            if not (speech and speech.active and settings.media_enable_voicelive_out):
                continue
            frame = await speech.get_next_output_frame()
            if not frame:
                continue
            try:
                b64 = base64.b64encode(frame).decode("ascii")
                payload = json.dumps({"kind": "AudioData", "audioData": {"data": b64}})
                await ws.send_text(payload)
                app_state.get_media(session_id).record_outbound(1, len(frame))
            except Exception as exc:
                logger.debug("outbound send error: %s", exc)
                return

    outbound_task = asyncio.create_task(outbound_loop())

    # Inbound loop (ACS → Voice Live)
    try:
        while True:
            speech = get_speech()
            incoming = await ws.receive()

            if incoming.get("type") == "websocket.disconnect":
                break

            text = incoming.get("text")
            raw_bytes = incoming.get("bytes")

            if text:
                pcm = _extract_pcm_from_json(text)
                if pcm:
                    await _forward_inbound(pcm, speech, app_state, session_id)
                continue

            if raw_bytes:
                await _forward_inbound(raw_bytes, speech, app_state, session_id)

    except Exception as exc:
        logger.debug("media ws loop error token=%s: %s", token, exc)
    finally:
        outbound_task.cancel()
        try:
            await outbound_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("MEDIA closed token=%s", token)


def _extract_pcm_from_json(text: str) -> bytes | None:
    """Parse ACS JSON message and extract PCM audio bytes."""
    try:
        parsed = json.loads(text)
    except Exception:
        return None

    kind = parsed.get("kind") or parsed.get("type")
    if kind == "AudioMetadata":
        return None

    # ACS sends base64 audio in two possible shapes
    b64 = None
    audio_data = parsed.get("audioData")
    if isinstance(audio_data, dict) and isinstance(audio_data.get("data"), str):
        b64 = audio_data["data"]
    elif isinstance(parsed.get("data"), str) and kind in {"AudioData", "AudioChunk"}:
        b64 = parsed["data"]

    if b64:
        try:
            return base64.b64decode(b64)
        except Exception:
            return None
    return None


async def _forward_inbound(
    pcm: bytes,
    speech,  # SpeechService | None
    app_state: AppState,
    session_id: str = "default",
) -> None:
    """Slice PCM into frames and forward to Voice Live."""
    if not pcm:
        return

    frame_count = len(pcm) // FRAME_BYTES
    if frame_count:
        app_state.get_media(session_id).record_inbound(frame_count, len(pcm))

    if not (speech and speech.active and settings.media_enable_voicelive_in):
        return

    # Send each frame individually to Voice Live
    for offset in range(0, frame_count * FRAME_BYTES, FRAME_BYTES):
        frame = pcm[offset : offset + FRAME_BYTES]
        try:
            await speech.send_audio(frame)
        except Exception as exc:
            logger.debug("speech frame send error: %s", exc)
            break
