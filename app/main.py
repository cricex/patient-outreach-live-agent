"""FastAPI endpoints orchestrating ACS call automation and Voice Live streaming."""

from fastapi import FastAPI, HTTPException, Request
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict
from starlette.websockets import WebSocketState
from azure.communication.callautomation import (
    CallAutomationClient,
    PhoneNumberIdentifier,
    MediaStreamingOptions,
    StreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    AudioFormat,
)
try:
    from azure.communication.callautomation import __version__ as callautomation_version
except Exception:  # pragma: no cover
    callautomation_version = "unknown"
from azure.core.exceptions import AzureError
from .state import app_state
from .config import settings
import logging
import asyncio
import time
from .voice_live import VoiceLiveSession, run_receive
import base64, json as _json
import os
from logging.handlers import RotatingFileHandler

logger = logging.getLogger("voice_call")

# --- Logging configuration (supports DEBUG file capture) ---
_env_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
_log_dir = os.getenv("LOG_DIR", "logs")
_log_file_level_name = os.getenv("LOG_FILE_LEVEL", "DEBUG").upper()
try:
    _log_file_level = getattr(logging, _log_file_level_name)
except AttributeError:
    _log_file_level = logging.DEBUG
_log_file_force = os.getenv("LOG_FILE_ENABLE", "false").lower() == "true"
try:
    _log_file_max_kb = int(os.getenv("LOG_FILE_MAX_KB", "5120"))
except ValueError:
    _log_file_max_kb = 5120
if _log_file_max_kb < 0:
    _log_file_max_kb = 0
try:
    _log_file_backup_count = int(os.getenv("LOG_FILE_BACKUP_COUNT", "3"))
except ValueError:
    _log_file_backup_count = 3
if _log_file_backup_count < 0:
    _log_file_backup_count = 0
_root = logging.getLogger()
if not _root.handlers:
    # Base stream handler (console)
    stream_handler = logging.StreamHandler()
    try:
        stream_handler.setLevel(getattr(logging, "INFO" if _env_log_level == "DEBUG" else _env_log_level))
    except Exception:
        stream_handler.setLevel(logging.INFO)
    fmt = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    stream_handler.setFormatter(fmt)
    _root.addHandler(stream_handler)
    # Root level: full requested level so file handler (if any) gets everything
    try:
        _root.setLevel(getattr(logging, _env_log_level, logging.INFO))
    except Exception:
        _root.setLevel(logging.INFO)

    # If DEBUG requested, also write detailed logs to rotating file
    if (_env_log_level == "DEBUG" or _log_file_force) and _log_file_max_kb:
        try:
            os.makedirs(_log_dir, exist_ok=True)
            file_path = os.path.join(_log_dir, "debug.log")
            max_bytes = max(_log_file_max_kb, 1) * 1024
            file_handler = RotatingFileHandler(
                file_path,
                maxBytes=max_bytes,
                backupCount=_log_file_backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(_log_file_level)
            file_fmt = logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(filename)s:%(lineno)d | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S"
            )
            file_handler.setFormatter(file_fmt)
            _root.addHandler(file_handler)
            logger.info(
                "FILE logging enabled path=%s level=%s max_kb=%s backups=%s force=%s",
                file_path,
                logging.getLevelName(_log_file_level),
                _log_file_max_kb,
                _log_file_backup_count,
                _log_file_force,
            )
        except Exception as fh_err:
            logger.warning("Failed to initialize debug file logging: %s", fh_err)

# Reduce verbosity of third-party libs if desired
for noisy in ["websockets.client", "websockets.protocol"]:
    try:
        logging.getLogger(noisy).setLevel(logging.INFO if _env_log_level != "DEBUG" else logging.DEBUG)
    except Exception:
        pass

app = FastAPI(title="Voice Call PoC", version="0.1.0")

_voice_live_session: VoiceLiveSession | None = None
_voice_live_pacer_task: asyncio.Task | None = None
_active_media_sockets: set[WebSocket] = set()


class StartCallRequest(BaseModel):
    """Inbound payload for launching a phone call via ACS."""
    target_phone_number: Optional[str] = Field(None, description="Destination PSTN number in E.164 format; overrides TARGET_PHONE_NUMBER env var.")
    system_prompt: Optional[str] = Field(None, description="Custom system prompt for this call; overrides DEFAULT_SYSTEM_PROMPT env var.")


class StartCallResponse(BaseModel):
    """Response describing the call connection that ACS created."""
    call_id: str
    prompt_used: str
    to: str


