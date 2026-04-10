"""Voice Live GA 1.1.0 session wrapper.

Provides a clean async interface for the media bridge:
    - connect(system_prompt, tools) → establishes Voice Live WebSocket session
    - send_audio(pcm_bytes) → streams caller audio to Voice Live
    - get_next_output_frame() → returns next synthesized audio frame (or None)
    - close() → tears down session

The GA SDK handles VAD, turn detection, noise suppression, and echo cancellation
natively — no manual flush timers or upsampling needed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from typing import Any, Deque

from azure.core.credentials import AzureKeyCredential

from ..config import settings
from ..services.event_bus import event_bus, EventType

logger = logging.getLogger("app.voice")

# Frame size for output audio (20ms @ 16kHz mono PCM16 = 640 bytes)
OUTPUT_FRAME_BYTES = settings.media_frame_bytes

# Import SDK — graceful fallback if not installed
try:
    from azure.ai.voicelive.aio import connect as voicelive_connect
    from azure.ai.voicelive.models import (
        RequestSession,
        AzureStandardVoice,
        Modality,
        InputAudioFormat,
        OutputAudioFormat,
        ServerVad,
        ServerEventType,
        AudioEchoCancellation,
        AudioNoiseReduction,
    )

    VOICELIVE_AVAILABLE = True
except ImportError:
    VOICELIVE_AVAILABLE = False
    logger.warning("azure-ai-voicelive not installed — speech service unavailable")


class SpeechService:
    """Wraps a single Voice Live session for one call.

    Created per-call by CallSession, not shared across calls.
    """

    def __init__(self) -> None:
        self.session_id: str = str(uuid.uuid4())
        self.voice: str | None = None
        self.model: str | None = None
        self._active: bool = False
        self._connection: Any = None
        self._session_ready = asyncio.Event()
        self._event_task: asyncio.Task | None = None
        self._output_queue: Deque[bytes] = deque(maxlen=500)
        self._output_buffer = bytearray()
        self._inbound_frame_count: int = 0

    @property
    def active(self) -> bool:
        return self._active

    async def connect(self, system_prompt: str | None = None) -> None:
        """Connect to Voice Live and configure the session.

        Args:
            system_prompt: Override for the default system prompt.  Falls back
                to ``settings.voicelive_system_prompt`` then
                ``settings.default_system_prompt``.

        Raises:
            RuntimeError: If the Voice Live SDK is not installed.
            Exception: Propagates connection or session-update failures.
        """
        if self._active:
            return
        if not VOICELIVE_AVAILABLE:
            logger.warning("Voice Live SDK not available — session will be inactive")
            return

        self.model = settings.voicelive_model
        self.voice = settings.voicelive_voice

        instructions = self._build_instructions(system_prompt)

        # Credential — prefer explicit API key, fall back to Entra identity
        credential = (
            AzureKeyCredential(settings.voicelive_api_key)
            if settings.voicelive_api_key
            else None
        )
        if not credential:
            try:
                from azure.identity.aio import DefaultAzureCredential

                credential = DefaultAzureCredential()
            except Exception as exc:
                logger.error("No API key and DefaultAzureCredential failed: %s", exc)
                raise

        try:
            self._connection = await voicelive_connect(
                endpoint=settings.voicelive_endpoint,
                credential=credential,
                model=self.model,
                api_version=settings.voicelive_api_version,
            ).__aenter__()

            voice_cfg = self._build_voice_config()

            # Build optional GA feature kwargs
            extra: dict[str, Any] = {}
            if settings.voicelive_noise_reduction:
                extra["input_audio_noise_reduction"] = AudioNoiseReduction(
                    type="azure_deep_noise_suppression",
                )
            if settings.voicelive_echo_cancellation:
                extra["input_audio_echo_cancellation"] = AudioEchoCancellation()

            session_cfg = RequestSession(
                modalities=[Modality.TEXT, Modality.AUDIO],
                instructions=instructions,
                voice=voice_cfg,
                input_audio_format=InputAudioFormat.PCM16,
                output_audio_format=OutputAudioFormat.PCM16,
                turn_detection=ServerVad(
                    threshold=settings.voicelive_vad_threshold,
                    prefix_padding_ms=settings.voicelive_vad_prefix_padding_ms,
                    silence_duration_ms=settings.voicelive_vad_silence_duration_ms,
                ),
                **extra,
            )
            await self._connection.session.update(session=session_cfg)

            self._event_task = asyncio.create_task(self._consume_events())
            await self._session_ready.wait()

            self._active = True
            logger.info(
                "Voice Live session started id=%s model=%s voice=%s",
                self.session_id,
                self.model,
                self.voice,
            )
        except Exception:
            logger.exception("Voice Live connect failed")
            raise

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Stream raw PCM audio from caller to Voice Live input buffer.

        Args:
            pcm_bytes: Raw 16-bit PCM audio bytes from the caller.
        """
        if not (self._active and self._connection and pcm_bytes):
            return
        try:
            await self._connection.input_audio_buffer.append(audio=pcm_bytes)
            self._inbound_frame_count += 1
            if self._inbound_frame_count >= 50:
                event_bus.emit(EventType.AUDIO_INBOUND, frames=self._inbound_frame_count, session_id=self.session_id)
                self._inbound_frame_count = 0
        except Exception as exc:
            logger.debug("audio send error: %s", exc)

    async def get_next_output_frame(self) -> bytes | None:
        """Pop next output audio frame from queue, or None if empty."""
        if not self._active:
            return None
        try:
            return self._output_queue.popleft()
        except IndexError:
            return None

    async def close(self) -> None:
        """Tear down the Voice Live session."""
        self._active = False
        if self._event_task:
            self._event_task.cancel()
            try:
                await self._event_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._connection:
            try:
                await self._connection.__aexit__(None, None, None)
            except Exception:
                pass
        logger.info("SpeechService closed id=%s", self.session_id)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _build_instructions(self, system_prompt: str | None) -> str | None:
        """Merge system prompt with behavioural directives."""
        parts: list[str] = []
        base = (
            system_prompt
            or settings.voicelive_system_prompt
            or settings.default_system_prompt
        )
        if base and base.strip():
            parts.append(base.strip())
        if settings.voicelive_wait_for_caller:
            parts.append("Wait silently until the caller speaks first.")
        if settings.voicelive_language_hint:
            parts.append(f"Respond in {settings.voicelive_language_hint.strip()}.")
        return "\n".join(parts) if parts else None

    def _build_voice_config(self) -> AzureStandardVoice | str:
        """Return typed voice config.

        Azure TTS voices contain hyphens (e.g. ``en-US-AvaNeural``);
        OpenAI built-in voices are plain strings (``alloy``, ``nova``, …).
        """
        v = self.voice or "alloy"
        openai_voices = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
        if "-" in v and not v.startswith(openai_voices):
            return AzureStandardVoice(name=v)
        return v

    async def _consume_events(self) -> None:
        """Async iterator over Voice Live server events."""
        try:
            async for event in self._connection:
                etype = getattr(event, "type", None)
                logger.debug("voicelive event type=%s", etype)

                if etype == ServerEventType.SESSION_UPDATED:
                    self._session_ready.set()
                    event_bus.emit(EventType.VL_SESSION_READY, session_id=self.session_id)
                    logger.info("Voice Live session ready")

                elif etype == ServerEventType.RESPONSE_AUDIO_DELTA:
                    delta = getattr(event, "delta", None)
                    if delta:
                        self._buffer_output_audio(delta)
                        event_bus.emit(EventType.AUDIO_OUTBOUND, frames=len(delta), session_id=self.session_id)

                elif etype == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
                    # Barge-in: user started speaking, clear queued output
                    self._output_queue.clear()
                    self._output_buffer.clear()
                    event_bus.emit(EventType.BARGE_IN, session_id=self.session_id)
                    logger.debug("barge-in: cleared output queue")

                elif etype == ServerEventType.ERROR:
                    error = getattr(event, "error", None)
                    event_bus.emit(EventType.VL_ERROR, message=str(getattr(error, "message", error)), session_id=self.session_id)
                    logger.error(
                        "Voice Live error: %s", getattr(error, "message", error)
                    )

                elif etype == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                    transcript = getattr(event, "transcript", "")
                    if transcript:
                        event_bus.emit(EventType.TRANSCRIPT_USER, text=transcript, session_id=self.session_id)

                elif etype == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                    transcript = getattr(event, "transcript", "")
                    if transcript:
                        event_bus.emit(EventType.TRANSCRIPT_AGENT, text=transcript, session_id=self.session_id)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("event consumer error: %s", exc)

    def _buffer_output_audio(self, audio_bytes: bytes) -> None:
        """Segment output audio into fixed-size frames for ACS.

        Incoming deltas are variable-length; ACS expects uniform 20 ms
        frames.  This method buffers and slices accordingly.
        """
        self._output_buffer.extend(audio_bytes)
        while len(self._output_buffer) >= OUTPUT_FRAME_BYTES:
            frame = bytes(self._output_buffer[:OUTPUT_FRAME_BYTES])
            del self._output_buffer[:OUTPUT_FRAME_BYTES]
            if len(self._output_queue) == self._output_queue.maxlen:
                self._output_queue.popleft()  # drop oldest if full
            self._output_queue.append(frame)
