"""Call lifecycle orchestrator.

Manages the active CallSession, coordinates with ACS for PSTN calls,
handles webhook events, and provides the speech service accessor
for the media bridge.
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

from ..config import settings
from ..models.state import AppState, app_state
from .call_session import CallSession
from .call_history import call_history
from ..services.event_bus import event_bus, EventType

logger = logging.getLogger("app.call")


class CallManager:
    """Singleton service that orchestrates call lifecycle.

    Owns the active CallSession and provides accessors for
    the media bridge and route handlers.
    """

    def __init__(self) -> None:
        self._session: CallSession | None = None
        self._hangup_future: asyncio.Future | None = None
        self._recording_id: str | None = None

    @property
    def current_session(self) -> CallSession | None:
        return self._session

    def get_speech(self):
        """Return the active SpeechService or None.

        This is passed as a callable to the media bridge so it can
        access the speech service without circular imports.
        """
        if self._session and self._session.active:
            return self._session.speech
        return None

    async def start_call(
        self,
        target_phone: str | None = None,
        system_prompt: str | None = None,
        simulate: bool = False,
    ) -> tuple[str, str, str]:
        """Start a new call (real ACS or simulated).

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

        # Clean up any prior session
        if self._session:
            await self._session.stop("NewCall")
            self._session = None

        if simulate:
            call_id = f"sim-{int(time.time() * 1000)}"
        else:
            call_id = await self._create_acs_call(dest, prompt)

        # Create session and start Voice Live
        await app_state.begin_call(call_id, prompt)
        call_history.begin_call(
            call_id=call_id,
            destination=dest or "SIMULATED",
            system_prompt=prompt,
            voice=settings.voicelive_voice,
            model=settings.voicelive_model,
            simulated=simulate,
        )
        event_bus.emit(EventType.CALL_STARTED, call_id=call_id, destination=dest or "SIMULATED")
        self._session = CallSession(call_id, app_state)

        # Set up auto-hangup callback
        loop = asyncio.get_running_loop()
        self._hangup_future = loop.create_future()
        self._session.set_hangup_callback(self._hangup_future)
        asyncio.create_task(self._watch_hangup_future(call_id))

        try:
            await asyncio.wait_for(self._session.start(prompt), timeout=30.0)
        except Exception as exc:
            # Call is placed but speech failed — don't crash the call
            logger.warning("Speech session start failed: %s", exc)

        return call_id, dest or "SIMULATED", prompt

    async def handle_event(
        self, event_type: str, call_id: str, data: dict
    ) -> None:
        """Process an ACS webhook event."""
        app_state.update_last_event()

        if event_type.endswith("CallConnected"):
            # Start speech session if not already running
            if self._session and not self._session.active:
                prompt = (
                    app_state.current_call.prompt
                    if app_state.current_call
                    else settings.default_system_prompt
                )
                try:
                    await asyncio.wait_for(
                        self._session.start(prompt), timeout=30.0
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
                        self._recording_id = getattr(
                            recording_resp, "recording_id", None
                        )
                        if self._recording_id:
                            call_history.set_recording_id(self._recording_id)
                            logger.info(
                                "Recording started recording_id=%s",
                                self._recording_id,
                            )
                except Exception as exc:
                    logger.warning("Failed to start recording: %s", exc)

        elif event_type.endswith("MediaStreamingStarted"):
            app_state.media.started = True

        elif event_type.endswith("CallDisconnected") or event_type.endswith(
            "CallEnded"
        ):
            await self.end_call(call_id, reason=event_type)

    async def end_call(
        self, call_id: str | None = None, reason: str | None = None
    ) -> str | None:
        """End the active call and clean up."""
        if not self._session:
            return None

        actual_id = call_id or self._session.call_id

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
        if self._recording_id:
            try:
                client = self._acs_client()
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda: client.stop_recording(self._recording_id)
                )
                logger.info(
                    "Recording stopped recording_id=%s", self._recording_id
                )
            except Exception as exc:
                logger.warning("Failed to stop recording: %s", exc)
            self._recording_id = None

        event_bus.emit(EventType.CALL_ENDED, call_id=actual_id, reason=reason)
        await self._session.stop(reason)
        call_history.end_call(reason)
        self._session = None
        event_bus.clear()

        # Cancel hangup future if still pending
        if self._hangup_future and not self._hangup_future.done():
            self._hangup_future.cancel()
        self._hangup_future = None

        logger.info("Call ended call_id=%s reason=%s", actual_id, reason)
        return actual_id

    # ---- Internal ----

    async def _create_acs_call(self, dest: str, prompt: str) -> str:
        """Place an outbound PSTN call via ACS."""
        base_url = settings.app_base_url.rstrip("/")
        if base_url.startswith("http://"):
            raise ValueError("APP_BASE_URL must be https for ACS callbacks")

        token = f"m-{int(time.time() * 1000)}"
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
            audio_format="Pcm16KMono",
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

    async def _watch_hangup_future(self, call_id: str) -> None:
        """Wait for the hangup future and end the call when triggered."""
        try:
            reason = await self._hangup_future
            if reason:
                await self.end_call(call_id, reason=reason)
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
