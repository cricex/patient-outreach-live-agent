"""FastAPI entrypoint for /app2 minimal bridge."""
from __future__ import annotations
import time, asyncio, logging, os
from fastapi import FastAPI, WebSocket, HTTPException, Request
from azure.communication.callautomation import (
    CallAutomationClient,
    PhoneNumberIdentifier,
    MediaStreamingOptions,
    StreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
)
from azure.core.exceptions import AzureError
from pydantic import BaseModel, Field
from .config import settings
from .state import app_state
from .speech_session import SpeechSession
from .media_bridge import media_websocket

logger = logging.getLogger("app2.main")
app = FastAPI(title="Voice Call /app2", version="0.1.0")
_speech: SpeechSession | None = None
_timeout_task: asyncio.Task | None = None

class StartCallRequest(BaseModel):
    target_phone_number: str | None = Field(None, description="E.164 phone number overriding TARGET_PHONE_NUMBER")
    system_prompt: str | None = None

class StartCallResponse(BaseModel):
    call_id: str
    to: str
    prompt_used: str

# ---- Helpers ----

def _call_client() -> CallAutomationClient:
    return CallAutomationClient.from_connection_string(settings.acs_connection_string)

# ---- Endpoints ----
@app.get("/health")
async def health():
    return "ok"

@app.get("/status")
async def status():
    return app_state.snapshot()

@app.post("/call/start", response_model=StartCallResponse)
async def start_call(payload: StartCallRequest):
    prompt = payload.system_prompt or settings.default_system_prompt
    dest = payload.target_phone_number or settings.target_phone_number
    if not dest:
        raise HTTPException(400, "Destination number missing")
    token = f"m-{int(time.time()*1000)}"
    # Determine public base URL (supports Azure App Service WEBSITE_HOSTNAME)
    azure_host = os.getenv("WEBSITE_HOSTNAME")
    if azure_host:
        base_url = f"https://{azure_host}".rstrip('/')
    else:
        base_url = settings.app_base_url.rstrip('/')
        if base_url.startswith("http://"):
            raise HTTPException(400, "APP_BASE_URL must be https for ACS callbacks")
    transport_url = f"wss://{base_url.split('://',1)[1]}/media/{token}"  # reuse host
    media = MediaStreamingOptions(
        transport_url=transport_url,
        transport_type=StreamingTransportType.WEBSOCKET,
        content_type=MediaStreamingContentType.AUDIO,
        audio_channel_type=(MediaStreamingAudioChannelType.MIXED if settings.media_audio_channel_type == "mixed" else MediaStreamingAudioChannelType.UNMIXED),
        enable_bidirectional=True,
        audio_format="Pcm16KMono",
        start_media_streaming=settings.media_start_at_create,
    )
    try:
        client = _call_client()
        resp = client.create_call(
            target_participant=PhoneNumberIdentifier(dest),
            callback_url=f"{base_url}/call/events",
            source_caller_id_number=PhoneNumberIdentifier(settings.acs_outbound_caller_id),
            media_streaming=media,
            operation_context=token,
        )
    except AzureError as e:
        logger.exception("create_call failed: %s", e)
        raise HTTPException(502, "ACS call creation failed")
    call_props = getattr(resp, "call_connection_properties", None)
    call_id = getattr(call_props, "call_connection_id", None) or getattr(resp, "call_connection_id", None)
    if not call_id:
        raise HTTPException(500, "Could not determine call id")
    app_state.begin_call(call_id, prompt)
    return StartCallResponse(call_id=call_id, to=dest, prompt_used=prompt)

@app.post("/call/hangup")
async def hangup():
    if not app_state.current_call:
        raise HTTPException(409, "No active call")
    call_id = app_state.current_call["call_id"]
    try:
        client = _call_client()
        conn = client.get_call_connection(call_id)
        conn.hang_up(is_for_everyone=True)
    except Exception:
        logger.debug("hangup API failed (continuing)")
    app_state.end_call(call_id, reason="ManualHangup")
    global _speech
    if _speech and _speech.active:
        await _speech.close()
        app_state.end_voicelive("Hangup")
        _speech = None
    return {"ok": True, "call_id": call_id}

@app.post("/call/events")
async def call_events(request: Request):
    global _speech
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    events = body if isinstance(body, list) else [body]
    ended = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        et = ev.get("type") or ev.get("eventType") or ev.get("publicEventType")
        data = ev.get("data") or {}
        call_id = data.get("callConnectionId") or ev.get("callConnectionId")
        if not et or not call_id:
            continue
        app_state.update_last_event()
        if et.endswith("CallConnected") and app_state.current_call and app_state.current_call.get("call_id") == call_id:
            # start media if not auto
            if not settings.media_start_at_create:
                try:
                    client = _call_client(); client.get_call_connection(call_id).start_media_streaming()
                except Exception as e:
                    logger.warning("start_media_streaming failed: %s", e)
            # start speech session
            if settings.enable_voice_live and (not _speech or not _speech.active):
                _speech = SpeechSession(frame_bytes=settings.media_frame_bytes)
                prompt = app_state.current_call.get("prompt") if app_state.current_call else settings.default_system_prompt
                await asyncio.wait_for(_speech.connect(settings.default_voice or "en-US-JennyNeural", prompt), timeout=15.0)
                app_state.begin_voicelive(_speech.session_id, _speech.voice or (settings.default_voice or "voice"))
        if et.endswith("CallDisconnected") or et.endswith("CallEnded"):
            app_state.end_call(call_id, reason=et)
            if _speech and _speech.active:
                await _speech.close(); app_state.end_voicelive(et)
                _speech = None
            ended.append(et)
    return {"ok": True, "processed": len(events), "ended": ended}

@app.websocket("/media/{token}")
async def media_ws(ws: WebSocket, token: str):
    global _speech
    await media_websocket(ws, token, _speech)

# ---- Background timeout watcher ----
async def _timeout_watcher():
    global _speech
    while True:
        await asyncio.sleep(5)
        cur = app_state.current_call
        if not cur: continue
        started = cur.get("started_at")
        if not started: continue
        elapsed = time.time() - started
        if elapsed > settings.call_timeout_sec:
            call_id = cur.get("call_id")
            try:
                client = _call_client(); client.get_call_connection(call_id).hang_up(is_for_everyone=True)
            except Exception: pass
            app_state.end_call(call_id, reason="Timeout")
            if _speech and _speech.active:
                await _speech.close(); app_state.end_voicelive("Timeout")
                _speech = None
        elif app_state.last_event_at and (time.time() - app_state.last_event_at) > settings.call_idle_timeout_sec:
            call_id = cur.get("call_id")
            app_state.end_call(call_id, reason="Idle")
            if _speech and _speech.active:
                await _speech.close(); app_state.end_voicelive("Idle")
                _speech = None

@app.on_event("startup")
async def _startup():
    global _timeout_task
    _timeout_task = asyncio.create_task(_timeout_watcher())
