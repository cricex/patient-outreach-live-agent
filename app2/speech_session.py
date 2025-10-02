"""Simplified GA speech session wrapper for /app2.

This intentionally keeps a tiny surface:
 - connect(voice, system_prompt) -> establishes session
 - send_input_frame(pcm_20ms)
 - get_next_outbound_frame() -> 20ms frame sized `media_frame_bytes`

Real GA integration can replace the mock paths later.
"""
from __future__ import annotations
import asyncio, os, uuid, logging
from typing import Optional

logger = logging.getLogger("app2.speech")

class SpeechSession:
    def __init__(self, frame_bytes: int = 640) -> None:
        self.session_id: Optional[str] = None
        self.voice: Optional[str] = None
        self._active = False
        self._closed = False
        self._frame_bytes = frame_bytes
        self._seg_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self._assembly = bytearray()
        # SDK objects (lazy) – placeholder fields
        self._push_stream = None
        self._synth = None
        self._rx_mock_task: asyncio.Task | None = None

    @property
    def active(self) -> bool:
        return self._active and not self._closed

    async def connect(self, voice: str, system_prompt: str):
        if self.active:
            return
        self.session_id = str(uuid.uuid4())
        self.voice = voice
        use_mock = False
        try:
            import azure.cognitiveservices.speech as speechsdk  # type: ignore
            from .config import settings
            key, region = settings.speech_key, settings.speech_region
            if not key or not region:
                raise RuntimeError("Missing SPEECH_KEY/SPEECH_REGION")
            speech_cfg = speechsdk.SpeechConfig(subscription=key, region=region)
            if system_prompt:
                # Placeholder property (no-op if unsupported)
                try:
                    speech_cfg.set_service_property("system_prompt", system_prompt, speechsdk.ServicePropertyChannel.UriQueryParameter)
                except Exception:
                    pass
            import azure.cognitiveservices.speech.audio as audio
            self._push_stream = audio.PushAudioInputStream()
            audio_in = audio.AudioConfig(stream=self._push_stream)
            self._synth = speechsdk.SpeechSynthesizer(speech_config=speech_cfg, audio_config=None)
            # Attach synthesizing event for streaming audio out
            if hasattr(self._synth, 'synthesizing'):
                def _on_synth(evt):
                    try:
                        data = evt.result.audio_data
                        if data:
                            self._enqueue_output_bytes(data)
                    except Exception as e:
                        logger.debug("speech synth cb err: %s", e)
                self._synth.synthesizing.connect(_on_synth)  # type: ignore
            self._active = True
            logger.info("SpeechSession connected session_id=%s voice=%s", self.session_id, voice)
        except ModuleNotFoundError:
            logger.warning("azure-cognitiveservices-speech not installed; mock synth enabled")
            use_mock = True
        except Exception as e:
            logger.warning("SpeechSession init failed – mock mode (%s)", e)
            use_mock = True
        if use_mock:
            self._active = True
            if os.getenv("APP2_ENABLE_MOCK_AUDIO", "false").lower() == "true":
                self._rx_mock_task = asyncio.create_task(self._mock_outbound())
            logger.info("SpeechSession mock active session_id=%s voice=%s", self.session_id, voice)

    async def close(self):
        if self._closed:
            return
        self._closed = True
        self._active = False
        if self._rx_mock_task:
            self._rx_mock_task.cancel()
            try: await self._rx_mock_task
            except Exception: pass
        logger.info("SpeechSession closed session_id=%s", self.session_id)

    async def send_input_frame(self, pcm_frame: bytes):
        if not self.active or not pcm_frame:
            return
        if len(pcm_frame) != self._frame_bytes:
            logger.debug("input frame size unexpected=%d expected=%d", len(pcm_frame), self._frame_bytes)
        if self._push_stream is not None:
            try:
                self._push_stream.write(pcm_frame)
            except Exception as e:
                logger.debug("push_stream write err: %s", e)
        # mock does nothing

    async def get_next_outbound_frame(self) -> bytes | None:
        if not self.active:
            return None
        try:
            return await asyncio.wait_for(self._seg_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None

    def _enqueue_output_bytes(self, data: bytes):
        if not data:
            return
        self._assembly.extend(data)
        fb = self._frame_bytes
        while len(self._assembly) >= fb:
            frame = bytes(self._assembly[:fb])
            del self._assembly[:fb]
            if self._seg_queue.full():
                try: _ = self._seg_queue.get_nowait()
                except Exception: break
            try: self._seg_queue.put_nowait(frame)
            except Exception: break

    async def _mock_outbound(self):
        try:
            import math, struct
            sr = 16000
            samples_per_frame = self._frame_bytes // 2
            t = 0
            while self.active:
                frame = bytearray()
                for i in range(samples_per_frame):
                    val = int(5000 * math.sin(2 * math.pi * 440 * (t + i)/sr))
                    frame.extend(struct.pack('<h', val))
                t += samples_per_frame
                if not self._seg_queue.full():
                    await self._seg_queue.put(bytes(frame))
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("mock outbound err: %s", e)
