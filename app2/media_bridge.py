"""WebSocket media bridge for /app2.

Responsibilities:
 - Accept ACS media WS, send initial ack (required to unlock audio payloads)
 - Parse inbound JSON metadata + audio frames (base64) or raw binary frames
 - Slice into 20ms frames (frame_bytes) and forward to SpeechSession (if enabled)
 - Pull outbound frames from SpeechSession and send to ACS if bidirectional enabled

This is a *minimal* version without adaptive pacing or VAD heuristics.
"""
from __future__ import annotations
import asyncio, base64, json, logging, time
from fastapi import WebSocket
from starlette.websockets import WebSocketState
from .state import app_state
from .config import settings
from .speech_session import SpeechSession

logger = logging.getLogger("app2.media")

AUDIO_FRAME_BYTES = settings.media_frame_bytes  # 640 default

# Track all active sockets for broadcast of model audio (usually 1)
_active_media_sockets: set[WebSocket] = set()

async def media_websocket(ws: WebSocket, token: str, speech: SpeechSession | None):
    t0 = time.perf_counter_ns()
    offered = ws.headers.get("sec-websocket-protocol")
    subproto = offered.split(",")[0].strip() if offered else None
    await ws.accept(subprotocol=subproto)
    t1 = time.perf_counter_ns()
    try:
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.send_text('{"type":"ack"}')
    except Exception as e:
        logger.warning("ack send failed token=%s err=%s", token, e)
        return
    t2 = time.perf_counter_ns()
    logger.info("MEDIA2 handshake token=%s accept_us=%d ack_us=%d", token, (t1-t0)//1000, (t2-t1)//1000)

    _active_media_sockets.add(ws)
    app_state.media_ws_open()

    async def outbound_loop():
        while True:
            await asyncio.sleep(settings.media_frame_interval_ms / 1000.0)
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
            except Exception as e:
                logger.debug("outbound frame send err: %s", e)
                return

    ob_task = asyncio.create_task(outbound_loop())

    AUDIO_CHUNK = AUDIO_FRAME_BYTES
    try:
        while True:
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
                    continue  # ignore metadata here (could capture sample rate)
                # audio container variants
                b64 = None
                if isinstance(parsed.get("audioData"), dict) and isinstance(parsed["audioData"].get("data"), str):
                    b64 = parsed["audioData"]["data"]
                elif isinstance(parsed.get("data"), str) and kind in {"AudioData","AudioChunk"}:
                    b64 = parsed["data"]
                if b64:
                    try:
                        pcm = base64.b64decode(b64)
                    except Exception:
                        continue
                    await _handle_inbound_pcm(pcm, speech, AUDIO_CHUNK)
                continue
            if data:
                await _handle_inbound_pcm(data, speech, AUDIO_CHUNK)
    except Exception as e:
        logger.debug("media ws loop err token=%s err=%s", token, e)
    finally:
        try: ob_task.cancel();
        except Exception: pass
        try: _active_media_sockets.discard(ws)
        except Exception: pass
        logger.info("MEDIA2 closed token=%s", token)

async def _handle_inbound_pcm(pcm: bytes, speech: SpeechSession | None, frame_bytes: int):
    if not pcm:
        return
    frames = len(pcm) // frame_bytes
    if frames:
        app_state.media_in_audio(frames, len(pcm))
    if not (speech and speech.active and settings.media_enable_voicelive_in):
        return
    # iterate fixed-size frames only (drop remainder)
    for off in range(0, frames * frame_bytes, frame_bytes):
        frame = pcm[off:off+frame_bytes]
        try:
            await speech.send_input_frame(frame)
        except Exception as e:
            logger.debug("speech frame send err: %s", e)
            break
