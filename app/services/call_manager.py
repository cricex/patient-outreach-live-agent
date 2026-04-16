"""Call lifecycle orchestrator.

Manages per-session CallSessions, coordinates with ACS for PSTN calls,
handles webhook events, and provides the speech service accessor
for the media bridge.  Supports multiple concurrent calls (one per session).
"""
from __future__ import annotations

import asyncio
import logging
import time

from azure.communication.callautomation import (
    CallAutomationClient,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    PhoneNumberIdentifier,
    ServerCallLocator,
    StreamingTransportType,
)
from azure.core.exceptions import AzureError

from ..auth import DEFAULT_SESSION_ID
from ..config import settings
from ..models.state import AppState, app_state
from .call_session import CallSession
from .call_history import call_history
from ..services.event_bus import event_bus, EventType

logger = logging.getLogger("app.call")


class CallManager:
    """Service that orchestrates call lifecycle across sessions.

    Tracks per-session CallSessions and media token mappings so each
    authenticated user has an isolated call experience.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, CallSession] = {}  # session_id → CallSession
        self._hangup_futures: dict[str, asyncio.Future] = {}
        self._recording_ids: dict[str, str] = {}  # session_id → recording_id
        self._media_tokens: dict[str, str] = {}  # media_token → session_id
        self._call_to_session: dict[str, str] = {}  # call_id → session_id

    def get_session(self, session_id: str) -> CallSession | None:
        return self._sessions.get(session_id)

    @property
    def current_session(self) -> CallSession | None:
        """Backward compat — returns default session's call."""
        return self._sessions.get(DEFAULT_SESSION_ID)

    def get_speech(self, session_id: str | None = None):
        """Return the active SpeechService for a session, or None.

        This is passed as a callable to the media bridge so it can
        access the speech service without circular imports.
        """
        sid = session_id or DEFAULT_SESSION_ID
        session = self._sessions.get(sid)
        if session and session.active:
            return session.speech
        return None

    def get_speech_for_media_token(self, media_token: str):
        """Resolve a media token to its session's SpeechService."""
        sid = self._media_tokens.get(media_token)
        if sid:
            return self.get_speech(sid)
        return None

    def get_session_id_for_media_token(self, media_token: str) -> str:
        """Resolve a media token to its session_id."""
        return self._media_tokens.get(media_token, DEFAULT_SESSION_ID)

    async def start_call(
        self,
        session_id: str,
        target_phone: str | None = None,
        system_prompt: str | None = None,
        simulate: bool = False,
    ) -> tuple[str, str, str]:
        """Start a new call for a specific session.

        Returns:
            (call_id, destination, prompt_used)

        Raises:
            ValueError: if destination is missing for real calls.
            RuntimeError: if ACS call creation fails.
        """
        prompt = system_prompt or settings.default_system_prompt
        dest = target_phone or settings.target_phone_number or (
            "SIMULATED" if simulate else None
        )

        if not simulate and not dest:
            raise ValueError(
                "Destination number missing "
                "(provide target_phone_number or set TARGET_PHONE_NUMBER)"
            )

        # Clean up any prior session for this user
        if session_id in self._sessions:
            await self._sessions[session_id].stop("NewCall")
            del self._sessions[session_id]

        if simulate:
            call_id = f"sim-{int(time.time() * 1000)}"
        else:
            call_id = await self._create_acs_call(session_id, dest, prompt)

        # Create session and start Voice Live
        await app_state.begin_call(session_id, call_id, prompt)
        call_history.begin_call(
            call_id=call_id,
            destination=dest or "SIMULATED",
            system_prompt=prompt,
            voice=settings.voicelive_voice,
            model=settings.voicelive_model,
            simulated=simulate,
        )
        event_bus.emit(EventType.CALL_STARTED, session_id=session_id, call_id=call_id, destination=dest or "SIMULATED")

        session = CallSession(call_id, app_state, session_id)
        self._sessions[session_id] = session
        self._call_to_session[call_id] = session_id

        # Set up auto-hangup callback
        loop = asyncio.get_running_loop()
        hangup_future = loop.create_future()
        session.set_hangup_callback(hangup_future)
        self._hangup_futures[session_id] = hangup_future
        asyncio.create_task(self._watch_hangup_future(session_id, call_id))

        try:
            await asyncio.wait_for(session.start(prompt), timeout=30.0)
        except Exception as exc:
            # Call is placed but speech failed — don't crash the call
            logger.warning("Speech session start failed: %s", exc)

        return call_id, dest or "SIMULATED", prompt

    async def handle_event(
        self, event_type: str, call_id: str, data: dict
    ) -> None:
        """Process an ACS webhook event."""
        session_id = self._call_to_session.get(call_id, DEFAULT_SESSION_ID)
        app_state.update_last_event(session_id)

        if event_type.endswith("CallConnected"):
            session = self._sessions.get(session_id)
            if session and not session.active:
                prompt = (
                    app_state.get_call(session_id).prompt
                    if app_state.get_call(session_id)
                    else settings.default_system_prompt
                )
                try:
                    await asyncio.wait_for(
                        session.start(prompt), timeout=30.0
                    )
                except Exception as exc:
                    logger.warning(
                        "Speech session start on CallConnected failed: %s", exc
                    )
            # Start media streaming if not auto-started
            if not settings.media_start_at_create:
                try:
                    client = self._acs_client()
                    conn = client.get_call_connection(call_id)
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, conn.start_media_streaming)
                except Exception as exc:
                    logger.warning("start_media_streaming failed: %s", exc)

            # Start recording if enabled
            if settings.enable_call_recording:
                try:
                    client = self._acs_client()
                    loop = asyncio.get_running_loop()
                    server_call_id = data.get("serverCallId")
                    if server_call_id:
                        recording_resp = await loop.run_in_executor(
                            None,
                            lambda: client.start_recording(
                                call_locator=ServerCallLocator(server_call_id),
                            ),
                        )
                        rec_id = getattr(recording_resp, "recording_id", None)
                        if rec_id:
                            self._recording_ids[session_id] = rec_id
                            call_history.set_recording_id(rec_id)
                            logger.info("Recording started recording_id=%s", rec_id)
                except Exception as exc:
                    logger.warning("Failed to start recording: %s", exc)

        elif event_type.endswith("MediaStreamingStarted"):
            app_state.get_media(session_id).started = True

        elif event_type.endswith("CallDisconnected") or event_type.endswith(
            "CallEnded"
        ):
            await self.end_call(session_id, call_id=call_id, reason=event_type)

    async def end_call(
        self, session_id: str, call_id: str | None = None, reason: str | None = None
    ) -> str | None:
        """End the call for a specific session and clean up."""
        session = self._sessions.get(session_id)
        if not session:
            return None

        actual_id = call_id or session.call_id

        # Try ACS hangup (best-effort, skip for timeout/idle — session already dead)
        if reason != "Timeout" and reason != "Idle":
            try:
                client = self._acs_client()
                conn = client.get_call_connection(actual_id)
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda: conn.hang_up(is_for_everyone=True)
                )
            except Exception:
                logger.debug("ACS hangup failed (continuing)")

        # Stop recording if active
        rec_id = self._recording_ids.pop(session_id, None)
        if rec_id:
            try:
                client = self._acs_client()
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda: client.stop_recording(rec_id)
                )
                logger.info("Recording stopped recording_id=%s", rec_id)
            except Exception as exc:
                logger.warning("Failed to stop recording: %s", exc)

        event_bus.emit(EventType.CALL_ENDED, session_id=session_id, call_id=actual_id, reason=reason)
        await session.stop(reason)
        call_history.end_call(reason)

        # Clean up mappings
        del self._sessions[session_id]
        self._call_to_session.pop(actual_id, None)
        # Clean up media tokens for this session
        stale_tokens = [t for t, sid in self._media_tokens.items() if sid == session_id]
        for t in stale_tokens:
            del self._media_tokens[t]
        event_bus.clear(session_id)

        # Cancel hangup future if still pending
        hangup_future = self._hangup_futures.pop(session_id, None)
        if hangup_future and not hangup_future.done():
            hangup_future.cancel()

        logger.info("Call ended call_id=%s session_id=%s reason=%s", actual_id, session_id, reason)
        return actual_id

    # ---- Internal ----

    async def _create_acs_call(self, session_id: str, dest: str, prompt: str) -> str:
        """Place an outbound PSTN call via ACS."""
        base_url = settings.app_base_url.rstrip("/")
        if base_url.startswith("http://"):
            raise ValueError("APP_BASE_URL must be https for ACS callbacks")

        token = f"m-{int(time.time() * 1000)}"
        self._media_tokens[token] = session_id
        ws_host = base_url.split("://", 1)[1]
        transport_url = f"wss://{ws_host}/media/{token}"

        media = MediaStreamingOptions(
            transport_url=transport_url,
            transport_type=StreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=(
                MediaStreamingAudioChannelType.MIXED
                if settings.media_audio_channel_type == "mixed"
                else MediaStreamingAudioChannelType.UNMIXED
            ),
            enable_bidirectional=settings.media_bidirectional,
            audio_format="Pcm24KMono",
            start_media_streaming=settings.media_start_at_create,
        )

        client = self._acs_client()
        loop = asyncio.get_running_loop()

        def _do_create():
            return client.create_call(
                target_participant=PhoneNumberIdentifier(dest),
                callback_url=f"{base_url}/call/events",
                source_caller_id_number=PhoneNumberIdentifier(
                    settings.acs_outbound_caller_id
                ),
                media_streaming=media,
                operation_context=token,
            )

        try:
            resp = await loop.run_in_executor(None, _do_create)
        except AzureError as exc:
            logger.exception("ACS create_call failed: %s", exc)
            raise RuntimeError("ACS call creation failed") from exc

        call_props = getattr(resp, "call_connection_properties", None)
        call_id = getattr(call_props, "call_connection_id", None) or getattr(
            resp, "call_connection_id", None
        )
        if not call_id:
            raise RuntimeError("Could not determine call ID from ACS response")

        return call_id

    async def _watch_hangup_future(self, session_id: str, call_id: str) -> None:
        """Wait for the hangup future and end the call when triggered."""
        try:
            hangup_future = self._hangup_futures.get(session_id)
            if not hangup_future:
                return
            reason = await hangup_future
            if reason:
                await self.end_call(session_id, call_id=call_id, reason=reason)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("hangup future watcher error: %s", exc)

    @staticmethod
    def _acs_client() -> CallAutomationClient:
        return CallAutomationClient.from_connection_string(
            settings.acs_connection_string
        )


# Module-level singleton
call_manager = CallManager()