def _call_client() -> CallAutomationClient:
    """Create a Call Automation client while logging redacted connection diagnostics."""
    # Diagnostic logging without exposing full secret: show hash & length
    cs = settings.acs_connection_string
    import hashlib
    redacted = None
    try:
        h = hashlib.sha256(cs.encode()).hexdigest()[:12]
        redacted = f"endpoint_present={'endpoint=' in cs};accesskey_present={'accesskey=' in cs};len={len(cs)};sha256_12={h}"
    except Exception:
        redacted = "<hash_failed>"
    logger.info("ACS CONNECTION STRING DIAG %s", redacted)
    return CallAutomationClient.from_connection_string(cs)


@app.get("/health")
async def health() -> str:
    """Simple readiness probe for platform health checks."""
    return "ok"


@app.get("/status")
async def status():
    """Expose a snapshot of current call, voice live, and media metrics."""
    return app_state.snapshot()


@app.get("/debug/callback-base")
async def debug_callback_base():
    """Return the callback base URL seen by the process for troubleshooting tunnels."""
    import os
    runtime_base = os.getenv("APP_BASE_URL") or settings.app_base_url
    return {"app_base_url_runtime": runtime_base}


@app.post("/call/start", response_model=StartCallResponse)
async def start_call(payload: StartCallRequest):
    """Place an outbound ACS call and prime media streaming for the Voice Live bridge."""
    prompt = payload.system_prompt or settings.default_system_prompt
    try:
        client = _call_client()
        resolved_to = payload.target_phone_number or settings.target_phone_number
        if not resolved_to:
            raise HTTPException(status_code=400, detail="Destination number missing: provide 'target_phone_number' in request or set TARGET_PHONE_NUMBER env.")
        target = PhoneNumberIdentifier(resolved_to)
        # Allow runtime override or detect Azure-provided hostname
        import os
        azure_hostname = os.getenv("WEBSITE_HOSTNAME")
        if azure_hostname:
            runtime_base = f"https://{azure_hostname}"
        else:
            runtime_base = os.getenv("APP_BASE_URL") or settings.app_base_url
        callback_base = runtime_base.rstrip('/')
        # In a deployed environment, we can be more lenient on the http check if it's behind a TLS-terminating proxy
        if not azure_hostname and callback_base.startswith('http://'):
            raise HTTPException(status_code=400, detail="APP_BASE_URL must be https (public) for ACS callbacks; use an HTTPS tunnel or deploy to Azure.")
        if not azure_hostname and ('localhost' in callback_base or '127.0.0.1' in callback_base):
            raise HTTPException(status_code=400, detail="APP_BASE_URL cannot be localhost for ACS callbacks; expose a public https URL.")
        from urllib.parse import urlparse as _urlparse
        public_host = _urlparse(callback_base).netloc
        opaque_token = f"m-{int(time.time()*1000)}"
        token_mode = settings.media_token_mode
        if token_mode == "callid":
            # Not supported with SDK 1.5.0 (start_media_streaming has no media_streaming parameter); fallback to opaque
            logger.warning("MEDIA TOKEN MODE callid requested but unsupported in SDK 1.5.0; falling back to opaque create-time configuration")
            token_mode = "opaque"
        transport_url = f"wss://{public_host}/media/{opaque_token}"
        channel_enum = (
            MediaStreamingAudioChannelType.MIXED
            if settings.media_audio_channel_type == "mixed"
            else MediaStreamingAudioChannelType.UNMIXED
        )
        media_streaming = MediaStreamingOptions(
            transport_url=transport_url,
            transport_type=StreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=channel_enum,
            enable_bidirectional=True,
            audio_format="Pcm16KMono",
            start_media_streaming=settings.media_start_at_create,
        )
        logger.info(
            "MEDIA STREAM CONFIG mode=%s bidirectional=%s start_at_create=%s channel=%s transport_url=%s",
            token_mode,
            settings.media_bidirectional,
            settings.media_start_at_create,
            settings.media_audio_channel_type,
            transport_url,
        )
        logger.info(
            "SDK create_call prep transport_url=%s sdk_version=%s", transport_url, callautomation_version
        )
        try:
            create_response = client.create_call(
                target_participant=target,
                callback_url=f"{callback_base}/call/events",
                source_caller_id_number=PhoneNumberIdentifier(settings.acs_outbound_caller_id),
                media_streaming=media_streaming,
                operation_context=opaque_token,
            )
            logger.info("SDK create_call used media_streaming=True transport_url=%s", transport_url)
        except TypeError as sig_err:
            # Fallback: older/no media_streaming support – retry without it
            logger.warning("create_call retry without media_streaming due to TypeError: %s", sig_err)
            create_response = client.create_call(
                target_participant=target,
                callback_url=f"{callback_base}/call/events",
                source_caller_id_number=PhoneNumberIdentifier(settings.acs_outbound_caller_id),
                operation_context=opaque_token,
            )
            logger.info("SDK create_call used media_streaming=False (fallback) transport_url=%s", transport_url)
        # SDK shape fallback handling
        props = getattr(create_response, "call_connection_properties", None)
        call_connection_id = None
        if props is not None:
            call_connection_id = getattr(props, "call_connection_id", None)
        if not call_connection_id:
            # Try direct attribute if SDK differs
            call_connection_id = getattr(create_response, "call_connection_id", None)
        if not call_connection_id:
            raise RuntimeError("Could not determine call_connection_id from create_call response")
        app_state.begin_call(call_connection_id, prompt)
        logger.info("Placed outbound call call_id=%s to=%s", call_connection_id, resolved_to)
        return StartCallResponse(call_id=call_connection_id, prompt_used=prompt, to=resolved_to)
    except AzureError as e:
        msg = f"ACS create_call failed: {e}"
        logger.exception(msg)
        app_state.set_error(msg)
        raise HTTPException(status_code=502, detail="Call placement failed")


