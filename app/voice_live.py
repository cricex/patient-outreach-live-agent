"""Voice Live websocket session management and ACS media bridging helpers."""

import asyncio
import json
import logging
import os
import uuid
import math
from typing import Callable, Optional, List, Awaitable

try:  # optional (some slim builds may omit audioop)
    import audioop  # type: ignore
except Exception:  # pragma: no cover
    audioop = None  # type: ignore

import websockets
from urllib.parse import urlparse, urlencode

logger = logging.getLogger("voice_live")

# Log library version for sanity
logger.info("websockets version=%s", getattr(websockets, '__version__', 'unknown'))
from .state import app_state  # for updating format/metrics


class VoiceLiveSession:
    """Manage a realtime Voice Live websocket session and audio buffering flow."""
    def __init__(self, endpoint: str, api_key: str):
        self.endpoint = endpoint.rstrip('/')
        self.api_key = api_key
        self.session_id: Optional[str] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._closed = False
        self._event_type_count = 0
        self._event_type_limit = 10
        self.voice: Optional[str] = None
        self._response_started = False
        # Downlink audio buffering (raw PCM 16k/16-bit mono)
        self._downlink_queue = asyncio.Queue(maxsize=16)
        self._current_burst_active = False
        # Outbound (to ACS) segmentation buffer
        self._seg_buffer = bytearray()
        self._seg_frame_bytes = int(os.getenv("MEDIA_FRAME_BYTES", "640"))
        self._seg_queue = asyncio.Queue(maxsize=64)
        self._source_frame_ms = float(os.getenv("MEDIA_FRAME_INTERVAL_MS", "20"))
        # 20ms @16k mono 16-bit by default -> 640 bytes -> 320 samples
        self._source_input_rate = int(os.getenv("MEDIA_SOURCE_SAMPLE_RATE", "16000"))
        self._assumed_input_rate = int(os.getenv("VOICE_LIVE_ASSUME_INPUT_RATE", "24000"))
        self._assumed_output_rate = int(os.getenv("VOICE_LIVE_ASSUME_OUTPUT_RATE", "24000"))
        # Inbound (from ACS -> Voice Live) commit batching
        self._in_commit_every = max(1, int(os.getenv("MEDIA_VL_IN_COMMIT_EVERY", "1")))
        self._in_frame_counter = 0
        self._in_accum_buf = bytearray()
        self._in_accum_frames = 0
        self._in_frames_since_commit = 0
        self._in_ms_since_commit = 0.0
        # Resampling state for model output -> 16k
        self._target_rate = 16000
        self._requested_input_rate = self._source_input_rate
        self._requested_output_rate = 16000
        self._model_output_rate: Optional[int] = None
        self._resample_state = None
        self._saw_format_update = False
        # Improved commit gating state
        self._last_commit_ms = 0.0
        self._commit_empty_errors = 0
        self._awaiting_commit_ack = False
        self._speech_active = False  # from VL event
        self._speech_detected = False  # from our RMS analysis
        self._had_speech_since_last_commit = False
        self._silence_after_speech_ms = 0.0  # for commit-on-silence
        # Response/commit control enhancements
        self._response_active = False  # model currently streaming a response
        self._commit_cooldown_frames = 0  # suppress commits until this decrements to 0 (after commit_empty)
        self._min_commit_total_floor_ms = 180  # floor for (adaptive + safety)
        # Adaptive speech detection & commit diagnostics
        self._dynamic_rms_enabled = os.getenv("VL_DYNAMIC_RMS", "true").lower() == "true"
        from .config import settings as _cfg_vad
        # Centralized VAD + commit tuning (bootstrap + steady state)
        self._dynamic_rms_offset = _cfg_vad.vl_dynamic_rms_offset  # steady-state additive offset
        self._dynamic_rms_min = int(os.getenv("VL_DYNAMIC_RMS_MIN", str(_cfg_vad.vl_dynamic_rms_min)))
        self._dynamic_rms_max = int(os.getenv("VL_DYNAMIC_RMS_MAX", str(_cfg_vad.vl_dynamic_rms_max)))
        self._min_speech_frames_for_commit = _cfg_vad.vl_min_speech_frames  # steady-state requirement
        self._max_buffer_commit_ms = _cfg_vad.vl_max_buffer_ms
        # Bootstrap phase – lower thresholds to capture first utterance rapidly
        self._bootstrap_deadline = None  # set when first audio arrives
        self._bootstrap_active = True
        self._bootstrap_duration_ms = _cfg_vad.vl_bootstrap_duration_ms
        self._bootstrap_offset = _cfg_vad.vl_bootstrap_rms_offset
        self._bootstrap_min_frames = _cfg_vad.vl_bootstrap_min_speech_frames
        # Adaptive offset decay (during bootstrap hunt for speech)
        self._offset_decay_step = _cfg_vad.vl_offset_decay_step
        self._offset_decay_interval_ms = _cfg_vad.vl_offset_decay_interval_ms
        self._offset_decay_min = _cfg_vad.vl_offset_decay_min
        self._last_decay_check_ms = 0.0
        # Early silence commit threshold
        self._silence_commit_ms_threshold = _cfg_vad.vl_silence_commit_ms
        # Commit even if no speech after this many ms (to avoid starvation / allow model turn); configurable
        self._no_speech_commit_ms = int(os.getenv("VL_NO_SPEECH_COMMIT_MS", "600"))  # 0 disables
        # Allow no-speech timeout even if there was earlier speech after a number of consecutive low-speech blocks
        self._no_speech_low_speech_blocks = int(os.getenv("VL_NO_SPEECH_LOW_SPEECH_BLOCKS", "3"))
        # Diagnostics flags (instrumentation only)
        self._first_frame_diag_done = False
        self._session_updated_monotonic = None
        self._no_input_watchdog_started = False
        # Barge-in detection (interrupt agent audio when user starts speaking)
        self._barge_in_enabled = _cfg_vad.vl_barge_in_enabled
        self._barge_in_offset = _cfg_vad.vl_barge_in_offset
        self._barge_in_consecutive = _cfg_vad.vl_barge_in_consecutive_frames
        self._barge_in_frames = 0
        self._barge_in_triggered = False
        # Enhanced barge-in gating (added)
        self._barge_in_candidate_start_ms: float | None = None
        self._barge_in_last_trigger_ms: float = 0.0
        self._barge_in_release_counter: int = 0
        self._agent_burst_start_ms: float | None = None
        # First commit timing metrics
        self._first_audio_monotonic = None
        self._first_commit_monotonic = None
        self._first_commit_logged = False
        # Low-speech block escalation counter
        self._low_speech_block_count = 0
        # --- Instrumentation counters (no behavioral change) ---
        self._frames_during_ack = 0            # frames appended while awaiting commit ack
        self._total_frames_during_ack = 0      # cumulative diagnostic
        self._successful_commits = 0           # count of commits acknowledged by service
        self._frames_since_successful_commit = 0  # frames appended after last successful commit (excludes during-ack)
        self._last_successful_commit_monotonic = None
        # Staging buffer: frames arriving while a commit ack is outstanding (we now buffer instead of sending)
        self._staged_frames: List[bytes] = []
        # Legacy latch flag referenced in debug lines; ensure it exists to avoid AttributeError
        self._commit_ready = False
        # Noise / dynamic threshold tracking
        self._noise_rms_samples = []
        self._noise_rms_window = 50
        self._current_dynamic_threshold = None
        # Commit diagnostics accumulators
        self._commit_accum_audio_bytes = 0
        self._commit_accum_speech_frames = 0
        self._commit_accum_rms_sum = 0
        self._commit_accum_rms_count = 0
        self._commit_accum_rms_peak = 0
        # Dynamic input rate / frame sizing & adaptive threshold
        self._input_rate: Optional[int] = None
        self._frame_ms_in = self._source_frame_ms  # actual ACS frame duration
        from .config import settings as _settings_init
        self._adaptive_min_ms = _settings_init.vl_input_min_ms
        self._safety_ms = _settings_init.vl_input_safety_ms
        # Minimum user speech duration (ms) required before permitting a normal silence commit
        self._commit_min_user_ms = _settings_init.vl_commit_min_user_ms
        self._threshold_frames = 0
        self._recompute_threshold(force=True)
        self._accum_started_monotonic = None
        self._input_resample_state = None  # track upsampling state
        self._input_format_ready = False
        self._waiting_for_format_logged = False
        # Forced rate overrides (optional)
        try:
            from .config import settings as _cfg_rate
            if _cfg_rate.voice_live_force_input_rate:
                self._input_rate = int(_cfg_rate.voice_live_force_input_rate)
                self._assumed_input_rate = self._input_rate
                self._requested_input_rate = self._input_rate
                self._frame_ms_in = self._source_frame_ms
                self._recompute_threshold(force=True)
                self._input_format_ready = True
                logger.warning(
                    "VOICE-LIVE INPUT RATE forced rate=%d frame_ms_in=%.2f threshold_frames=%d",
                    self._input_rate,
                    self._frame_ms_in,
                    self._threshold_frames,
                )
            if _cfg_rate.voice_live_force_output_rate:
                self._model_output_rate = int(_cfg_rate.voice_live_force_output_rate)
                self._assumed_output_rate = self._model_output_rate
                logger.warning("VOICE-LIVE OUTPUT RATE forced rate=%d", self._model_output_rate)
        except Exception as _fr_err:
            logger.debug("Force rate override parse error: %s", _fr_err)
        # Patch marker: confirm new staging/buffering logic active
        logger.info("VOICE-LIVE PATCH INIT staging_enabled=1 commit_ready_flag_added=1")

    def _recompute_threshold(self, force: bool = False):
        """Recalculate frame thresholds when runtime settings change."""
        import math
        if self._frame_ms_in <= 0:
            self._frame_ms_in = 20.0
        total_ms = self._adaptive_min_ms + self._safety_ms
        frames = max(1, math.ceil(total_ms / self._frame_ms_in))
        if force or frames != self._threshold_frames:
            self._threshold_frames = frames

    @property
    def active(self) -> bool:
        """Return ``True`` when the websocket is connected and not closed."""
        return self._ws is not None and not self._closed

    async def connect(self, model: str, voice: str, system_prompt: str) -> None:
        """Establish the Voice Live websocket session and negotiate audio formats."""
        if self.active:
            return
        supplied_host_override = os.getenv("VOICE_LIVE_OPENAI_HOST")
        if supplied_host_override:
            openai_host = supplied_host_override
        else:
            parsed = urlparse(self.endpoint)
            host = parsed.netloc
            if host.endswith("services.ai.azure.com"):
                openai_host = host.replace("services.ai.azure.com", "openai.azure.com")
            elif host.endswith("cognitiveservices.azure.com"):
                openai_host = host.replace("cognitiveservices.azure.com", "openai.azure.com")
            else:
                openai_host = host
        deployment_name = os.getenv("VOICE_LIVE_DEPLOYMENT", model)
        api_version = os.getenv("VOICE_LIVE_API_VERSION", "2025-04-01-preview")
        uri = f"wss://{openai_host}/openai/realtime?api-version={api_version}&deployment={deployment_name}"
        headers = [
            ("api-key", self.api_key),
            ("OpenAI-Beta", "realtime=v1"),
        ]
        origin = f"https://{openai_host}"
        if os.getenv("VOICE_LIVE_SEND_ORIGIN", "true").lower() == "true":
            headers.append(("Origin", origin))
        self.session_id = str(uuid.uuid4())
        logger.info(
            "VOICE-LIVE HANDSHAKE uri=%s deployment=%s model_param=%s headers=api-key,OpenAI-Beta session_id=%s",
            uri.replace(api_version, "<ver>"), deployment_name, model, self.session_id,
        )
        subprotocol_candidates = [
            p.strip() for p in os.getenv("VOICE_LIVE_PROTOCOLS", "realtime,openai-realtime,realtime-v1").split(',') if p.strip()
        ]
        last_err = None
        for idx, subp in enumerate(subprotocol_candidates, start=1):
            try:
                logger.info("VOICE-LIVE TRY SUBPROTOCOL %d/%d=%s", idx, len(subprotocol_candidates), subp)
                self._ws = await websockets.connect(
                    uri,
                    additional_headers=headers,
                    subprotocols=[subp],
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=30,
                    ping_timeout=10,
                )
                logger.info("VOICE-LIVE CONNECTED 101 subprotocol=%s", subp)
                break
            except Exception as e:
                last_err = e
                logger.warning("VOICE-LIVE SUBPROTOCOL FAIL %s: %s", subp, e)
                self._ws = None
        if not self._ws:
            raise last_err if last_err else RuntimeError("Voice Live connection failed (all subprotocols)")
        logger.info("VOICE-LIVE CONNECTED 101 model=%s deployment=%s", model, deployment_name)
        # Send initial configure frame
        supported_voices = [
            "alloy","ash","ballad","coral","echo","sage","shimmer","verse","marin","cedar"
        ]
        resolved_voice = voice
        if voice not in supported_voices:
            fallback = os.getenv("VOICE_LIVE_FALLBACK_VOICE", supported_voices[0])
            logger.warning("VOICE-LIVE Unsupported voice '%s' -> falling back to '%s' (supported=%s)", voice, fallback, supported_voices)
            resolved_voice = fallback if fallback in supported_voices else supported_voices[0]
        self.voice = resolved_voice
        # Initial update (voice + instructions). Format negotiation handled dynamically once session.updated arrives.
        base_update = {
            "type": "session.update",
            "session": {
                "instructions": system_prompt,
                "voice": resolved_voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
            },
        }
        self._format_retry_sent = False
        await self._ws.send(json.dumps(base_update))

    async def send_audio_frame(self, pcm16_le_16k_mono: bytes) -> None:
        if not self.active:
            return
        # For now Voice Live input channel not defined; placeholder for future binary send.
        # If service later accepts binary audio, implement here.
        return

    async def send_input_audio_frame(self, pcm_frame: bytes) -> None:
        """Send a single 20ms PCM frame to Voice Live realtime API as input audio.
        Sends one append per frame; issues commit after threshold (>=100ms worth). This avoids race where
        append+commit in same loop results in service reporting empty buffer.
        """
        if not self.active or not pcm_frame:
            return
        if not self._input_format_ready:
            if not self._waiting_for_format_logged:
                logger.debug("VL-IN waiting for session.updated before sending input audio")
                self._waiting_for_format_logged = True
            return
            if len(pcm_frame) != self._seg_frame_bytes:  # Enforce expected 20ms size; skip otherwise
                return
        # NEW: If we're currently awaiting a commit acknowledgement, buffer (stage) this frame locally
        # instead of sending it immediately. Previously we still sent frames, causing the service-side
        # buffer (which had just been committed/reset) to appear empty when the commit arrived, yielding
        # input_audio_buffer_commit_empty errors and starving the dialog.
        if self._awaiting_commit_ack:
            self._staged_frames.append(pcm_frame)
            self._frames_during_ack += 1
            if logger.isEnabledFor(logging.DEBUG) and (len(self._staged_frames) == 1 or len(self._staged_frames) % 25 == 0):
                logger.debug(
                    "VL-IN staging frame count=%d (awaiting commit ack)", len(self._staged_frames)
                )
            return
        from .config import settings as _settings
        import base64
        try:
            # If model expects higher input rate (e.g., 24000) and differs from ACS 16k, upsample this 20ms frame
            send_bytes = pcm_frame
            target_rate = self._input_rate or self._assumed_input_rate or self._source_input_rate
            source_rate = self._source_input_rate
            effective_rate = target_rate if target_rate else source_rate
            if target_rate != source_rate:
                if audioop is None:
                    logger.warning("VL-IN upsample skipped audioop_missing src=%d dst=%d", source_rate, target_rate)
                else:
                    try:
                        converted, self._input_resample_state = audioop.ratecv(
                            pcm_frame,
                            2,
                            1,
                            source_rate,
                            target_rate,
                            self._input_resample_state,
                        )
                        send_bytes = converted
                        effective_rate = target_rate
                    except Exception as up_err:
                        logger.warning("VL-IN upsample failed src=%d dst=%d err=%s", source_rate, target_rate, up_err)
                        self._input_resample_state = None
                        send_bytes = pcm_frame
                        effective_rate = source_rate
            if not self._first_frame_diag_done:
                try:
                    declared = effective_rate
                    expected_20ms_bytes = int(round(declared * 0.02 * 2)) if declared else -1
                    logger.info(
                        "VL-DIAG FIRST-FRAME bytes=%d expected_20ms=%d declared_rate=%d source_rate=%d target_rate=%d upsample=%s",
                        len(send_bytes), expected_20ms_bytes, declared, source_rate, target_rate, target_rate != source_rate
                    )
                except Exception:
                    pass
                self._first_frame_diag_done = True
            # Compute real frame ms from bytes being appended
            try:
                samples = len(send_bytes) // 2
                if effective_rate > 0:
                    frame_ms_effective = (samples / effective_rate) * 1000.0
                else:
                    frame_ms_effective = self._frame_ms_in
            except Exception:
                frame_ms_effective = self._frame_ms_in
            b64 = base64.b64encode(send_bytes).decode('ascii')
            await self._ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": b64}))
            self._in_frame_counter += 1
            self._in_frames_since_commit += 1
            # Instrumentation: track frames appended while awaiting ack separately
            if self._awaiting_commit_ack:
                self._frames_during_ack += 1
            else:
                self._frames_since_successful_commit += 1
            loop = asyncio.get_event_loop()
            if self._accum_started_monotonic is None:
                self._accum_started_monotonic = loop.time()
            self._in_ms_since_commit += frame_ms_effective
            # Potentially update adaptive min from env if changed dynamically
            self._adaptive_min_ms = max(self._adaptive_min_ms, _settings.vl_input_min_ms)
            # Recompute threshold if currently zero (initial) or env increased beyond previous adaptive value
            self._recompute_threshold()
            
            # Decrement cooldown timer if active
            if self._commit_cooldown_frames > 0:
                self._commit_cooldown_frames -= 1
                if logger.isEnabledFor(logging.DEBUG) and self._commit_cooldown_frames == 0:
                    logger.debug("VL-IN commit cooldown expired")
            
            frame_ms = frame_ms_effective  # use actual appended frame duration
            threshold_frames = self._threshold_frames  # legacy diagnostic
            threshold_ms = self._adaptive_min_ms
            total_threshold_ms = max(self._adaptive_min_ms + self._safety_ms, self._min_commit_total_floor_ms)
            elapsed_ms = 0.0
            if self._accum_started_monotonic is not None:
                elapsed_ms = (loop.time() - self._accum_started_monotonic) * 1000.0
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "VL-IN append frame_idx=%d frames_since_commit=%d ms_since_commit=%.1f threshold_ms=%d safety_ms=%d commit_ready=%s frame_ms=%.2f bytes=%d awaiting_ack=%s",
                    self._in_frame_counter,
                    self._in_frames_since_commit,
                    self._in_ms_since_commit,
                    self._adaptive_min_ms,
                    self._safety_ms,
                    self._commit_ready,
                    frame_ms,
                    len(send_bytes),
                    self._awaiting_commit_ack,
                )
            # Implement RMS-based voice activity detection
            if audioop is not None and len(send_bytes) >= 2:
                try:
                    # Calculate RMS for speech detection (use the bytes we're actually sending)
                    rms = audioop.rms(send_bytes, 2)  # 2 bytes per sample for PCM16
                    loop_now_ms = asyncio.get_event_loop().time() * 1000.0
                    if self._first_audio_monotonic is None:
                        self._first_audio_monotonic = loop_now_ms
                        self._bootstrap_deadline = loop_now_ms + self._bootstrap_duration_ms
                    # Dynamic thresholding
                    if self._dynamic_rms_enabled:
                        # Maintain noise floor: collect rms from clearly low-energy frames (previous threshold or fallback)
                        base_ref = self._current_dynamic_threshold or 500
                        if rms < base_ref * 0.6:  # low-energy candidate
                            self._noise_rms_samples.append(rms)
                            if len(self._noise_rms_samples) > self._noise_rms_window:
                                self._noise_rms_samples.pop(0)
                        noise_floor = None
                        if self._noise_rms_samples:
                            # Use median for robustness
                            sorted_vals = sorted(self._noise_rms_samples)
                            noise_floor = sorted_vals[len(sorted_vals)//2]
                        # Derive dynamic threshold (bootstrap + decay)
                        effective_offset = self._dynamic_rms_offset
                        if self._bootstrap_active and self._bootstrap_deadline is not None:
                            if loop_now_ms <= self._bootstrap_deadline:
                                effective_offset = self._bootstrap_offset
                            else:
                                self._bootstrap_active = False
                        # Decay search while still bootstrap & no speech seen
                        if self._bootstrap_active and not self._had_speech_since_last_commit and noise_floor is not None:
                            if (loop_now_ms - self._last_decay_check_ms) >= self._offset_decay_interval_ms:
                                self._last_decay_check_ms = loop_now_ms
                                if effective_offset > self._offset_decay_min:
                                    effective_offset = max(self._offset_decay_min, effective_offset - self._offset_decay_step)
                                    self._bootstrap_offset = effective_offset  # persist lowered offset
                        # Adjust offset aggressively in ultra-quiet environments so threshold doesn't sit far above true signal
                        adjusted_offset = effective_offset
                        if noise_floor is not None and noise_floor <= 5:
                            adjusted_offset = min(effective_offset, 80)  # clamp offset for near-silence room
                        dyn_thresh = (noise_floor + adjusted_offset) if noise_floor is not None else (500 if adjusted_offset is None else adjusted_offset)
                        if dyn_thresh < self._dynamic_rms_min:
                            dyn_thresh = self._dynamic_rms_min
                        if dyn_thresh > self._dynamic_rms_max:
                            dyn_thresh = self._dynamic_rms_max
                        self._current_dynamic_threshold = dyn_thresh
                        speech_threshold = dyn_thresh
                        self._speech_detected = rms >= speech_threshold
                        # Accumulate commit diagnostics
                        self._commit_accum_audio_bytes += len(send_bytes)
                        if self._speech_detected:
                            self._commit_accum_speech_frames += 1
                        self._commit_accum_rms_sum += rms
                        self._commit_accum_rms_count += 1
                        if rms > self._commit_accum_rms_peak:
                            self._commit_accum_rms_peak = rms
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "VL-IN RMS dyn: rms=%d noise_floor=%s dyn_thresh=%d speech=%s speech_frames=%d", 
                                rms, noise_floor if noise_floor is not None else 'n/a', speech_threshold, self._speech_detected, self._commit_accum_speech_frames
                            )
                            # Additional dynamic threshold instrumentation
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "VL-IN dyn_state base_offset=%d bootstrap=%s adjusted_offset=%d dyn_thresh=%d awaiting_ack=%s frames_during_ack=%d frames_since_success=%d", 
                                    self._dynamic_rms_offset, self._bootstrap_active, adjusted_offset, self._current_dynamic_threshold, 
                                    self._awaiting_commit_ack, self._frames_during_ack, self._frames_since_successful_commit
                                )
                    else:
                        speech_threshold = 500
                        self._speech_detected = rms > speech_threshold
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug("VL-IN RMS static: rms=%d threshold=%d speech_detected=%s", rms, speech_threshold, self._speech_detected)
                except Exception as rms_err:
                    logger.debug("VL-IN RMS calculation failed: %s", rms_err)
                    # Fallback: assume no speech if RMS calculation fails
                    self._speech_detected = False
            else:
                # Fallback: assume no speech if audioop unavailable
                self._speech_detected = False

            # New commit logic (reordered for safety-first):
            # 1. Track speech + silence progression.
            # 2. Max-buffer safety evaluated first so it cannot be starved by low-speech blocks.
            # 3. Silence-after-speech boundary commits.
            # 4. Low-speech escalation if repeated blocks while buffer large.
            if self._speech_detected:
                self._had_speech_since_last_commit = True
                self._silence_after_speech_ms = 0.0
                self._low_speech_block_count = 0
            elif self._had_speech_since_last_commit and self._in_frames_since_commit > 0:
                self._silence_after_speech_ms += frame_ms_effective

            # Enhanced barge-in detection (multi-factor) -----------------------------------------------------
            # Conditions required:
            # 1. Agent currently speaking (burst active) and feature enabled.
            # 2. Agent has spoken at least vl_barge_in_min_agent_ms (grace period) since burst start.
            # 3. User speech candidate sustained >= vl_barge_in_min_user_ms of frames above barge threshold.
            # 4. User RMS must exceed both absolute (noise + offset) AND relative (factor * noise) criteria.
            # 5. Cooldown since last trigger satisfied.
            # 6. Hysteresis: once candidate falls below a lower release threshold for N frames, reset candidate.
            if self._barge_in_enabled and (self._response_active or self._current_burst_active):
                if 'rms' in locals() and self._current_dynamic_threshold is not None:
                    from .config import settings as _cfg_bi
                    loop_now_ms_full = asyncio.get_event_loop().time() * 1000.0
                    # Establish agent burst start time if missing
                    if self._agent_burst_start_ms is None and (self._response_active or self._current_burst_active):
                        self._agent_burst_start_ms = loop_now_ms_full
                    agent_elapsed_ms = 0.0
                    if self._agent_burst_start_ms is not None:
                        agent_elapsed_ms = loop_now_ms_full - self._agent_burst_start_ms
                    # Hard lock window: do not even accumulate candidate within lock period
                    if agent_elapsed_ms < _cfg_bi.vl_barge_in_lock_ms:
                        if self._barge_in_candidate_start_ms is not None:
                            # reset any partial candidate formed before realizing lock window
                            self._barge_in_candidate_start_ms = None
                            self._barge_in_frames = 0
                            self._barge_in_release_counter = 0
                        # Skip rest of barge-in logic during hard lock
                        pass_lock = True
                    else:
                        pass_lock = False
                    # Approximate noise baseline
                    approx_noise = max(1, self._current_dynamic_threshold - self._dynamic_rms_offset)
                    abs_thresh = max(20, approx_noise + self._barge_in_offset)
                    rel_thresh = approx_noise * _cfg_bi.vl_barge_in_relative_factor
                    effective_thresh = max(abs_thresh, rel_thresh)
                    # Compute SNR (dB) using noise baseline
                    snr_db = 0.0
                    if approx_noise > 0:
                        snr_db = 20.0 * math.log10(max(rms, 1) / approx_noise)
                    below_release_thresh = rms < (effective_thresh * 0.65)  # release hysteresis
                    cooldown_ok = (loop_now_ms_full - self._barge_in_last_trigger_ms) >= _cfg_bi.vl_barge_in_cooldown_ms
                    grace_ok = agent_elapsed_ms >= _cfg_bi.vl_barge_in_min_agent_ms
                    # Candidate tracking
                    if (not pass_lock
                        and rms >= effective_thresh
                        and grace_ok and cooldown_ok
                        and snr_db >= _cfg_bi.vl_barge_in_min_snr_db
                        and rms >= _cfg_bi.vl_barge_in_abs_min_rms):
                        if self._barge_in_candidate_start_ms is None:
                            self._barge_in_candidate_start_ms = loop_now_ms_full
                            self._barge_in_frames = 1
                        else:
                            self._barge_in_frames += 1
                    else:
                        # Hysteresis release handling
                        if self._barge_in_candidate_start_ms is not None:
                            if below_release_thresh:
                                self._barge_in_release_counter += 1
                                if self._barge_in_release_counter >= _cfg_bi.vl_barge_in_release_frames:
                                    logger.debug(
                                        "VL-BARGE-RESET reason=release frames=%d rms=%d eff_thresh=%.1f noise=%d", 
                                        self._barge_in_release_counter, rms, effective_thresh, approx_noise
                                    )
                                    self._barge_in_candidate_start_ms = None
                                    self._barge_in_frames = 0
                                    self._barge_in_release_counter = 0
                            else:
                                # Still near threshold; don't yet reset, but decay release counter
                                if self._barge_in_release_counter > 0:
                                    self._barge_in_release_counter = max(0, self._barge_in_release_counter - 1)
                        else:
                            self._barge_in_frames = 0
                    user_ms = 0.0
                    if self._barge_in_candidate_start_ms is not None:
                        user_ms = loop_now_ms_full - self._barge_in_candidate_start_ms
                    # Periodic evaluation logging (every 200ms while candidate active or every ~1s idle)
                    if logger.isEnabledFor(logging.DEBUG):
                        if (self._barge_in_candidate_start_ms and self._barge_in_frames % 5 == 0) or (self._in_frame_counter % 50 == 0):
                            logger.debug(
                                "VL-BARGE-EVAL rms=%d noise=%d abs=%.1f rel=%.1f eff=%.1f snr_db=%.1f user_ms=%.1f agent_ms=%.1f frames=%d grace=%s cooldown=%s lock=%s candidate=%s release_frames=%d", 
                                rms, approx_noise, abs_thresh, rel_thresh, effective_thresh, snr_db, user_ms, agent_elapsed_ms, self._barge_in_frames, 
                                grace_ok, cooldown_ok, agent_elapsed_ms < _cfg_bi.vl_barge_in_lock_ms, self._barge_in_candidate_start_ms is not None, self._barge_in_release_counter
                            )
                    trigger_ready = (
                        self._barge_in_candidate_start_ms is not None
                        and user_ms >= _cfg_bi.vl_barge_in_min_user_ms
                        and grace_ok and cooldown_ok
                        and snr_db >= _cfg_bi.vl_barge_in_min_snr_db
                        and rms >= _cfg_bi.vl_barge_in_abs_min_rms
                    )
                    if trigger_ready and not self._barge_in_triggered:
                        self._barge_in_triggered = True
                        self._barge_in_last_trigger_ms = loop_now_ms_full
                        self._response_active = False
                        self._current_burst_active = False
                        dropped = 0
                        try:
                            while not self._seg_queue.empty():
                                _ = self._seg_queue.get_nowait(); dropped += 1
                        except Exception:
                            pass
                        logger.info(
                            "VL-BARGE-IN TRIGGER rms=%d noise=%d eff=%.1f snr_db=%.1f user_ms=%.1f agent_ms=%.1f frames=%d dropped_out_frames=%d", 
                            rms, approx_noise, effective_thresh, snr_db, user_ms, agent_elapsed_ms, self._barge_in_frames, dropped
                        )
                        # Commit immediately if we have enough local speech frames buffered
                        if self._commit_accum_speech_frames >= max(self._bootstrap_min_frames, self._min_speech_frames_for_commit):
                            await self._commit_now("barge_in")
                        # Reset candidate after trigger so new speech requires fresh buildup
                        self._barge_in_candidate_start_ms = None
                        self._barge_in_frames = 0
                        self._barge_in_release_counter = 0

            commit_now = False
            trigger = ""

            # (A) Max-buffer safety first
            if self._in_frames_since_commit > 0 and self._in_ms_since_commit >= self._max_buffer_commit_ms:
                # ADDED: Only trigger safety commit if there's actual speech to send
                if self._commit_accum_speech_frames > 0:
                    commit_now = True
                    trigger = "max_buffer_safety"
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "VL-IN max_buffer_safety triggered: ms_since_commit=%.1f awaiting_ack=%s cooldown=%d speech_frames=%d",
                            self._in_ms_since_commit, self._awaiting_commit_ack, self._commit_cooldown_frames, self._commit_accum_speech_frames
                        )
                else:
                    # If it's all silence, just clear the buffer and reset timing
                    self._in_frames_since_commit = 0
                    self._in_ms_since_commit = 0.0
                    self._accum_started_monotonic = None
                    self._commit_accum_audio_bytes = 0
                    self._commit_accum_speech_frames = 0
                    self._commit_accum_rms_sum = 0
                    self._commit_accum_rms_count = 0
                    self._commit_accum_rms_peak = 0
                    logger.debug("VL-IN max_buffer_safety skipped (no speech), buffer cleared")


            # (A2) No-speech timeout / prolonged low-speech starvation safeguard.
            # Fires when buffer age exceeds threshold AND either no speech at all OR repeated low-speech blocks.
            if (not commit_now
                and self._no_speech_commit_ms > 0
                and self._in_frames_since_commit > 0
                and self._in_ms_since_commit >= self._no_speech_commit_ms):
                eligible = False
                reason = None
                if not self._had_speech_since_last_commit:
                    eligible = True
                    reason = "no_prior_speech"
                elif self._low_speech_block_count >= self._no_speech_low_speech_blocks:
                    eligible = True
                    reason = f"low_speech_blocks>={self._no_speech_low_speech_blocks}"
                else:
                    reason = "had_prior_speech_insufficient_blocks"
                if eligible:
                    commit_now = True
                    trigger = "no_speech_timeout"
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "VL-IN no_speech_timeout triggered: ms_since_commit=%.1f threshold=%d reason=%s blocks=%d", 
                            self._in_ms_since_commit, self._no_speech_commit_ms, reason, self._low_speech_block_count
                        )
                else:
                    # Rate-limit suppression logging (every 25 frames while over threshold)
                    if logger.isEnabledFor(logging.DEBUG) and (self._in_frames_since_commit % 25 == 0):
                        logger.debug(
                            "VL-IN no_speech_timeout suppressed reason=%s ms_since_commit=%.1f blocks=%d blocks_needed=%d had_speech=%s", 
                            reason, self._in_ms_since_commit, self._low_speech_block_count, self._no_speech_low_speech_blocks, self._had_speech_since_last_commit
                        )

            # (B) Silence boundary (only if safety didn't already trigger)
            if not commit_now and self._had_speech_since_last_commit and self._in_frames_since_commit > 0:
                if self._silence_after_speech_ms >= self._silence_commit_ms_threshold:
                    commit_now = True
                    trigger = "silence_after_speech"

            # Enforce minimum speech frames requirement (unless forced by max_buffer_safety)
            if commit_now and trigger != "max_buffer_safety" and self._min_speech_frames_for_commit > 0:
                if self._commit_accum_speech_frames < self._min_speech_frames_for_commit:
                    commit_now = False
                    self._low_speech_block_count += 1
                    try:
                        app_state.media_commit_block("low_speech")
                    except Exception:
                        pass
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "VL-IN commit blocked low_speech frames=%d required=%d ms_buf=%.1f blocks=%d",
                            self._commit_accum_speech_frames,
                            self._min_speech_frames_for_commit,
                            self._in_ms_since_commit,
                            self._low_speech_block_count,
                        )
                    # Escalate after several blocks if buffer already exceeded safety threshold
                    if self._low_speech_block_count >= 3 and self._in_ms_since_commit >= self._max_buffer_commit_ms:
                        commit_now = True
                        trigger = "low_speech_escalation"
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "VL-IN low_speech escalation forcing commit frames=%d ms_buf=%.1f blocks=%d",
                                self._commit_accum_speech_frames,
                                self._in_ms_since_commit,
                                self._low_speech_block_count,
                            )

            if commit_now:
                # Additional gating: require minimum accumulated user speech for certain triggers
                if self._commit_min_user_ms > 0 and trigger in ("silence_after_speech",):
                    speech_ms = self._commit_accum_speech_frames * frame_ms_effective
                    if speech_ms < self._commit_min_user_ms:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "VL-IN commit blocked min_user_ms speech_ms=%.1f required=%d trigger=%s frames=%d ms_buf=%.1f", 
                                speech_ms, self._commit_min_user_ms, trigger, self._commit_accum_speech_frames, self._in_ms_since_commit
                            )
                        # Treat as ongoing speech; reset silence timer so we wait for true pause
                        if trigger == "silence_after_speech":
                            self._silence_after_speech_ms = 0.0
                        commit_now = False
                if commit_now:
                    await self._commit_now(trigger)

        except Exception as e:
            logger.debug("VOICE-LIVE send_input_audio_frame error: %s", e)

    async def _commit_now(self, trigger: str):
        """Helper to centralize commit logic."""
        if self._awaiting_commit_ack or self._commit_cooldown_frames > 0:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("VL-IN commit blocked: trigger=%s awaiting_ack=%s cooldown=%d frames=%d ms=%.1f", 
                           trigger, self._awaiting_commit_ack, self._commit_cooldown_frames, 
                           self._in_frames_since_commit, self._in_ms_since_commit)
            return
        # UNIVERSAL GUARD: If zero speech frames have been detected in this buffer, block the commit
        # unless it's a timeout-related trigger, which is meant to flush the buffer regardless.
        if self._commit_accum_speech_frames == 0 and trigger not in ("max_buffer_safety", "no_speech_timeout", "low_speech_escalation"):
            try:
                app_state.media_commit_block("no_speech")
            except Exception:
                pass
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("VL-IN commit blocked (universal guard): no_speech trigger=%s ms_buf=%.1f", trigger, self._in_ms_since_commit)
            return
        
        await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        self._last_commit_ms = asyncio.get_event_loop().time() * 1000.0
        effective_ms = int(self._in_ms_since_commit)
        logger.debug(
            "VL-IN commit_sent frames=%d effective_ms=%d trigger=%s adaptive_min_ms=%d safety_ms=%d local_ms=%.1f dyn_thresh=%s speech_frames=%d audio_bytes=%d",
            self._in_frames_since_commit,
            effective_ms,
            trigger,
            self._adaptive_min_ms,
            self._safety_ms,
            (self._in_frames_since_commit * self._frame_ms_in),
            self._current_dynamic_threshold,
            self._commit_accum_speech_frames,
            self._commit_accum_audio_bytes,
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "VL-IN commit_outstanding awaiting_ack=True frames_during_previous_ack=%d total_frames_during_ack=%d frames_since_success_commit=%d", 
                self._frames_during_ack, self._total_frames_during_ack, self._frames_since_successful_commit
            )
        # Capture speech frames at commit before reset for metrics
        _speech_frames_at_commit = self._commit_accum_speech_frames
        try:
            app_state.media_commit_success(self._in_frames_since_commit, effective_ms, int(self._adaptive_min_ms), trigger=trigger)
            # Emit detailed metrics
            avg_rms = None
            if self._commit_accum_rms_count > 0:
                avg_rms = int(self._commit_accum_rms_sum / self._commit_accum_rms_count)
            app_state.media_commit_detail(
                audio_bytes=self._commit_accum_audio_bytes,
                speech_frames=self._commit_accum_speech_frames,
                rms_avg=avg_rms,
                rms_peak=self._commit_accum_rms_peak,
                dyn_thresh=self._current_dynamic_threshold,
                noise_floor=(sorted(self._noise_rms_samples)[len(self._noise_rms_samples)//2] if self._noise_rms_samples else None),
            )
        except Exception:
            pass
        self._awaiting_commit_ack = True
        self._frames_during_ack = 0  # reset counter for new ack window
        self._in_frames_since_commit = 0
        self._in_ms_since_commit = 0.0
        self._accum_started_monotonic = None
        self._speech_detected = False  # Reset after commit
        self._had_speech_since_last_commit = False # Reset after commit
        self._silence_after_speech_ms = 0.0 # Reset after commit
        # Reset commit accumulators
        self._commit_accum_audio_bytes = 0
        self._commit_accum_speech_frames = 0
        self._commit_accum_rms_sum = 0
        self._commit_accum_rms_count = 0
        self._commit_accum_rms_peak = 0
        # First commit latency log
        if self._first_commit_monotonic is None:
            self._first_commit_monotonic = self._last_commit_ms
            if self._first_audio_monotonic is not None and not self._first_commit_logged:
                latency_ms = self._first_commit_monotonic - self._first_audio_monotonic
                from .config import settings as _cfg_log
                if _cfg_log.vl_log_first_commit:
                    logger.info(
                        "VL-FIRST-COMMIT latency_ms=%.1f trigger=%s speech_frames=%d adaptive_min_ms=%d dyn_thresh=%s local_ms=%.1f", 
                        latency_ms, trigger, _speech_frames_at_commit, self._adaptive_min_ms, self._current_dynamic_threshold, (self._in_frames_since_commit * self._frame_ms_in)
                    )
                self._first_commit_logged = True

    async def receive_loop(self, on_event: Callable[[dict], None | Awaitable[None]]) -> None:
        """Pump Voice Live events, updating state and forwarding audio deltas."""
        if not self.active:
            return
        try:
            async for message in self._ws:
                etype = None
                try:
                    data = json.loads(message)
                    etype = data.get("type")
                except Exception:
                    logger.debug("Non-JSON message length=%d", len(message) if isinstance(message, (bytes, str)) else -1)
                    continue
                if etype:
                    if self._event_type_count < self._event_type_limit:
                        top_keys = list(data.keys())
                        # Redact lengths of any base64-looking fields
                        b64_lens = {}
                        for k,v in data.items():
                            if isinstance(v,str) and len(v) > 16 and all(c.isalnum() or c in '+/=\n' for c in v[:32]):
                                b64_lens[k] = len(v)
                        logger.info("VOICE-LIVE EVENT type=%s keys=%s b64_lens=%s", etype, top_keys, b64_lens)
                        self._event_type_count += 1
                    # If error, log body (only once to avoid noise)
                    if etype == "error":
                        logger.warning("VOICE-LIVE ERROR EVENT payload=%s", data)
                    if etype == "session.updated":
                        # Capture accepted audio formats (service may return simple strings or objects)
                        sess = data.get("session") or {}
                        out_fmt_raw = sess.get("output_audio_format")
                        in_fmt_raw = sess.get("input_audio_format")
                        def _derive_rate(v):
                            # Only trust explicit numeric-bearing objects; bare strings like 'pcm16' are ambiguous
                            if isinstance(v, dict):
                                return v.get("sample_rate_hz") or v.get("sample_rate")
                            # Return None for simple strings; we'll fall back to assumed default (often 24000)
                            return None
                        out_rate = _derive_rate(out_fmt_raw)
                        in_rate = _derive_rate(in_fmt_raw)
                        if not out_rate:
                            out_rate = self._assumed_output_rate
                            logger.warning(
                                "VOICE-LIVE session.updated missing output sample rate; assuming %d Hz",
                                out_rate,
                            )
                        if not in_rate:
                            in_rate = self._assumed_input_rate
                            logger.warning(
                                "VOICE-LIVE session.updated missing input sample rate; assuming %d Hz",
                                in_rate,
                            )
                        if out_rate:
                            try:
                                self._model_output_rate = int(out_rate)
                            except Exception:
                                pass
                        if in_rate:
                            try:
                                self._input_rate = int(in_rate)
                                self._assumed_input_rate = self._input_rate
                                self._requested_input_rate = self._input_rate
                                self._saw_format_update = True
                                self._frame_ms_in = self._source_frame_ms
                                self._recompute_threshold(force=True)
                                self._input_format_ready = True
                                self._waiting_for_format_logged = False
                                self._input_resample_state = None
                                logger.info(
                                    "VOICE-LIVE ACCEPTED input=pcm16/%dHz output=pcm16/%sHz frame_ms_in=%.2f threshold_frames=%d adaptive_min_ms=%d safety_ms=%d",
                                    self._input_rate,
                                    str(self._model_output_rate) if self._model_output_rate else "unknown",
                                    self._frame_ms_in,
                                    self._threshold_frames,
                                    self._adaptive_min_ms,
                                    self._safety_ms,
                                )
                                try:
                                    app_state.media_commit_success(0, 0, int(self._adaptive_min_ms))
                                except Exception:
                                    pass
                            except Exception as fr_err:
                                logger.debug("Failed to set dynamic frame_ms: %s", fr_err)
                        if out_rate or in_rate:
                            try:
                                app_state.voicelive_set_formats(out_rate, in_rate)
                            except Exception:
                                pass
                        # Initial automatic greeting removed (Option 1):
                        # Rationale: allow caller to speak first and avoid preemptive meta responses.
                        # If future behavior requires an optional greeting, guard with env flag below.
                        if os.getenv("VOICE_LIVE_ENABLE_GREETING", "false").lower() == "true" and not self._response_started:
                            try:
                                greeting_text = os.getenv("VOICE_LIVE_GREETING_TEXT", "Hello.")
                                await self._ws.send(json.dumps({
                                    "type": "response.create",
                                    "response": {"modalities": ["audio", "text"], "instructions": greeting_text}
                                }))
                                self._response_started = True
                                logger.info("VOICE-LIVE OPTIONAL greeting sent (env enabled)")
                            except Exception as send_err:
                                logger.warning("VOICE-LIVE optional greeting send failed: %s", send_err)
                        else:
                            if not self._response_started:
                                logger.debug("VOICE-LIVE greeting suppressed (Option 1 hard removal)")
                    # Dynamic audio delta detection
                    lowered = etype.lower()
                    if 'audio' in lowered and 'delta' in lowered:
                        pcm = self._extract_audio_bytes(data)
                        if pcm:
                            # Resample if needed
                            try:
                                rate = self._model_output_rate or 24000  # assume 24k typical if not provided
                                # DO NOT resample if we haven't seen a format update yet.
                                # The initial greeting audio may come before the session.updated event
                                # and is likely at the target rate already.
                                if rate != self._target_rate and self._saw_format_update:
                                    if audioop is None:
                                        logger.warning("audioop_unavailable skip_resample src_rate=%s", rate)
                                    else:
                                        try:
                                            converted, self._resample_state = audioop.ratecv(pcm, 2, 1, rate, self._target_rate, self._resample_state)
                                            out_frames = len(converted) // self._seg_frame_bytes if self._seg_frame_bytes else 0
                                            app_state.media_resample_add(len(pcm), len(converted), out_frames)
                                            pcm = converted
                                        except Exception as e:
                                            logger.warning("resample_failed rate=%s->%s err=%s", rate, self._target_rate, e)
                                            # On failure, do not enqueue the original (likely corrupt) frame.
                                            # The buffer is better off missing a tiny fragment than being corrupted.
                                            pcm = None
                                if pcm:
                                    await self._enqueue_pcm(pcm)
                            except Exception as r_err:
                                logger.debug("VOICE-LIVE resample error: %s", r_err)
                    # Track response lifecycle
                    if 'response.audio.delta' in lowered or 'response.content_part.added' in lowered or 'response.output_item.added' in lowered:
                        self._response_active = True
                        self._current_burst_active = True
                        # Mark the start of a new agent burst (used for barge-in grace timing)
                        if self._agent_burst_start_ms is None:
                            self._agent_burst_start_ms = asyncio.get_event_loop().time() * 1000.0
                    if 'response.audio.done' in lowered or 'response.done' in lowered:
                        self._current_burst_active = False
                        logger.debug("VL-OUT audio response completed, final queue_size=%d buffer_bytes=%d", 
                                   self._seg_queue.qsize(), len(self._seg_buffer))
                        self._response_active = False
                        # Reset agent burst timing & barge-in state for next response
                        self._agent_burst_start_ms = None
                        self._barge_in_triggered = False
                        self._barge_in_candidate_start_ms = None
                        self._barge_in_frames = 0
                        self._barge_in_release_counter = 0
                    try:
                        result = on_event(data)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as cb_err:
                        logger.warning("Voice Live on_event callback error: %s", cb_err)
                    # Handle invalid_type for input_audio_format (retry with simple spec if we somehow sent object prior)
                    if etype == 'error':
                        err = data.get('error') or {}
                        code = err.get('code')
                        msg = (err.get('message') or '').lower()
                        # Retry format negotiation once
                        if code == 'invalid_type' and 'input_audio_format' in msg and not self._format_retry_sent:
                            try:
                                retry = {"type": "session.update", "session": {"input_audio_format": "pcm16", "output_audio_format": "pcm16"}}
                                await self._ws.send(json.dumps(retry))
                                self._format_retry_sent = True
                                logger.info("VOICE-LIVE RETRY session.update simple pcm16 formats sent")
                            except Exception as re_err:
                                logger.warning("VOICE-LIVE retry session.update failed: %s", re_err)
                        # Adaptive response to commit_empty: keep frames accumulated and raise threshold by 1 frame temporarily
                        if code == 'input_audio_buffer_commit_empty':
                            self._commit_empty_errors += 1
                            self._awaiting_commit_ack = False
                            # Log ack transition on error
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "VL-IN ack_transition error=commit_empty frames_during_ack=%d total_frames_during_ack=%d", 
                                    self._frames_during_ack, self._total_frames_during_ack
                                )
                            self._total_frames_during_ack += self._frames_during_ack
                            self._frames_during_ack = 0
                            # Adaptive increase: raise minimum by one frame worth of ms (or safety) and recompute threshold
                            increment = max(int(self._frame_ms_in), 20)
                            self._adaptive_min_ms += increment
                            if self._adaptive_min_ms > 300:  # cap growth
                                self._adaptive_min_ms = 300
                            self._recompute_threshold(force=True)
                            # Reset accumulation so next commit builds clean buffer
                            self._commit_ready = False
                            self._in_frames_since_commit = 0
                            self._in_ms_since_commit = 0.0
                            self._accum_started_monotonic = None
                            # Add a short cooldown (frames) before next commit attempt
                            self._commit_cooldown_frames = max(self._commit_cooldown_frames, 8)
                            logger.debug(
                                "VL-IN commit_empty observed count=%d frames=%d ms_since_commit=%.1f adaptive_min_ms_now=%d frame_ms_in=%.2f",
                                self._commit_empty_errors, self._in_frames_since_commit, self._in_ms_since_commit, self._adaptive_min_ms, self._frame_ms_in,
                            )
                            try:
                                app_state.media_commit_error(int(self._adaptive_min_ms))
                            except Exception:
                                pass
                        if code == 'conversation_already_has_active_response':
                            self._response_active = True
                    # After commit acknowledgement: optionally trigger a new response if no active output
                    if etype == 'input_audio_buffer.committed':
                        try:
                            app_state.update_last_event()
                        except Exception:
                            pass
                        self._awaiting_commit_ack = False
                        self._successful_commits += 1
                        # Update instrumentation counters
                        self._total_frames_during_ack += self._frames_during_ack
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "VL-IN ack_transition success commits=%d frames_during_ack=%d total_frames_during_ack=%d dyn_offset=%d dyn_thresh=%s", 
                                self._successful_commits, self._frames_during_ack, self._total_frames_during_ack, 
                                self._dynamic_rms_offset, self._current_dynamic_threshold
                            )
                        self._frames_during_ack = 0
                        self._frames_since_successful_commit = 0
                        self._last_successful_commit_monotonic = asyncio.get_event_loop().time() * 1000.0
                        self._speech_since_commit = False
                        self._no_speech_skip_logged = False
                        if os.getenv("VOICE_LIVE_AUTO_RESPONSE_ON_COMMIT", "true").lower() == "true":
                            if (not self._response_active) and (not self._current_burst_active):
                                instr = os.getenv("VOICE_LIVE_COMMIT_RESPONSE_INSTRUCTIONS", "")
                                if instr.strip():
                                    try:
                                        auto_payload = {"type": "response.create", "response": {"modalities": ["audio","text"], "instructions": instr}}
                                        await self._ws.send(json.dumps(auto_payload))
                                        logger.debug("VOICE-LIVE AUTO response.create after commit sent")
                                    except Exception as ar_err:
                                        logger.debug("VOICE-LIVE auto response.create send error: %s", ar_err)
                                # Flush any frames that were staged while we awaited this acknowledgement
                                if self._staged_frames:
                                    staged_to_flush = len(self._staged_frames)
                                    if logger.isEnabledFor(logging.DEBUG):
                                        logger.debug("VL-IN flushing staged frames count=%d after commit ack", staged_to_flush)
                                    # Copy then clear to avoid reentrancy issues if a flush triggers another commit
                                    frames_to_send = list(self._staged_frames)
                                    self._staged_frames.clear()
                                    for fr in frames_to_send:
                                        # Re-inject frames through normal path (now not awaiting ack)
                                        await self.send_input_audio_frame(fr)
                    if etype == 'input_audio_buffer.speech_started':
                        self._speech_active = True
                        self._speech_since_commit = True
                        self._no_speech_skip_logged = False
                    if etype == 'input_audio_buffer.speech_stopped':
                        self._speech_active = False
                        self._speech_since_commit = False
                        self._no_speech_skip_logged = False
                        # Keep buffered audio so the next commit can carry remaining speech or
                        # allow the no-speech timer to flush naturally. Only reset the ready flag
                        # so new speech reopeners can re-arm the latch without discarding audio.
                        if self._in_ms_since_commit > 0:
                            logger.debug(
                                "VL-IN speech stopped hold buffered audio frames=%d ms=%.1f",
                                self._in_frames_since_commit,
                                self._in_ms_since_commit,
                            )
                        self._commit_ready = False
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Voice Live receive loop error: %s", e)
        finally:
            await self.close()

    async def close(self) -> None:
        """Close the websocket gracefully and log the session identifier."""
        if self._closed:
            return
        self._closed = True
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        logger.info("VOICE-LIVE CLOSED session_id=%s", self.session_id)

    # --- Audio extraction helpers ---
    def _looks_base64(self, s: str) -> bool:
        if len(s) < 8:
            return False
        sample = s.strip().replace('\n','')
        if len(sample) % 4 != 0:
            return False
        allowed = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
        return all(c in allowed for c in sample[:48])

    def _extract_audio_bytes(self, evt: dict) -> bytes | None:
        """Pull the first base64 audio payload out of a Voice Live event."""
        candidates = []
        # Top-level simple fields
        for key in ['audio','data','chunk','bytes','pcm','delta']:
            v = evt.get(key)
            if isinstance(v, str) and self._looks_base64(v):
                candidates.append(v)
        # Nested patterns
        nests = [
            (evt.get('delta') or {}),
            (evt.get('item') or {}),
            (evt.get('output') or {}),
        ]
        for nest in nests:
            if isinstance(nest, dict):
                for key in ['audio','data','chunk','bytes','pcm','delta']:
                    v = nest.get(key)
                    if isinstance(v,str) and self._looks_base64(v):
                        candidates.append(v)
        import base64
        for enc in candidates:
            try:
                return base64.b64decode(enc)
            except Exception:
                continue
        return None

    async def get_next_pcm_chunk(self) -> bytes | None:
        try:
            return await asyncio.wait_for(self._downlink_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None

    # --- Outbound segmentation for Voice Live PCM (downlink) into fixed frames ---
    async def get_next_outbound_frame(self) -> bytes | None:
        # Return already segmented frames if any
        try:
            frame = await asyncio.wait_for(self._seg_queue.get(), timeout=1.0)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("VL-OUT delivering frame: bytes=%d remaining_queue=%d buffer_bytes=%d", 
                           len(frame), self._seg_queue.qsize(), len(self._seg_buffer))
            return frame
        except asyncio.TimeoutError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("VL-OUT frame timeout: remaining_queue=%d buffer_bytes=%d", 
                           self._seg_queue.qsize(), len(self._seg_buffer))
            return None

    async def _enqueue_pcm(self, pcm: bytes):
        """Push PCM into both the downlink queue and the outbound pacing buffer."""
        if not pcm:
            return
        if not self._current_burst_active:
            self._current_burst_active = True
            logger.debug("VL-OUT burst started")
        
        # Track queue overflow for downlink buffer
        downlink_dropped = False
        if self._downlink_queue.full():
            try:
                _ = self._downlink_queue.get_nowait()
                downlink_dropped = True
            except Exception:
                pass
        await self._downlink_queue.put(pcm)
        
        # Segmentation for outbound (ACS) pacing
        buffer_before = len(self._seg_buffer)
        self._seg_buffer.extend(pcm)
        frame_size = self._seg_frame_bytes
        frames_created = 0
        seg_dropped = False
        
        while len(self._seg_buffer) >= frame_size:
            frame = bytes(self._seg_buffer[:frame_size])
            del self._seg_buffer[:frame_size]
            if self._seg_queue.full():
                try:
                    _ = self._seg_queue.get_nowait()  # drop oldest (already late)
                    seg_dropped = True
                except Exception:
                    pass
            await self._seg_queue.put(frame)
            frames_created += 1
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("VL-OUT enqueued: pcm_bytes=%d buffer_before=%d buffer_after=%d frames_created=%d seg_queue_size=%d downlink_dropped=%s seg_dropped=%s",
                       len(pcm), buffer_before, len(self._seg_buffer), frames_created, self._seg_queue.qsize(), downlink_dropped, seg_dropped)
        if seg_dropped:
            try:
                app_state.media_out_frame_dropped()
            except Exception:
                pass
        # Track high-water mark
        try:
            app_state.media_out_backlog(self._seg_queue.qsize())
        except Exception:
            pass


async def run_receive(session: VoiceLiveSession, on_event: Callable[[dict], None | Awaitable[None]]):
    """Convenience wrapper for ``asyncio.create_task`` callers."""
    await session.receive_loop(on_event)
