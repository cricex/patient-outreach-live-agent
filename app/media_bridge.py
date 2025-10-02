"""WebSocket media bridge for `/app`.

Responsibilities:
 - Accept ACS media WebSocket and send an initial ack (unlocks audio from ACS)
 - Parse inbound JSON (AudioMetadata / AudioData) or raw binary frames
 - Slice audio into fixed 20 ms (640-byte) PCM16 frames and forward to the
     active Voice Live session (if inbound enabled)
 - Pull synthesized frames from the session and send back to ACS (if outbound enabled)

This module intentionally mirrors the minimal implementation from `/app2` so the
behavior is predictable and easy to reason about.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from . import main as app_main
from .config import settings
from .speech_session import SpeechSession
from .state import app_state

logger = logging.getLogger("app.media")

AUDIO_FRAME_BYTES = settings.media_frame_bytes  # 640 default

# Track all active sockets for broadcast of model audio (usually 1)
_active_media_sockets: set[WebSocket] = set()


async def media_websocket(ws: WebSocket, token: str) -> None:
    t0 = time.perf_counter_ns()
    offered = ws.headers.get("sec-websocket-protocol")
    subproto = offered.split(",")[0].strip() if offered else None
    await ws.accept(subprotocol=subproto)
    t1 = time.perf_counter_ns()
    try:
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.send_text('{"type":"ack"}')
    except Exception as exc:
        logger.warning("ack send failed token=%s err=%s", token, exc)
        return
    t2 = time.perf_counter_ns()
    logger.info("MEDIA handshake token=%s accept_us=%d ack_us=%d", token, (t1 - t0) // 1000, (t2 - t1) // 1000)

    _active_media_sockets.add(ws)
    app_state.media_ws_open()

    async def outbound_loop() -> None:
        while True:
            await asyncio.sleep(settings.media_frame_interval_ms / 1000.0)
            speech = app_main._speech
            if not (speech and speech.active and settings.media_enable_voicelive_out and settings.media_bidirectional):
                continue
            frame = await speech.get_next_outbound_frame()
            if not frame:
                continue
            try:
                if settings.media_out_format == "binary":
                    await ws.send_bytes(frame)
                else:
                    b64 = base64.b64encode(frame).decode("ascii")
                    payload = json.dumps({"kind": "AudioData", "audioData": {"data": b64}})
                    await ws.send_text(payload)
                app_state.media_out_audio(1, len(frame))
            except Exception as exc:
                logger.debug("outbound frame send err: %s", exc)
                return

    outbound_task = asyncio.create_task(outbound_loop())

    audio_chunk = AUDIO_FRAME_BYTES
    try:
        while True:
            current_speech_session = app_main._speech
            incoming = await ws.receive()
            if incoming.get("type") == "websocket.disconnect":
                break
            text = incoming.get("text")
            data = incoming.get("bytes")
            if text:
                try:
                    parsed = json.loads(text)
                except Exception:
                    continue
                kind = parsed.get("kind") or parsed.get("type")
                if kind == "AudioMetadata":
                    continue
                b64 = None
                if isinstance(parsed.get("audioData"), dict) and isinstance(parsed["audioData"].get("data"), str):
                    b64 = parsed["audioData"]["data"]
                elif isinstance(parsed.get("data"), str) and kind in {"AudioData", "AudioChunk"}:
                    b64 = parsed["data"]
                if b64:
                    try:
                        pcm = base64.b64decode(b64)
                    except Exception:
                        continue
                    await _handle_inbound_pcm(pcm, current_speech_session, audio_chunk)
                continue
            if data:
                await _handle_inbound_pcm(data, current_speech_session, audio_chunk)
    except Exception as exc:
        logger.debug("media ws loop err token=%s err=%s", token, exc)
    finally:
        try:
            outbound_task.cancel()
        except Exception:
            pass
        try:
            _active_media_sockets.discard(ws)
        except Exception:
            pass
        logger.info("MEDIA closed token=%s", token)


async def _handle_inbound_pcm(pcm: bytes, speech: SpeechSession | None, frame_bytes: int) -> None:
    if not pcm:
        return
    frames = len(pcm) // frame_bytes
    if frames:
        app_state.media_in_audio(frames, len(pcm))
        if app_state.media["inFrames"] % 100 == 0:
            logger.debug(
                "inbound frames=%d bytes_in=%d",
                app_state.media["inFrames"],
                app_state.media["audio_bytes_in"],
            )
    if not (speech and speech.active and settings.media_enable_voicelive_in):
        return
    for offset in range(0, frames * frame_bytes, frame_bytes):
        frame = pcm[offset:offset + frame_bytes]
        try:
            await speech.send_input_frame(frame)
        except Exception as exc:
            logger.debug("speech frame send err: %s", exc)
            break