@app.post("/call/hangup")
async def hangup_call():
    """Hang up the active ACS call and tear down any Voice Live resources."""
    global _voice_live_session
    current = app_state.current_call
    if not current:
        raise HTTPException(status_code=409, detail="No active call")
    call_id = current.get("call_id")
    try:
        client = _call_client()
        call_conn = client.get_call_connection(call_id)
        call_conn.hang_up(is_for_everyone=True)
    except Exception as e:  # broad catch to still end state
        logger.warning("Hangup API failed for call_id=%s: %s", call_id, e)
    app_state.end_call(call_id, reason="ManualHangup")
    # Close Voice Live if open
    if _voice_live_session and _voice_live_session.active:
        await _voice_live_session.close()
        app_state.end_voicelive("CallHangup")
    _voice_live_session = None
    return {"ok": True, "call_id": call_id, "ended": True}


async def _timeout_watcher():
    """Background task enforcing overall call duration and idle timeouts."""
    global _voice_live_session
    while True:
        await asyncio.sleep(5)
        try:
            current = app_state.current_call
            if not current:
                continue
            started = current.get("started_at")
            if not started:
                continue
            last_event_age = None
            if app_state.last_event_at:
                last_event_age = time.time() - app_state.last_event_at
            elapsed = time.time() - started
            if elapsed > settings.call_timeout_sec:
                cid = current.get("call_id")
                logger.info("Call timeout reached (%.1fs > %ss) call_id=%s", elapsed, settings.call_timeout_sec, cid)
                try:
                    client = _call_client()
                    call_conn = client.get_call_connection(cid)
                    call_conn.hang_up(is_for_everyone=True)
                except Exception as e:
                    logger.warning("Timeout hangup API failed call_id=%s: %s", cid, e)
                app_state.end_call(cid, reason="Timeout")
                # Close Voice Live if open
                if _voice_live_session and _voice_live_session.active:
                    await _voice_live_session.close()
                    app_state.end_voicelive("CallTimeout")
                _voice_live_session = None
            # Idle timeout uses dedicated setting
            elif last_event_age and last_event_age > settings.call_idle_timeout_sec:
                cid = current.get("call_id")
                logger.info("Call idle timeout (no events %.1fs > %ss) call_id=%s", last_event_age, settings.call_idle_timeout_sec, cid)
                app_state.end_call(cid, reason="IdleTimeout")
                if _voice_live_session and _voice_live_session.active:
                    await _voice_live_session.close()
                    app_state.end_voicelive("IdleTimeout")
                _voice_live_session = None
        except Exception as loop_err:
            logger.warning("Timeout watcher iteration error: %s", loop_err)


@app.on_event("startup")
async def _startup_tasks():
    """Register background timers once the FastAPI app starts up."""
    asyncio.create_task(_timeout_watcher())


