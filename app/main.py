"""FastAPI entrypoint for /app minimal bridge.

Adds diagnostic endpoints for ACS TLS troubleshooting (/acs/health, /acs/handshake).
"""
from __future__ import annotations
import time, asyncio, logging, os, socket, ssl
from urllib.parse import urlparse
try:  # Python 3.8+ standard
    from importlib import metadata as importlib_metadata  # type: ignore
except Exception:  # pragma: no cover
    import importlib_metadata  # type: ignore
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
from .logging_config import configure_logging
from .state import app_state
from .speech_session import SpeechSession
from .media_bridge import media_websocket

logger = logging.getLogger("app.main")
configure_logging()
app = FastAPI(title="Voice Call /app", version="0.1.0")
_speech: SpeechSession | None = None
_timeout_task: asyncio.Task | None = None

# ---- Diagnostics helpers ----
def _parse_acs_endpoint_host() -> str | None:
    cs = settings.acs_connection_string
    parts = cs.split(';')
    for p in parts:
        if p.lower().startswith('endpoint='):
            ep = p.split('=',1)[1].strip()
            if not ep:
                return None
            # ensure it has scheme for urlparse
            if not ep.startswith('http'):  # pragma: no cover
                ep = 'https://' + ep
            u = urlparse(ep)
            host = u.hostname
            return host
    return None

async def _tls_handshake(host: str, timeout: float = 5.0):
    result: dict = {"host": host}
    try:
        t0 = time.time()
        addr_info = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        result["dns_records"] = [ai[4][0] for ai in addr_info[:5]]
        result["dns_count"] = len(addr_info)
        sock = socket.create_connection((host, 443), timeout=timeout)
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            result["cipher"] = ssock.cipher()
            result["tls_version"] = ssock.version()
            cert = ssock.getpeercert()
            result["cert_subject"] = cert.get('subject')
            result["cert_notAfter"] = cert.get('notAfter')
        result["elapsed_ms"] = int((time.time()-t0)*1000)
        result["ok"] = True
    except Exception as e:  # pragma: no cover
        result["ok"] = False
        result["error"] = str(e)
    return result

class StartCallRequest(BaseModel):
    target_phone_number: str | None = Field(None, description="E.164 phone number overriding TARGET_PHONE_NUMBER")
    system_prompt: str | None = None
    simulate: bool = Field(False, description="If true, skip ACS API and simulate call locally (no PSTN).")

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

@app.get("/acs/health")
async def acs_health():
    host = _parse_acs_endpoint_host()
    if not host:
        return {"ok": False, "error": "Could not parse endpoint host", "conn_len": len(settings.acs_connection_string)}
    hs = await _tls_handshake(host)
    return {"connection_string_len": len(settings.acs_connection_string), **hs}

@app.get("/acs/handshake")
async def acs_handshake():  # alias returning raw handshake diagnostics
    return await acs_health()

