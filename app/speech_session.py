"""Voice Live GA session wrapper for /app.

Adapts the official azure-ai-voicelive SDK (async) to a simple frame-based
interface consumed by the media bridge:
    - connect(system_prompt)
    - send_input_frame(pcm_20ms)  (ACS inbound audio -> Voice Live input buffer)
    - get_next_outbound_frame() -> fixed-size PCM frames (queued from response.audio.delta events)

Differences from preview placeholder:
    * Uses `azure.ai.voicelive.aio.connect` and session.update with RequestSession
    * Consumes streaming events and extracts `response.audio.delta` bytes
    * Segments audio deltas into FRAME_BYTES chunks (drops remainder until enough bytes accumulate)

If the GA SDK is not installed, falls back to optional mock sine generator.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import math
import os
import struct
import time
import uuid
from collections import deque
from typing import Deque, Optional, Union

try:
    import audioop  # type: ignore
except Exception:  # pragma: no cover
    audioop = None  # type: ignore

from .config import settings
from .state import app_state

logger = logging.getLogger("app.voice")

FRAME_BYTES = settings.media_frame_bytes

try:  # GA Voice Live SDK
    from azure.core.credentials import AzureKeyCredential  # type: ignore
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore
    except Exception:  # pragma: no cover
        DefaultAzureCredential = None  # type: ignore
    from azure.ai.voicelive.aio import connect as voicelive_connect  # type: ignore
    from azure.ai.voicelive.models import (  # type: ignore
        RequestSession,
        AzureStandardVoice,
        Modality,
        InputAudioFormat,
        OutputAudioFormat,
        ServerEventType,
        ServerVad,
    )
    VOICELIVE_AVAILABLE = True
except Exception as _import_err:  # pragma: no cover
    VOICELIVE_AVAILABLE = False
    import sys
    logger.warning(
        "azure-ai-voicelive import failed: %s | sys.executable=%s | sys.path[0]=%s",
        _import_err,
        sys.executable,
        sys.path[0] if sys.path else '<empty>'
    )


class SpeechSession:
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.voice: Optional[str] = None
        self.model: Optional[str] = None
        self._active = False
        self._connection = None  # VoiceLiveConnection (async context)
        self._session_ready_event = asyncio.Event()
        self._rx_task: Optional[asyncio.Task] = None
        self._rx_queue: Deque[bytes] = deque(maxlen=500)
        self._mock_task: Optional[asyncio.Task] = None
        self._buffer_out = bytearray()
        self._frames_dropped = 0
        self._frame_bytes_dynamic = FRAME_BYTES
        self._emitted_frames = 0
        self._frame_interval_ms = settings.media_frame_interval_ms
        self._target_frame_bytes = FRAME_BYTES
        self._target_sample_rate = self._compute_sample_rate(self._target_frame_bytes)
        self._output_sample_rate: Optional[int] = None
        self._output_resample_state = None
        self._outgoing_remainder = bytearray()
        self._output_resample_warned = False
        # Input batching (flush to service without issuing manual commits; Server VAD handles turn taking)
        self._input_buffer = bytearray()
        self._input_frames_buffered = 0
        self._input_flush_target_frames = max(1, settings.voicelive_input_flush_target_frames)
        base_interval_ms = max(settings.voicelive_input_flush_interval_ms, 1)
        max_interval_ms = max(settings.voicelive_input_flush_max_interval_ms, base_interval_ms)
        self._input_flush_interval_sec = base_interval_ms / 1000.0
        self._input_flush_max_interval_sec = max_interval_ms / 1000.0
        self._min_flush_delay_sec = min(self._input_flush_interval_sec, 0.02)
        self._last_flush_monotonic = time.monotonic()
        self._using_upsample = settings.voicelive_upsample_16k_to_24k
        self._flush_task: Optional[asyncio.Task] = None
        self._debug_input_flush = settings.debug_voicelive_input_flush

    @property
    def active(self) -> bool:
        return self._active

    async def connect(self, system_prompt: str | None):
        if self._active:
            return
        self.model = settings.voicelive_model
        self.voice = settings.voicelive_voice
        base_instructions = system_prompt or settings.voicelive_system_prompt or settings.default_system_prompt
        instruction_parts: list[str] = []
        if base_instructions and base_instructions.strip():
            instruction_parts.append(base_instructions.strip())
        if settings.voicelive_wait_for_caller:
            instruction_parts.append(
                "Wait silently until the caller greets you first; do not speak until you hear them say something."
            )
        language_hint = settings.voicelive_language_hint
        if language_hint:
            hint = language_hint.strip()
            if hint:
                instruction_parts.append(f"Respond in {hint}.")
        instructions = "\n".join(instruction_parts) if instruction_parts else None

        if not VOICELIVE_AVAILABLE:
            self._active = True
            app_state.begin_voicelive(self.session_id, self.voice or "voice", self.model)
            if os.getenv("APP_ENABLE_MOCK_AUDIO", "false").lower() == "true":
                self._mock_task = asyncio.create_task(self._mock_outbound())
            logger.warning("Voice Live GA SDK missing – mock mode active.")
            return

        credential = None
        if settings.voicelive_api_key:
            credential = AzureKeyCredential(settings.voicelive_api_key)
        else:  # Entra ID
            try:
                credential = DefaultAzureCredential()
            except Exception as exc:  # pragma: no cover
                logger.error("Failed to create DefaultAzureCredential: %s", exc)
                raise

        try:
            logger.debug(
                "voicelive connect begin model=%s voice=%s endpoint=%s api_version=%s",
                self.model,
                self.voice,
                settings.voicelive_endpoint,
                settings.voicelive_api_version,
            )
            self._connection = await voicelive_connect(
                endpoint=settings.voicelive_endpoint,
                credential=credential,
                model=self.model,
                api_version=settings.voicelive_api_version,
            ).__aenter__()
            logger.debug("voicelive websocket connected session_obj=%s", type(self._connection))
            voice_cfg: Union["AzureStandardVoice", str]
            if self._looks_like_azure_voice(self.voice):
                voice_cfg = AzureStandardVoice(name=self.voice, type="azure-standard")
            else:
                voice_cfg = self.voice
            session_cfg = RequestSession(
                modalities=[Modality.TEXT, Modality.AUDIO],
                instructions=instructions,
                voice=voice_cfg,
                input_audio_format=InputAudioFormat.PCM16,
                output_audio_format=OutputAudioFormat.PCM16,
                turn_detection=ServerVad(
                    threshold=0.35,
                    prefix_padding_ms=100,
                    silence_duration_ms=250,
                ),
            )
            logger.debug("voicelive session.update sending modalities=%s voice=%s", session_cfg.modalities, voice_cfg)
            await self._connection.session.update(session=session_cfg)
            logger.debug("voicelive session.update completed, awaiting session_ready event")

            self._rx_task = asyncio.create_task(self._event_consumer())
            await self._session_ready_event.wait()

            self._active = True
            app_state.begin_voicelive(self.session_id, self.voice or "voice", self.model)
            logger.info(
                "Voice Live GA session started id=%s model=%s voice=%s endpoint=%s",
                self.session_id,
                self.model,
                self.voice,
                settings.voicelive_endpoint,
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Voice Live GA connect failed: %s", exc)
            raise

    async def close(self):
        self._active = False
        try:
            if self._rx_task:
                self._rx_task.cancel()
        except Exception:
            pass
        if self._connection:
            try:
                await self._connection.__aexit__(None, None, None)
            except Exception:
                pass
        if self._mock_task:
            self._mock_task.cancel()
        if self._flush_task:
            self._flush_task.cancel()
            self._flush_task = None
        logger.info("SpeechSession closed id=%s", self.session_id)

    async def send_input_frame(self, frame: bytes):
        if not (self._active and frame and len(frame) == FRAME_BYTES):
            return
        if VOICELIVE_AVAILABLE and self._connection:
            try:
                if not self._session_ready_event.is_set():
                    await self._session_ready_event.wait()

                if not app_state.media.get("started"):
                    return

                if self._using_upsample:
                    out_frames = self._upsample_16k_to_24k_multiple(frame)
                else:
                    out_frames = [frame]

                for out_frame in out_frames:
                    self._input_buffer.extend(out_frame)
                    self._input_frames_buffered += 1

                if self._flush_task:
                    self._flush_task.cancel()
                    self._flush_task = None

                now = time.monotonic()
                flush_due_to_count = self._input_frames_buffered >= self._input_flush_target_frames
                flush_due_to_time = (now - self._last_flush_monotonic) >= self._input_flush_interval_sec
                should_flush = False
                flush_reason = "count" if flush_due_to_count else None
                if not flush_reason and flush_due_to_time:
                    elapsed = now - self._last_flush_monotonic
                    if elapsed >= self._input_flush_max_interval_sec:
                        should_flush = True
                        flush_reason = "max_interval"
                    elif self._input_buffer:
                        delay = max(self._input_flush_interval_sec - elapsed, self._min_flush_delay_sec)
                        self._flush_task = asyncio.create_task(self._flush_after_delay(delay))
                if flush_due_to_count:
                    should_flush = True
                if should_flush and self._input_buffer:
                    await self._flush_input_buffer(flush_reason or "timer")
                elif not flush_reason and self._input_buffer and not self._flush_task:
                    self._flush_task = asyncio.create_task(self._flush_after_delay(self._input_flush_interval_sec))

            except Exception as exc:  # pragma: no cover
                logger.debug("input frame send error: %s", exc)

    async def get_next_outbound_frame(self) -> bytes | None:
        if not self._active:
            return None
        try:
            return self._rx_queue.popleft()
        except IndexError:
            return None

    async def _flush_input_buffer(self, reason: str = "timer"):
        if not self._input_buffer or not self._connection:
            return
        payload = bytes(self._input_buffer)
        frames = self._input_frames_buffered
        energy = None
        if self._debug_input_flush and audioop is not None:
            try:
                energy = audioop.rms(payload, 2)
            except Exception:
                energy = None
        try:
            b64_chunk = base64.b64encode(payload).decode("ascii")
            await self._connection.input_audio_buffer.append(audio=b64_chunk)
            logger.debug(
                "flushed %d frames (%d bytes) to input buffer reason=%s%s",
                frames,
                len(payload),
                reason,
                f" rms={energy}" if energy is not None else "",
            )
        finally:
            self._input_buffer.clear()
            self._input_frames_buffered = 0
            self._last_flush_monotonic = time.monotonic()

    async def _flush_after_delay(self, delay: float):
        try:
            await asyncio.sleep(max(delay, self._min_flush_delay_sec))
            if self._input_buffer:
                await self._flush_input_buffer("timer")
        except asyncio.CancelledError:
            pass
        finally:
            self._flush_task = None

    async def _event_consumer(self):
        try:
            conn = self._connection
            if not conn:
                return
            async for event in conn:
                etype = getattr(event, "type", None)
                logger.debug("voicelive event type=%s", etype)
                if etype == ServerEventType.SESSION_UPDATED or (isinstance(etype, str) and etype.endswith("session.updated")):
                    logger.info("voicelive session is ready, signaling event")
                    self._handle_session_update(event)
                    self._session_ready_event.set()
                elif etype == ServerEventType.RESPONSE_AUDIO_DELTA or (isinstance(etype, str) and etype.endswith("response.audio.delta")):
                    delta = getattr(event, "delta", None)
                    if not delta:
                        continue
                    logger.debug("audio delta bytes=%d", len(delta))
                    self._buffer_out.extend(delta)
                    if self._frame_bytes_dynamic == 640 and len(self._buffer_out) >= 960 and (len(self._buffer_out) % 960 == 0):
                        logger.info("Switching frame size to 960 (detected probable 24kHz audio)")
                        self._frame_bytes_dynamic = 960
                    size = self._frame_bytes_dynamic
                    while len(self._buffer_out) >= size:
                        raw_chunk = bytes(self._buffer_out[:size])
                        del self._buffer_out[:size]
                        frames = self._process_outbound_chunk(raw_chunk)
                        for frame in frames:
                            if len(frame) != self._target_frame_bytes:
                                logger.debug(
                                    "dropping frame len=%d (expected=%d)",
                                    len(frame),
                                    self._target_frame_bytes,
                                )
                                continue
                            if len(self._rx_queue) == self._rx_queue.maxlen:
                                self._frames_dropped += 1
                                from .state import app_state as _as
                                _as.media_out_dropped(1)
                                self._rx_queue.popleft()
                            self._rx_queue.append(frame)
                            self._emitted_frames += 1
                            if self._emitted_frames % 100 == 0:
                                logger.debug(
                                    "outbound frames=%d dropped=%d queue=%d frame_bytes=%d src_frame_bytes=%d",
                                    self._emitted_frames,
                                    self._frames_dropped,
                                    len(self._rx_queue),
                                    self._target_frame_bytes,
                                    size,
                                )
                elif etype == ServerEventType.ERROR:
                    logger.error("VoiceLive error event: %s", getattr(event, 'error', None))
        except asyncio.CancelledError:  # pragma: no cover
            pass
        except Exception as exc:  # pragma: no cover
            logger.debug("event consumer error: %s", exc)

    def _handle_session_update(self, event: object) -> None:
        session_obj = getattr(event, "session", None)
        if not session_obj:
            return
        output_fmt = getattr(session_obj, "output_audio_format", None)
        sample_rate = self._extract_sample_rate(output_fmt)
        if sample_rate:
            prior_rate = self._output_sample_rate
            self._output_sample_rate = int(sample_rate)
            expected_bytes = self._frame_bytes_for_rate(self._output_sample_rate)
            if expected_bytes:
                if expected_bytes != self._frame_bytes_dynamic:
                    logger.info(
                        "detected Voice Live output sample rate=%dHz (frame_bytes=%d)",
                        self._output_sample_rate,
                        expected_bytes,
                    )
                self._frame_bytes_dynamic = expected_bytes
            if prior_rate and prior_rate != self._output_sample_rate:
                self._reset_output_resampler()

    def _extract_sample_rate(self, fmt_obj: object | None) -> Optional[int]:
        if not fmt_obj:
            return None
        candidates = []
        for attr in ("sample_rate", "sample_rate_hertz", "samples_per_second", "sample_rate_hz"):
            value = getattr(fmt_obj, attr, None)
            if value:
                candidates.append(value)
        if not candidates and isinstance(fmt_obj, dict):
            for key in ("sample_rate", "sample_rate_hertz", "samples_per_second", "sampleRate"):
                if key in fmt_obj and fmt_obj[key]:
                    candidates.append(fmt_obj[key])
        for raw in candidates:
            try:
                return int(raw)
            except (TypeError, ValueError):  # pragma: no cover
                continue
        return None

    def _compute_sample_rate(self, frame_bytes: int) -> Optional[int]:
        if frame_bytes <= 0:
            return None
        interval_sec = max(self._frame_interval_ms, 1) / 1000.0
        samples = frame_bytes // 2
        if interval_sec <= 0:
            return None
        return int(round(samples / interval_sec))

    def _frame_bytes_for_rate(self, sample_rate: int) -> Optional[int]:
        if sample_rate <= 0:
            return None
        return int(round(sample_rate * (self._frame_interval_ms / 1000.0) * 2))

    def _process_outbound_chunk(self, chunk: bytes) -> list[bytes]:
        frames: list[bytes] = []
        if not chunk:
            return frames
        buffer = self._outgoing_remainder
        target_rate = self._target_sample_rate
        src_rate = self._output_sample_rate or self._compute_sample_rate(len(chunk))
        if target_rate and src_rate and src_rate != target_rate:
            if src_rate > target_rate and audioop is not None:
                try:
                    converted, self._output_resample_state = audioop.ratecv(
                        chunk, 2, 1, src_rate, target_rate, self._output_resample_state
                    )
                    if converted:
                        buffer.extend(converted)
                except Exception as exc:  # pragma: no cover
                    if not self._output_resample_warned:
                        logger.warning(
                            "output resample failed src=%s dst=%s err=%s",
                            src_rate,
                            target_rate,
                            exc,
                        )
                        self._output_resample_warned = True
                    self._reset_output_resampler()
                    return frames
            elif src_rate > target_rate:
                if not self._output_resample_warned:
                    logger.warning(
                        "audioop unavailable; falling back to naive downsample src=%s dst=%s",
                        src_rate,
                        target_rate,
                    )
                    self._output_resample_warned = True
                fallback = self._fallback_resample_down(chunk, src_rate, target_rate)
                if fallback:
                    buffer.extend(fallback)
            else:
                buffer.extend(chunk)
        else:
            buffer.extend(chunk)

        frame_size = self._target_frame_bytes
        while len(buffer) >= frame_size:
            frames.append(bytes(buffer[:frame_size]))
            del buffer[:frame_size]
        return frames

    def _fallback_resample_down(self, chunk: bytes, src_rate: int, target_rate: int) -> bytes:
        if src_rate <= target_rate or src_rate <= 0 or target_rate <= 0:
            return chunk
        try:
            import array

            src = array.array("h")
            src.frombytes(chunk)
            ratio = src_rate / target_rate
            out_len = max(1, int(round(len(src) / ratio)))
            dst = array.array("h", [0] * out_len)
            pos = 0.0
            for i in range(out_len):
                idx = int(pos)
                if idx >= len(src):
                    idx = len(src) - 1
                dst[i] = src[idx]
                pos += ratio
            return dst.tobytes()
        except Exception as exc:  # pragma: no cover
            logger.debug(
                "fallback downsample failed src=%s dst=%s err=%s",
                src_rate,
                target_rate,
                exc,
            )
            return b""

    def _reset_output_resampler(self) -> None:
        self._output_resample_state = None
        self._outgoing_remainder.clear()
        self._output_resample_warned = False

    def _looks_like_azure_voice(self, v: str | None) -> bool:
        return bool(v and "-" in v and v.lower().endswith("neural"))

    async def _mock_outbound(self):
        samples = FRAME_BYTES // 2
        t = 0.0
        freq = 440.0
        rate = 16000.0
        step = 2 * math.pi * freq / rate
        try:
            while self._active:
                buf = bytearray()
                for _ in range(samples):
                    val = int(6000 * math.sin(t))
                    buf += struct.pack('<h', val)
                    t += step
                self._rx_queue.append(bytes(buf))
                await asyncio.sleep(settings.media_frame_interval_ms / 1000.0)
        except asyncio.CancelledError:  # pragma: no cover
            pass
        except Exception as exc:  # pragma: no cover
            logger.debug("mock outbound err: %s", exc)

    def _upsample_16k_to_24k_multiple(self, frame: bytes) -> list[bytes]:
        if len(frame) != 640:
            return [frame]

        import array

        src = array.array('h')
        src.frombytes(frame)
        out_len = 480
        dst = array.array('h', [0] * out_len)
        ratio = 320 / out_len
        for j in range(out_len):
            s = j * ratio
            i = int(s)
            frac = s - i
            if i >= 319:
                val = src[319]
            else:
                a = src[i]
                b = src[i + 1]
                val = int(a + (b - a) * frac)
            dst[j] = val
        return [dst.tobytes()]

    def _upsample_16k_to_24k(self, frame: bytes) -> bytes:
        return self._upsample_16k_to_24k_multiple(frame)[0]