@app.post("/call/events")
async def call_events(request: Request) -> Dict[str, Any]:
    """Handle ACS webhook events and keep local call/Voice Live state in sync."""
    global _voice_live_session
    try:
        body = await request.json()
    except Exception as parse_err:  # JSONDecodeError or other
        raw = await request.body()
        logger.warning("Failed to parse ACS event JSON: %s raw=%r", parse_err, raw[:500])
        raise HTTPException(status_code=400, detail="Invalid JSON payload for ACS events")
    # ACS may send an array (CloudEvents batch) or a single event.
    events = body if isinstance(body, list) else [body]
    logger.info("ACS event batch size=%d", len(events))
    ended = []
    for ev in events:
        if not isinstance(ev, dict):
            logger.warning("Unexpected event shape (not dict): %r", ev)
            continue
        event_type = (
            ev.get("type")
            or ev.get("eventType")
            or ev.get("publicEventType")
        )
        data = ev.get("data") or {}
        call_connection_id = (
            ev.get("callConnectionId")
            or data.get("callConnectionId")
            or ev.get("call_connection_id")
        )
        logger.info("ACS event type=%s call_connection_id=%s", event_type, call_connection_id)
        # Enhanced failure / disconnect diagnostics
        if event_type and (event_type.endswith("CreateCallFailed") or event_type.endswith("CallDisconnected")):
            # Surface full event (trim excessively large fields if any)
            try:
                result_info = data.get("resultInformation") or data.get("resultinformation") or {}
                code = result_info.get("code") or result_info.get("subCode") or result_info.get("errorCode")
                subcode = result_info.get("subCode") or result_info.get("subcode")
                message = result_info.get("message") or result_info.get("detail") or result_info.get("description")
                logger.warning(
                    "ACS %s detail code=%s subcode=%s message=%s raw_result=%s", event_type, code, subcode, message, result_info or 'N/A'
                )
                # Log callee / source if present
                target = data.get("targets") or data.get("participants") or []
                if target:
                    logger.warning("ACS %s targets=%s", event_type, target)
            except Exception as _diag_err:
                logger.debug("ACS failure event diag parse error: %s", _diag_err)
        app_state.update_last_event()
        if not event_type or not call_connection_id:
            continue
        # Start Voice Live on CallConnected
        if event_type.endswith("CallConnected") and app_state.current_call and app_state.current_call.get("call_id") == call_connection_id:
            # Only needed if not auto-start at create
            if settings.media_start_at_create:
                logger.info("ACS MEDIA STREAM already requested at create (start_at_create=True) call_id=%s", call_connection_id)
            else:
                try:
                    client = _call_client()
                    call_conn = client.get_call_connection(call_connection_id)
                    call_conn.start_media_streaming()
                    logger.info("ACS MEDIA STREAM START requested call_id=%s", call_connection_id)
                except Exception as sm_err:
                    logger.exception("Failed to start media streaming: %s", sm_err)
            # Voice Live only if enabled
            if settings.enable_voice_live and (not _voice_live_session or not _voice_live_session.active):
                try:
                    logger.info("VL-MAIN: Attempting to start Voice Live session...")
                    _voice_live_session = VoiceLiveSession(settings.ai_foundry_endpoint, settings.ai_foundry_api_key)
                    logger.info("VL-MAIN: VoiceLiveSession instantiated. Connecting...")
                    prompt = app_state.get_call_prompt(call_connection_id) or settings.default_system_prompt
                    import os as _os
                    runtime_default_voice = _os.getenv("DEFAULT_VOICE", settings.default_voice)
                    
                    # Add a specific timeout for the connection attempt
                    connect_task = _voice_live_session.connect(settings.voice_live_model, runtime_default_voice, prompt)
                    await asyncio.wait_for(connect_task, timeout=15.0)
                    
                    logger.info("VL-MAIN: Voice Live connection successful.")
                    app_state.begin_voicelive(_voice_live_session.session_id, settings.voice_live_model, _voice_live_session.voice or runtime_default_voice)
                    # Launch receive loop
                    async def _on_vl_event(evt: dict):
                        et = evt.get("type")
                        if et:
                            app_state.voicelive_add_event_type(et)
                    asyncio.create_task(run_receive(_voice_live_session, _on_vl_event))
                    # Launch outbound pacing task (segments Voice Live PCM deltas into fixed frames)
                    if settings.media_enable_voicelive_out:
                        async def _pacer():
                            frame_interval = settings.media_frame_interval_ms / 1000.0
                            expected = settings.media_frame_bytes
                            coerce_warned = False
                            # Adaptive backlog drain configuration
                            MAX_BATCH_PER_TICK = 8  # upper safety bound
                            HIGH_BACKLOG_THRESHOLD = 10  # if queue has more than this, drain faster
                            LOW_BACKLOG_SLEEP_THRESHOLD = 2  # if <= this, revert to paced sleep
                            while _voice_live_session and _voice_live_session.active:
                                drained = 0
                                backlog = _voice_live_session._seg_queue.qsize() if _voice_live_session else 0
                                # Always attempt at least one frame
                                frame = await _voice_live_session.get_next_outbound_frame()
                                if frame is None:
                                    # Nothing ready; normal pacing sleep
                                    try:
                                        app_state.media_out_backlog(backlog, drained)
                                    except Exception:
                                        pass
                                    await asyncio.sleep(frame_interval)
                                    continue
                                drained += 1
                                # If bidirectional disabled, just log + update metrics (no send)
                                if not settings.media_bidirectional:
                                    app_state.media_out_frame()
                                    app_state.media_add_out_bytes(len(frame))
                                else:
                                    # Bidirectional: send frame (JSON / binary below)
                                    try:
                                        import base64 as _b64
                                        from .config import settings as _settings_out
                                        b64 = _b64.b64encode(frame).decode('ascii')
                                        fmt = _settings_out.media_out_format
                                        if fmt == "multi":  # temporarily coerce to single to avoid duplication / pitch artifacts
                                            if not coerce_warned:
                                                logger.warning("MEDIA OUT FORMAT multi coerced to json_simple (set MEDIA_OUT_FORMAT) to prevent duplication")
                                                coerce_warned = True
                                            fmt = "json_simple"
                                        payloads: list[str] = []
                                        if fmt in ("json_simple", "multi"):
                                            payloads.append(_json.dumps({
                                                "kind": "AudioData",
                                                "audioData": {"data": b64}
                                            }))
                                        if fmt in ("json_wrapped", "multi"):
                                            payloads.append(_json.dumps({"kind": "AudioData", "audioData": {"data": b64}}))
                                        targets = list(_active_media_sockets)
                                        total_sent = 0
                                        for payload in payloads:
                                            for _ws in targets:
                                                try:
                                                    await _ws.send_text(payload)
                                                    total_sent += 1
                                                except Exception as send_err:
                                                    app_state.media_out_error()
                                                    logger.debug("MEDIA OUT json send error: %s", send_err)
                                        if fmt in ("binary", "multi"):
                                            for _ws in targets:
                                                try:
                                                    await _ws.send_bytes(frame)
                                                    total_sent += 1
                                                except Exception as b_err:
                                                    app_state.media_out_error()
                                                    logger.debug("MEDIA OUT binary send error: %s", b_err)
                                        if total_sent:
                                            app_state.media_out_frame()
                                            app_state.media_add_out_bytes(len(frame))
                                            if app_state.media_snapshot().get("outFrames") <= 3:
                                                logger.info("MEDIA OUT FRAME sent variants=%d targets=%d fmt=%s size=%d b64_len=%d", len(payloads) + (1 if fmt in ("binary","multi") else 0), len(targets), fmt, len(frame), len(b64))
                                    except Exception as o_err:
                                        app_state.media_out_error()
                                        logger.debug("MEDIA OUT error building/sending frame: %s", o_err)

                                # Additional backlog drain in same tick (no sleep) if large backlog
                                while (_voice_live_session and _voice_live_session.active and
                                       _voice_live_session._seg_queue.qsize() > HIGH_BACKLOG_THRESHOLD and
                                       drained < MAX_BATCH_PER_TICK):
                                    next_frame = await _voice_live_session.get_next_outbound_frame()
                                    if not next_frame:
                                        break
                                    drained += 1
                                    # Send without re-deriving config (reuse b64 path for each frame)
                                    if not settings.media_bidirectional:
                                        app_state.media_out_frame()
                                        app_state.media_add_out_bytes(len(next_frame))
                                    else:
                                        try:
                                            import base64 as _b64
                                            b64n = _b64.b64encode(next_frame).decode('ascii')
                                            payload = _json.dumps({"kind": "AudioData", "audioData": {"data": b64n}})
                                            for _ws in list(_active_media_sockets):
                                                try:
                                                    await _ws.send_text(payload)
                                                except Exception as send_err:
                                                    app_state.media_out_error()
                                                    logger.debug("MEDIA OUT json send error(backlog): %s", send_err)
                                            app_state.media_out_frame()
                                            app_state.media_add_out_bytes(len(next_frame))
                                        except Exception as be2:
                                            app_state.media_out_error()
                                            logger.debug("MEDIA OUT backlog frame send err: %s", be2)

                                # Record backlog metrics
                                try:
                                    qsize_now = _voice_live_session._seg_queue.qsize() if _voice_live_session else 0
                                    app_state.media_out_backlog(qsize_now, drained_this_cycle=drained)
                                except Exception:
                                    pass

                                # Sleep only if backlog is low
                                if (_voice_live_session and _voice_live_session._seg_queue.qsize() <= LOW_BACKLOG_SLEEP_THRESHOLD):
                                    await asyncio.sleep(frame_interval)
                                else:
                                    # minimal yield to avoid starving loop
                                    await asyncio.sleep(0)
                        try:
                            global _voice_live_pacer_task
                            _voice_live_pacer_task = asyncio.create_task(_pacer())
                            logger.info("VOICE-LIVE PACER task started frame_bytes=%d interval_ms=%d", settings.media_frame_bytes, settings.media_frame_interval_ms)
                        except Exception as pt_err:
                            logger.warning("Failed to start pacer: %s", pt_err)
                except Exception as vl_err:
                    logger.exception("Failed to start Voice Live session: %s", vl_err)
                    app_state.set_error(f"VoiceLive start failed: {vl_err}")
        # Heuristic for call end events
        if event_type in {"Microsoft.Communication.CallDisconnected", "Microsoft.Communication.CallEnded"} or event_type.endswith("CallDisconnected") or event_type.endswith("CallEnded"):
            app_state.end_call(call_connection_id, reason=event_type)
            ended.append(event_type)
            # Close Voice Live too
            if '_voice_live_session' in globals():
                if _voice_live_session and _voice_live_session.active:
                    try:
                        await _voice_live_session.close()
                    except Exception:
                        pass
                    app_state.end_voicelive(event_type)
                _voice_live_session = None
        # Media streaming failure diagnostics
        if 'MediaStreamingFailed' in event_type:
            try:
                logger.error("ACS MediaStreamingFailed data=%s", data)
                app_state.set_error(f"MediaStreamingFailed: {data}")
            except Exception:
                pass
    return {"ok": True, "processed": len(events), "ended": ended}