@app.post("/call/start", response_model=StartCallResponse)
async def start_call(payload: StartCallRequest):
    """Initiate (or simulate) an outbound call.

    If simulate=True, no ACS SDK call is performed; a synthetic call id is generated
    and the Voice Live session is started immediately. Use this to exercise the
    media bridge & model pipeline locally without PSTN charges.
    """
    global _speech
    prompt = payload.system_prompt or settings.default_system_prompt
    dest = payload.target_phone_number or settings.target_phone_number or "SIMULATED"

    if payload.simulate:
        call_id = f"sim-{int(time.time()*1000)}"
        app_state.begin_call(call_id, prompt)
        # Start speech session immediately (normally triggered by CallConnected event)
        if not _speech or not _speech.active:
            _speech = SpeechSession()
            try:
                await asyncio.wait_for(_speech.connect(prompt), timeout=30.0)
            except Exception as e:
                logger.warning("Simulated speech session start failed: %s", e)
        return StartCallResponse(call_id=call_id, to=dest, prompt_used=prompt)

    # Real ACS path
    if not payload.target_phone_number and not settings.target_phone_number:
        raise HTTPException(400, "Destination number missing (provide target_phone_number or set TARGET_PHONE_NUMBER)")

    token = f"m-{int(time.time()*1000)}"
    # Always rely on APP_BASE_URL (user requested removing dynamic WEBSITE_HOSTNAME logic)
    base_url = settings.app_base_url.rstrip('/')
    if base_url.startswith("http://"):
        raise HTTPException(400, "APP_BASE_URL must be https for ACS callbacks")
    transport_url = f"wss://{base_url.split('://',1)[1]}/media/{token}"
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
        loop = asyncio.get_running_loop()
        # Offload blocking SDK call (azure-core uses 'requests') so event loop can still serve callback validation pings.
        def _do_create(with_media: bool = True):
            if with_media:
                return client.create_call(
                    target_participant=PhoneNumberIdentifier(dest),
                    callback_url=f"{base_url}/call/events",
                    source_caller_id_number=PhoneNumberIdentifier(settings.acs_outbound_caller_id),
                    media_streaming=media,
                    operation_context=token,
                )
            else:
                return client.create_call(
                    target_participant=PhoneNumberIdentifier(dest),
                    callback_url=f"{base_url}/call/events",
                    source_caller_id_number=PhoneNumberIdentifier(settings.acs_outbound_caller_id),
                    operation_context=token,
                )
        try:
            resp = await loop.run_in_executor(None, _do_create, True)
            logger.debug("create_call completed (media_streaming enabled)")
        except TypeError as te:  # signature mismatch edge-case
            logger.warning("create_call TypeError with media_streaming (%s) - retrying without", te)
            resp = await loop.run_in_executor(None, _do_create, False)
        except Exception as first_err:
            logger.warning("create_call initial attempt failed (%s) - retry once without media_streaming", first_err)
            try:
                resp = await loop.run_in_executor(None, _do_create, False)
            except Exception:
                raise first_err
    except AzureError as e:
        from azure.core.exceptions import ServiceRequestError
        if isinstance(e, ServiceRequestError):
            # Improve diagnostics: extract endpoint host, perform immediate handshake probe
            host = _parse_acs_endpoint_host()
            hs = None
            if host:
                try:
                    hs = await _tls_handshake(host)
                except Exception as he:  # pragma: no cover
                    hs = {"ok": False, "error": str(he)}
            # Attempt to surface internal client endpoint property variants
            internal_endpoint = None
            try:
                internal_endpoint = getattr(getattr(client, '_call_automation_client', None), 'endpoint', None)
            except Exception:  # pragma: no cover
                pass
            if not internal_endpoint:
                try:
                    internal_endpoint = getattr(getattr(client, '_call_automation_client', None), '_config', None) and getattr(client._call_automation_client._config, 'endpoint', None)
                except Exception:  # pragma: no cover
                    pass
            logger.error(
                "create_call TLS/network failure endpoint_internal=%s host=%s conn_str_len=%d first50=%r handshake=%s",
                internal_endpoint,
                host,
                len(settings.acs_connection_string),
                settings.acs_connection_string[:50],
                hs,
            )
        logger.exception("create_call failed: %s", e)
        raise HTTPException(502, "ACS call creation failed")
    call_props = getattr(resp, "call_connection_properties", None)
    call_id = getattr(call_props, "call_connection_id", None) or getattr(resp, "call_connection_id", None)
    if not call_id:
        raise HTTPException(500, "Could not determine call id")
    app_state.begin_call(call_id, prompt)
    # Optional early Voice Live session start (before CallConnected) for reduced initial latency
    if settings.voicelive_start_immediate and (not _speech or not _speech.active):
        _speech = SpeechSession()
        try:
            await asyncio.wait_for(_speech.connect(prompt), timeout=30.0)
            logger.info("Early Voice Live session started prior to CallConnected for call_id=%s", call_id)
        except Exception as e:
            logger.warning("Early Voice Live session start failed (will retry on CallConnected): %s", e)
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
        if et:
            logger.debug("call_events et=%s keys=%s", et, list(ev.keys())[:6])
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
            if (not _speech or not _speech.active):
                _speech = SpeechSession()
                prompt = app_state.current_call.get("prompt") if app_state.current_call else settings.voicelive_system_prompt or settings.default_system_prompt
                # Voice & model read from settings inside connect()
                await asyncio.wait_for(_speech.connect(prompt), timeout=30.0)
        if et.endswith("MediaStreamingStarted"):
            app_state.media_stream_started()
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
    await media_websocket(ws, token)

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
    # Log GA Voice Live readiness
    try:
        from .speech_session import VOICELIVE_AVAILABLE  # type: ignore
        # Package versions & OpenSSL
        try:
            az_core_v = importlib_metadata.version('azure-core')
        except Exception:
            az_core_v = 'unknown'
        try:
            callauto_v = importlib_metadata.version('azure-communication-callautomation')
        except Exception:
            callauto_v = 'unknown'
        try:
            voicelive_v = importlib_metadata.version('azure-ai-voicelive')
        except Exception:
            voicelive_v = 'missing'
        openssl_v = ssl.OPENSSL_VERSION
        host = _parse_acs_endpoint_host()
        logger.info(
            "startup voice_live_available=%s model=%s voice=%s endpoint=%s frame_bytes=%d az-core=%s callauto=%s voicelive=%s openssl=%s acs_host=%s",
            VOICELIVE_AVAILABLE,
            settings.voicelive_model,
            settings.voicelive_voice,
            settings.voicelive_endpoint,
            settings.media_frame_bytes,
            az_core_v,
            callauto_v,
            voicelive_v,
            openssl_v,
            host,
        )
    except Exception:
        logger.info("startup voice_live_available=unknown")
