"""GA Voice Live session abstraction (Azure Speech SDK based).

Preview-era websocket logic and custom VAD have been removed. This
implementation focuses solely on:
 - Pushing 16 kHz PCM frames (caller audio) into a Speech SDK
     PushAudioInputStream.
 - Receiving synthesized audio (agent voice) via synthesizing events
     and segmenting into fixed 20 ms (640-byte) frames for ACS pacing.
 - Maintaining minimal session metadata (session_id, voice).

Extensible areas (future): transcription callbacks, barge-in APIs, and
true full-duplex conversation once GA exposes richer primitives.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("voice_live_ga")


class VoiceLiveSessionGA:
    """Lightweight placeholder for GA Voice Live session.

    This class intentionally avoids importing the preview websocket
    stack. Once the GA SDK package name and classes are known, wire
    them in here.
    """

    # Suggested contract constants (refine when GA docs are final)
    SUPPORTED_INPUT_RATE = 16000  # bytes passed in are expected 16k mono PCM16

    def __init__(self, endpoint: str | None = None, api_key: str | None = None):  # endpoint/api_key kept for forward compatibility (unused)
        self.endpoint = (endpoint or "").rstrip('/') if endpoint else None
        self.api_key = api_key
        self.session_id: Optional[str] = None
        self.voice: Optional[str] = None
        self._closed = False
        self._active = False
        # Downlink pacing queue (aligned with preview implementation pattern)
        self._seg_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self._seg_frame_bytes = int(os.getenv("MEDIA_FRAME_BYTES", "640"))  # 20ms @16k
        # Internal buffer for partial frames (if GA SDK yields variable sizes)
        self._assembly = bytearray()
        # Background receive task placeholder
        self._rx_task: Optional[asyncio.Task] = None
        logger.debug("VoiceLiveSessionGA instantiated endpoint=%s", self.endpoint)
        # GA speech SDK objects (lazy init)
        self._speech_cfg = None
        self._push_stream = None
        self._audio_in = None
        self._rt_client = None  # placeholder for future real-time client
        self._output_handler_attached = False

    # ------------------------------------------------------------------
    # Public properties / state
    # ------------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self._active and not self._closed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def connect(self, model: str | None, voice: str, system_prompt: str) -> None:
        """Establish a GA session.

        TODO(GA): Replace placeholder with real SDK client creation.
        Expected steps:
          - Instantiate GA client (auth with api_key / Azure identity)
          - Configure conversation (model, voice, instructions)
          - Register audio + event callbacks (enqueue outbound PCM into _seg_queue)
        """
        if self.active:
            return
        self.session_id = str(uuid.uuid4())
        self.voice = voice
        # Attempt GA Speech SDK initialization if available
        use_mock = False
        try:
            import azure.cognitiveservices.speech as speechsdk  # type: ignore
            from .config import settings
            key = settings.speech_key
            region = settings.speech_region
            if not key or not region:
                raise RuntimeError("Missing SPEECH_KEY / SPEECH_REGION for GA implementation")
            self._speech_cfg = speechsdk.SpeechConfig(subscription=key, region=region)
            # System prompt & model mapping (placeholder – adjust when GA adds explicit conversation configuration)
            if system_prompt:
                try:
                    self._speech_cfg.set_property(speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption, "True")  # harmless placeholder
                except Exception:
                    pass
            # Input push stream
            import azure.cognitiveservices.speech.audio as audio
            self._push_stream = audio.PushAudioInputStream()
            self._audio_in = audio.AudioConfig(stream=self._push_stream)
            # Output audio: choose pull or event. Here we'll attach a synthesis callback via SpeechSynthesizer.
            # NOTE: This is a simplification until GA realtime duplex API specifics are confirmed.
            self._synthesizer = speechsdk.SpeechSynthesizer(speech_config=self._speech_cfg, audio_config=None)

            def _synth_cb(evt):
                try:
                    # evt.result.audio_data is bytes (may be large); segment and enqueue
                    data = evt.result.audio_data
                    if not data:
                        return
                    self._enqueue_output_bytes(data)
                except Exception as cb_err:
                    logger.debug("GA-VOICE-LIVE synth callback error: %s", cb_err)

            if hasattr(self._synthesizer, 'synthesizing'):  # event exists in SDK
                self._synthesizer.synthesizing.connect(_synth_cb)  # type: ignore
                self._output_handler_attached = True

            # Placeholder: prime greeting or system prompt validation by synthesizing a silent marker (optional)
            if os.getenv("GA_VOICE_LIVE_PRIME", "false").lower() == "true":
                try:
                    _ = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._synthesizer.speak_text_async(" ").get(),
                    )
                except Exception:
                    pass
            self._active = True
            logger.info(
                "GA-VOICE-LIVE CONNECT speech_sdk session_id=%s region=%s voice=%s", self.session_id, region, voice
            )
        except ModuleNotFoundError:
            logger.warning(
                "GA-VOICE-LIVE azure-cognitiveservices-speech not installed; falling back to mock (pip install azure-cognitiveservices-speech)"
            )
            use_mock = True
        except Exception as e:
            logger.warning("GA-VOICE-LIVE init failed (%s); enabling mock fallback", e)
            use_mock = True

        if use_mock:
            self._active = True
            self._rx_task = asyncio.create_task(self._mock_receive())
            logger.info(
                "GA-VOICE-LIVE MOCK active session_id=%s model=%s voice=%s", self.session_id, model, voice
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._active = False
        if self._rx_task:
            self._rx_task.cancel()
            try:
                await self._rx_task
            except Exception:
                pass
        logger.info("GA-VOICE-LIVE CLOSED session_id=%s", self.session_id)

    # ------------------------------------------------------------------
    # Input (caller -> model)
    # ------------------------------------------------------------------
    async def send_input_audio_frame(self, pcm_frame: bytes) -> None:
        """Send a single PCM16 frame to the GA service.

        TODO(GA): Feed audio to GA SDK's input stream / push API.
        Assumes pcm_frame is 20ms @16k (640 bytes). If GA requires a
        different format, perform conversion here (centralized).
        """
        if not self.active or not pcm_frame:
            return
        if len(pcm_frame) != self._seg_frame_bytes:
            logger.debug(
                "GA-VOICE-LIVE frame size unexpected bytes=%d expected=%d", len(pcm_frame), self._seg_frame_bytes
            )
        # Feed push stream if SDK initialized
        if self._push_stream is not None:
            try:
                # Write raw PCM16 little-endian
                self._push_stream.write(pcm_frame)
            except Exception as w_err:
                logger.debug("GA-VOICE-LIVE push_stream write error: %s", w_err)
        # Else no-op (mock mode)

    # ------------------------------------------------------------------
    # Output (model -> caller)
    # ------------------------------------------------------------------
    async def get_next_outbound_frame(self) -> bytes | None:
        """Return the next fixed-size PCM frame for downstream pacing.

        Mirrors the preview interface so the pacer in main.py continues
        to function unchanged.
        """
        if not self.active:
            return None
        try:
            return await asyncio.wait_for(self._seg_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None

    # ------------------------------------------------------------------
    # Internal: segment arbitrary byte payload into fixed frames
    # ------------------------------------------------------------------
    def _enqueue_output_bytes(self, data: bytes):
        if not data:
            return
        self._assembly.extend(data)
        frame_size = self._seg_frame_bytes
        frames = 0
        while len(self._assembly) >= frame_size:
            chunk = bytes(self._assembly[:frame_size])
            del self._assembly[:frame_size]
            if self._seg_queue.full():  # drop oldest
                try:
                    _ = self._seg_queue.get_nowait()
                except Exception:
                    break
            try:
                self._seg_queue.put_nowait(chunk)
                frames += 1
            except Exception:
                break
        if frames and logger.isEnabledFor(logging.DEBUG):
            logger.debug("GA-VOICE-LIVE enqueued frames=%d backlog=%d", frames, self._seg_queue.qsize())

    # ------------------------------------------------------------------
    # Internal helpers / mock receive
    # ------------------------------------------------------------------
    async def _mock_receive(self):
        """Optional placeholder to simulate small trickle of audio.

        This aids early wiring tests without requiring the GA service to
        be live. Remove once real integration is complete.
        """
        try:
            # Only emit mock audio if explicitly enabled (avoids confusion)
            if os.getenv("GA_VOICE_LIVE_ENABLE_MOCK", "false").lower() != "true":
                return
            import math, struct
            sample_rate = 16000
            frame_samples = self._seg_frame_bytes // 2  # 2 bytes per sample
            t = 0
            freq = 440
            logger.info("GA-VOICE-LIVE MOCK audio enabled")
            while self.active:
                # Generate simple sine wave frame
                frame = bytearray()
                for i in range(frame_samples):
                    val = int(8000 * math.sin(2 * math.pi * freq * (t + i) / sample_rate))
                    frame.extend(struct.pack('<h', val))
                t += frame_samples
                if not self._seg_queue.full():
                    await self._seg_queue.put(bytes(frame))
                await asyncio.sleep(0.02)  # 20ms pacing
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("GA-VOICE-LIVE mock receive error: %s", e)


# Factory (optional future use if needed directly)
def create_ga_session(endpoint: str | None, api_key: str | None) -> VoiceLiveSessionGA:
    return VoiceLiveSessionGA(endpoint, api_key)