@app.websocket("/media/{token}")
async def media_ws(ws: WebSocket, token: str):
    """Bridge ACS media frames to internal processing and Voice Live streaming."""
    t0 = time.perf_counter_ns()
    # 1) subprotocol negotiation (echo if offered)
    offered = ws.headers.get("sec-websocket-protocol")
    subproto = offered.split(",")[0].strip() if offered else None

    await ws.accept(subprotocol=subproto)  # must be first, no awaits before
    t1 = time.perf_counter_ns()

    # 2) immediate ACK, no yields in between if possible
    ack = '{"type":"ack"}'  # use the exact shape that previously unlocked AudioMetadata
    try:
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.send_text(ack)
    except Exception as e:
        logger.warning("MEDIA WS ACK send failed: %r", e)
        return
    t2 = time.perf_counter_ns()

    logger.info(
        "MEDIA WS HANDSHAKE token=%s accepted_subproto=%s timings_us accept=%d ack=%d",
        token, subproto, (t1 - t0)//1000, (t2 - t1)//1000
    )

    # 3) now enter receive loop …
    app_state.media_ws_open()
    # Track active socket for outbound (Voice Live -> ACS) streaming
    _active_media_sockets.add(ws)
    logger.info(
        "MEDIA WS CONNECT token=%s bidi=%s",
        token,
        settings.media_bidirectional,
    )
    # Simplified debugging version: keep socket open, log any frames, no outbound until stability achieved
    first_in_logged = False
    wav_writer = None
    wav_path = settings.media_wav_path
    frame_bytes_expected = settings.media_frame_bytes
    import wave, io
    if settings.media_dump_wav:
        try:
            wav_writer = wave.open(wav_path, 'wb')
            wav_writer.setnchannels(1)
            wav_writer.setsampwidth(2)  # 16-bit
            wav_writer.setframerate(16000)
            logger.info("MEDIA WAV DUMP enabled path=%s", wav_path)
        except Exception as we:
            logger.warning("MEDIA WAV open failed path=%s err=%s", wav_path, we)
            wav_writer = None
    first_raw_logged = False
    last_log = time.time()
    # Diagnostics for missing binary audio
    metadata_seen_at: float | None = None
    warned_no_binary = False
    text_frames_after_metadata = 0
    BIN_DIAG_THRESHOLD_SEC = 5.0  # warn if no audio this long after metadata
    SAMPLE_TEXT_LOG_LIMIT = 20
    AUDIO_CHUNK_SIZE = 640  # bytes per 20ms frame
    try:
        while True:
            try:
                incoming = await asyncio.wait_for(ws.receive(), timeout=5.0)
            except asyncio.TimeoutError:
                if time.time() - last_log > 30:
                    logger.info("MEDIA WS HEARTBEAT token=%s", token)
                    last_log = time.time()
                # Periodic check if we saw metadata but still no binary
                if metadata_seen_at and not warned_no_binary and (time.time() - metadata_seen_at) > BIN_DIAG_THRESHOLD_SEC and app_state.media_snapshot().get("audio_bytes_in", 0) == 0:
                    logger.warning(
                        "MEDIA WS NO BINARY AUDIO %ss after metadata token=%s text_frames_post_meta=%d inFrames=%d",
                        int(time.time() - metadata_seen_at),
                        token,
                        text_frames_after_metadata,
                        app_state.media_snapshot().get("inFrames", -1),
                    )
                    warned_no_binary = True
                continue
            if not first_raw_logged:
                logger.info("MEDIA WS FIRST RAW token=%s frame=%s", token, incoming)
                first_raw_logged = True
            if incoming.get("type") == "websocket.disconnect":
                break
            msg_text = incoming.get("text")
            msg_bytes = incoming.get("bytes")
            if msg_text is not None and msg_text:
                app_state.media_set_schema('A')
                is_metadata = False
                is_audio = False
                audio_kind = None
                decoded_len = 0
                # Attempt JSON parse once
                parsed = None
                try:
                    parsed = _json.loads(msg_text)
                except Exception:
                    parsed = None
                if parsed and isinstance(parsed, dict):
                    audio_kind = parsed.get("kind") or parsed.get("type")
                    # Metadata frame
                    if (audio_kind == "AudioMetadata") or ('AudioMetadata' in msg_text and 'sampleRate' in msg_text):
                        is_metadata = True
                        metadata_seen_at = time.time()
                        app_state.media_set_metadata()
                        logger.info("MEDIA METADATA FRAME token=%s text_len=%d", token, len(msg_text))
                    else:
                        # Candidate audio payloads
                        b64_data = None
                        # Variants
                        if parsed.get("data") and isinstance(parsed.get("data"), str) and (audio_kind in {"AudioData", "AudioChunk"}):
                            b64_data = parsed.get("data")
                        elif isinstance(parsed.get("audioData"), dict) and isinstance(parsed["audioData"].get("data"), str):
                            b64_data = parsed["audioData"].get("data")
                        if b64_data:
                            try:
                                pcm = base64.b64decode(b64_data)
                                decoded_len = len(pcm)
                                if decoded_len:
                                    is_audio = True
                                    app_state.media_add_in_bytes(decoded_len)
                                    # Frame accounting (20ms == 640 bytes)
                                    n_frames = decoded_len // AUDIO_CHUNK_SIZE
                                    if n_frames:
                                        app_state.media_add_in_frames(n_frames)
                                    # Frame-by-frame energy metrics
                                    if decoded_len % AUDIO_CHUNK_SIZE != 0:
                                        logger.debug("MEDIA AUDIO SIZE not multiple frame_bytes len=%d", decoded_len)
                                    # Iterate each 640-byte frame
                                    for off in range(0, decoded_len, AUDIO_CHUNK_SIZE):
                                        frame_slice = pcm[off:off+AUDIO_CHUNK_SIZE]
                                        if len(frame_slice) < AUDIO_CHUNK_SIZE:
                                            break
                                        try:
                                            is_speech = app_state.media_process_audio_frame(frame_slice)
                                            global _voice_live_session
                                            if is_speech and _voice_live_session:
                                                _voice_live_session._speech_detected = True
                                            # Conditional bridging to Voice Live (inbound -> model)
                                            from .config import settings as _settings
                                            if (
                                                _settings.enable_voice_live
                                                and _settings.media_enable_voicelive_in
                                                and _voice_live_session
                                                and _voice_live_session.active
                                            ):
                                                snap = app_state.media_snapshot()
                                                started_flag = bool(snap.get("vl_in_started_at"))
                                                if not started_flag:
                                                    # Gate start on thresholds
                                                    ns_frames = snap.get("audio_frames_non_silent", 0)
                                                    rms_avg = snap.get("audio_rms_avg") or 0
                                                    if (
                                                        ns_frames >= _settings.media_vl_in_start_frames
                                                        and rms_avg >= _settings.media_vl_in_start_rms
                                                    ):
                                                        app_state.media_mark_vl_in_started()
                                                        logger.info(
                                                            "VL-IN BRIDGE START non_silent_frames=%d rms_avg=%s thresholds(frames=%d,rms=%d)",
                                                            ns_frames,
                                                            rms_avg,
                                                            _settings.media_vl_in_start_frames,
                                                            _settings.media_vl_in_start_rms,
                                                        )
                                                        # Prime buffer with greeting response if not already (optional)
                                                if started_flag or app_state.media_snapshot().get("vl_in_started_at"):
                                                    try:
                                                        await _voice_live_session.send_input_audio_frame(frame_slice)
                                                    except Exception as vf_err:
                                                        logger.debug("VL-IN frame send error: %s", vf_err)
                                        except Exception as fe:
                                            logger.debug("MEDIA AUDIO FRAME PROCESS ERR off=%d err=%s", off, fe)
                                    # Remainder ignored (rare) – could buffer if needed
                                    if wav_writer:
                                        try:
                                            wav_writer.writeframes(pcm)
                                        except Exception as wf_err:
                                            logger.warning("MEDIA WAV write err=%s", wf_err)
                                            pass
                                else:
                                    logger.debug("MEDIA AUDIO EMPTY PCM token=%s kind=%s", token, audio_kind)
                            except Exception as dec_err:
                                logger.warning("MEDIA AUDIO BASE64 DECODE FAIL token=%s kind=%s err=%s", token, audio_kind, dec_err)
                # Logging logic
                if is_metadata and not first_in_logged:
                    # Do not mark first audio timestamp yet (metadata only)
                    first_in_logged = True
                if not is_metadata and is_audio and not first_in_logged:
                    logger.info("MEDIA FIRST AUDIO FRAME token=%s bytes=%d kind=%s", token, decoded_len, audio_kind)
                    first_in_logged = True
                # Sample logging of subsequent control/audio frames
                if metadata_seen_at:
                    if is_metadata:
                        app_state.media_text_frame(post_metadata=False)
                    else:
                        app_state.media_text_frame(post_metadata=True)
                        if text_frames_after_metadata < SAMPLE_TEXT_LOG_LIMIT:
                            log_fn = logger.info if settings.media_log_all_text_frames else logger.debug
                            # Determine number of frames inside this message
                            frames_in_msg = 0
                            if decoded_len:
                                frames_in_msg = decoded_len // AUDIO_CHUNK_SIZE
                            log_fn(
                                "MEDIA TEXT FRAME token=%s idx=%d kind=%s audio=%s frames=%d bytes=%d len=%d",
                                token,
                                text_frames_after_metadata,
                                audio_kind,
                                is_audio,
                                frames_in_msg,
                                decoded_len,
                                len(msg_text),
                            )
                            text_frames_after_metadata += 1
                else:
                    # Pre-metadata text (should not happen except metadata itself)
                    app_state.media_text_frame(post_metadata=False)
                continue
            if msg_bytes is not None and msg_bytes:
                size = len(msg_bytes)
                app_state.media_add_in_bytes(size)
                # For binary, treat each message as exactly one frame unless larger
                frames = max(1, size // frame_bytes_expected)
                app_state.media_add_in_frames(frames)
                app_state.media_binary_frame()
                if wav_writer:
                    try:
                        wav_writer.writeframes(msg_bytes)
                    except Exception as wf_err:
                        logger.warning("MEDIA WAV write err=%s", wf_err)
                        wav_writer = None
                if not first_in_logged:
                    logger.info("MEDIA FIRST IN BINARY FRAME token=%s size=%d", token, size)
                    first_in_logged = True
                else:
                    if size != frame_bytes_expected:
                        logger.debug("MEDIA FRAME size unexpected got=%d expected=%d", size, frame_bytes_expected)
                continue
    except WebSocketDisconnect as d:
        code = getattr(d, 'code', 'n/a')
        logger.info("MEDIA WS DISCONNECT token=%s code=%s", token, code)
    except Exception as e:
        logger.warning("MEDIA WS ERROR token=%s err=%s", token, e)
    finally:
        try:
            if wav_writer:
                wav_writer.close()
                logger.info("MEDIA WAV DUMP closed path=%s", wav_path)
        except Exception:
            pass
        try:
            _active_media_sockets.discard(ws)
        except Exception:
            pass
        app_state.media_ws_close()
