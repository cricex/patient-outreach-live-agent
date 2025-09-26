"""Thread-safe in-memory state container backing the FastAPI diagnostics endpoints."""

import threading
import time
from typing import Optional, Dict, Any


class AppState:
    """Capture lifecycle information about ACS calls, Voice Live sessions, and media flow."""
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.started_at = time.time()
        self.last_call_id: Optional[str] = None
        self.last_voicelive_session_id: Optional[str] = None
        self.last_error: Optional[str] = None
        self.call_prompts: Dict[str, str] = {}
        self.current_call = None
        self.last_call = None
        self.last_event_at = None
        self.voicelive_session = None
        # Media streaming metrics (Task D)
        self.media = {
            "upstreamActive": False,
            "media_ws_connected_at": None,
            "inFrames": 0,
            "outFrames": 0,
            "outSendErrors": 0,
            "outJsonFrames": 0,
            "outBinaryFrames": 0,
            "vl_in_started_at": None,
            "textFrames": 0,
            "binaryFrames": 0,
            "first_in_ts": None,
            "first_out_ts": None,
            "last_in_ts": None,
            "last_out_ts": None,
            "schema": None,  # 'A' or 'B'
            "audio_bytes_in": 0,
            "audio_bytes_out": 0,
            "metadata_received": False,
            "postMetadataTextFrames": 0,
            # Detailed audio stats
            "audio_peak_max": 0,                 # max absolute sample observed overall
            "audio_rms_last": None,              # RMS of last processed 20ms frame
            "audio_rms_avg": None,               # rolling average RMS (window ~2s)
            "audio_frames_non_silent": 0,        # frames where peak > threshold (128)
            "audio_frames_zero": 0,              # frames entirely zero
            "audio_frames_total": 0,             # total 20ms frames analyzed for energy
            "audio_first_frame_samples": None,   # first 16 samples (list of ints)
            # Resampling / drift
            "resampler_active": False,
            "frames_resampled": 0,
            "bytes_resampled": 0,
            "pacer_drift_events": 0,
            # Voice Live input commit metrics
            "commit_errors_total": 0,
            "last_commit_frames": None,
            "last_commit_ms": None,
            "adaptive_min_ms_current": None,
            "last_commit_trigger": None,
            "commit_attempts": 0,
            "commit_ms_buffered_last": None,
            "commit_ms_buffered_current": 0,
            # Outbound (model -> phone) loss / pacing metrics
            "out_dropped_frames": 0,          # frames dropped due to seg queue overflow
            "out_seg_queue_high_water": 0,    # max observed queued frames
            "out_backlog_max": 0,             # max backlog drained in a single pacer cycle
            # Commit detail / speech capture diagnostics
            "last_commit_audio_bytes": 0,     # total raw (possibly resampled) bytes sent in last commit
            "last_commit_speech_frames": 0,   # frames classified as speech in last commit
            "last_commit_rms_avg": None,      # average RMS across frames in last commit
            "last_commit_rms_peak": 0,        # max RMS observed in last commit
            "dynamic_rms_threshold": None,    # current adaptive RMS threshold
            "noise_floor_rms": None,          # rolling noise floor estimate
            "commit_blocks_no_speech": 0,     # count of times a commit was blocked for insufficient speech
            "commit_skipped_low_speech": 0,   # count of skipped commit attempts due to low speech frame count
        }
        # Internal rolling RMS window (store integers)
        self._rms_window = []  # up to 100 frames (~2s at 50 fps)

    def snapshot(self) -> Dict[str, Any]:
        """Create a shallow snapshot for JSON serialization via ``/status``."""
        with self._lock:
            return {
                "uptime_sec": round(time.time() - self.started_at, 3),
                "last": {
                    "call_id": self.last_call_id,
                    "voicelive_session_id": self.last_voicelive_session_id,
                },
                "last_error": self.last_error,
                "call": {
                    "active": self.current_call is not None,
                    "current": self._augment_with_duration(self.current_call),
                    "last": self._augment_with_duration(self.last_call),
                    "last_event_age_sec": (round(time.time() - self.last_event_at, 3) if self.last_event_at else None),
                },
                "voicelive": self._voicelive_snapshot(),
                "media": dict(self.media),
            }

    def set_call_id(self, call_id: str) -> None:
        with self._lock:
            self.last_call_id = call_id

    def set_voicelive_session_id(self, session_id: str) -> None:
        with self._lock:
            self.last_voicelive_session_id = session_id

    def set_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message

    def set_call_prompt(self, call_id: str, prompt: str) -> None:
        with self._lock:
            self.call_prompts[call_id] = prompt

    def get_call_prompt(self, call_id: str) -> Optional[str]:
        with self._lock:
            return self.call_prompts.get(call_id)

    def begin_call(self, call_id: str, prompt: str) -> None:
        """Record the currently active call and remember its prompt."""
        with self._lock:
            now = time.time()
            self.current_call = {
                "call_id": call_id,
                "prompt": prompt,
                "started_at": now,
            }
            self.last_call_id = call_id
            self.call_prompts[call_id] = prompt
            self.last_event_at = now

    def end_call(self, call_id: str, reason: Optional[str] = None) -> None:
        """Mark the tracked call as completed and capture its duration."""
        with self._lock:
            if self.current_call and self.current_call.get("call_id") == call_id:
                self.current_call["ended_at"] = time.time()
                if reason:
                    self.current_call["end_reason"] = reason
                self.last_call = self.current_call
                self.current_call = None
                self.last_event_at = time.time()

    def update_last_event(self) -> None:
        with self._lock:
            self.last_event_at = time.time()

    # Voice Live session tracking
    def begin_voicelive(self, session_id: str, model: str, voice: str):
        """Persist metadata for a new Voice Live session when the bridge comes online."""
        with self._lock:
            now = time.time()
            self.voicelive_session = {
                "session_id": session_id,
                "model": model,
                "voice": voice,
                "started_at": now,
                "active": True,
                "event_types": [],  # first N captured
                "output_hz": None,
                "input_hz": None,
            }
            self.last_voicelive_session_id = session_id

    def voicelive_add_event_type(self, event_type: str, limit: int = 10):
        """Append distinct Voice Live event labels up to ``limit`` for quick debugging."""
        with self._lock:
            if self.voicelive_session and self.voicelive_session.get("active"):
                types = self.voicelive_session.get("event_types", [])
                if len(types) < limit:
                    types.append(event_type)
                self.voicelive_session["event_types"] = types

    def end_voicelive(self, reason: str = None):
        """Close out the Voice Live session so the status endpoint reflects teardown."""
        with self._lock:
            if self.voicelive_session and self.voicelive_session.get("active"):
                self.voicelive_session["ended_at"] = time.time()
                if reason:
                    self.voicelive_session["end_reason"] = reason
                self.voicelive_session["active"] = False

    def _voicelive_snapshot(self):
        """Return a sanitized subset of Voice Live fields safe for public diagnostics."""
        if not self.voicelive_session:
            return {"active": False}
        snap = dict(self.voicelive_session)
        started = snap.get("started_at")
        ended = snap.get("ended_at")
        if started:
            if ended:
                snap["duration_sec"] = round(ended - started, 3)
            else:
                snap["duration_sec"] = round(time.time() - started, 3)
        # Do not expose internal lists beyond first events
        return {
            "active": snap.get("active", False),
            "session_id": snap.get("session_id"),
            "model": snap.get("model"),
            "voice": snap.get("voice"),
            "output_hz": snap.get("output_hz"),
            "input_hz": snap.get("input_hz"),
            "started_at": snap.get("started_at"),
            "duration_sec": snap.get("duration_sec"),
            "event_types": snap.get("event_types", []),
            "end_reason": snap.get("end_reason"),
        }

    def _augment_with_duration(self, call: Optional[Dict[str, Any]]):
        if not call:
            return None
        started = call.get("started_at")
        ended = call.get("ended_at")
        if started:
            if ended:
                call["duration_sec"] = round(ended - started, 3)
            else:
                call["duration_sec"] = round(time.time() - started, 3)
        return call

    # Media metrics update helpers (Task D)
    def media_ws_open(self):
        """Flag that the ACS media websocket is ready for inbound audio frames."""
        with self._lock:
            self.media["upstreamActive"] = True
            self.media["media_ws_connected_at"] = time.time()

    def media_set_schema(self, schema: str):
        with self._lock:
            if not self.media.get("schema"):
                self.media["schema"] = schema

    def media_in_frame(self):
        with self._lock:
            now = time.time()
            self.media["inFrames"] += 1
            if not self.media["first_in_ts"]:
                self.media["first_in_ts"] = now
            self.media["last_in_ts"] = now
    # New: add multiple inbound audio frames (e.g. decoded from base64 payload)
    def media_add_in_frames(self, n: int):
        if n <= 0:
            return
        with self._lock:
            now = time.time()
            self.media["inFrames"] += n
            if not self.media["first_in_ts"]:
                self.media["first_in_ts"] = now
            self.media["last_in_ts"] = now

    def media_out_frame(self):
        with self._lock:
            now = time.time()
            self.media["outFrames"] += 1
            if not self.media["first_out_ts"]:
                self.media["first_out_ts"] = now
            self.media["last_out_ts"] = now

    def media_add_in_bytes(self, n: int):
        """Accumulate inbound audio payload size for quick bandwidth estimates."""
        with self._lock:
            self.media["audio_bytes_in"] += n

    def media_text_frame(self, post_metadata: bool = False):
        with self._lock:
            self.media["textFrames"] += 1
            if post_metadata:
                self.media["postMetadataTextFrames"] += 1

    def media_binary_frame(self):
        with self._lock:
            self.media["binaryFrames"] += 1

    def media_add_out_bytes(self, n: int):
        with self._lock:
            self.media["audio_bytes_out"] += n

    def media_out_error(self):
        """Increment transport error counters for outbound model audio."""
        with self._lock:
            self.media["outSendErrors"] += 1

    def media_out_json_frame(self):
        with self._lock:
            self.media["outJsonFrames"] += 1

    def media_out_binary_frame(self):
        with self._lock:
            self.media["outBinaryFrames"] += 1

    def media_resample_add(self, in_bytes: int, out_bytes: int, out_frames: int):
        with self._lock:
            self.media["resampler_active"] = True
            self.media["frames_resampled"] += out_frames
            self.media["bytes_resampled"] += out_bytes

    def media_out_frame_dropped(self, dropped: int = 1):
        if dropped <= 0:
            return
        with self._lock:
            self.media["out_dropped_frames"] += dropped

    def media_out_backlog(self, queued: int, drained_this_cycle: int | None = None):
        """Track pacing backlog so we can spot stuck Voice Live out queues."""
        with self._lock:
            if queued > self.media["out_seg_queue_high_water"]:
                self.media["out_seg_queue_high_water"] = queued
            if drained_this_cycle and drained_this_cycle > self.media["out_backlog_max"]:
                self.media["out_backlog_max"] = drained_this_cycle

    def media_pacer_drift(self):
        with self._lock:
            self.media["pacer_drift_events"] += 1

    # Commit metrics helpers
    def media_commit_success(self, frames: int, ms: int, adaptive_min_ms: int, trigger: str | None = None):
        """Store stats for a successful Voice Live input commit."""
        with self._lock:
            self.media["last_commit_frames"] = frames
            self.media["last_commit_ms"] = ms
            self.media["adaptive_min_ms_current"] = adaptive_min_ms
            if trigger:
                self.media["last_commit_trigger"] = trigger
            self.media["commit_attempts"] += 1
            self.media["commit_ms_buffered_last"] = ms
            self.media["commit_ms_buffered_current"] = 0

    def media_commit_detail(self, audio_bytes: int, speech_frames: int, rms_avg: int | None, rms_peak: int, dyn_thresh: int | None, noise_floor: int | None):
        """Capture deeper metrics about the most recent commit for troubleshooting."""
        with self._lock:
            self.media["last_commit_audio_bytes"] = audio_bytes
            self.media["last_commit_speech_frames"] = speech_frames
            self.media["last_commit_rms_avg"] = rms_avg
            if rms_peak > self.media.get("last_commit_rms_peak", 0):
                self.media["last_commit_rms_peak"] = rms_peak
            if dyn_thresh is not None:
                self.media["dynamic_rms_threshold"] = dyn_thresh
            if noise_floor is not None:
                self.media["noise_floor_rms"] = noise_floor

    def media_commit_block(self, reason: str):
        """Tally skipped commits so adaptive thresholds can surface in the UI."""
        with self._lock:
            if reason == "no_speech":
                self.media["commit_blocks_no_speech"] += 1
            elif reason == "low_speech":
                self.media["commit_skipped_low_speech"] += 1

    def media_commit_error(self, adaptive_min_ms: int | None = None):
        """Count errors returned by Voice Live and persist the last adaptive threshold."""
        with self._lock:
            self.media["commit_errors_total"] += 1
            if adaptive_min_ms is not None:
                self.media["adaptive_min_ms_current"] = adaptive_min_ms
            self.media["commit_attempts"] += 1

    def media_commit_progress(self, ms_current: int):
        """Help the UI show how much audio is currently buffered before commit."""
        with self._lock:
            self.media["commit_ms_buffered_current"] = ms_current

    def voicelive_set_formats(self, out_rate: int | None, in_rate: int | None):
        with self._lock:
            if not self.voicelive_session:
                return
            if out_rate:
                self.voicelive_session["output_hz"] = out_rate
            if in_rate:
                self.voicelive_session["input_hz"] = in_rate

    def media_set_metadata(self):
        """Note that audio metadata has arrived so downstream logs can change verbosity."""
        with self._lock:
            self.media["metadata_received"] = True

    def media_ws_close(self):
        """Reset websocket flags when ACS disconnects."""
        with self._lock:
            self.media["upstreamActive"] = False

    def media_process_audio_frame(self, pcm_frame: bytes, silence_threshold: int = 128) -> bool:
        """Process a single 20ms (640-byte) PCM16 frame for stats. Returns True if speech detected."""
        if len(pcm_frame) != 640:
            return False
        import struct
        try:
            samples = struct.unpack('<320h', pcm_frame)
        except Exception:
            return False
        # Peak & RMS
        peak = 0
        sq_sum = 0
        all_zero = True
        for s in samples:
            if s != 0:
                all_zero = False
            a = s if s >= 0 else -s
            if a > peak:
                peak = a
            sq_sum += s * s
        rms = int((sq_sum / len(samples)) ** 0.5)
        is_speech = peak > silence_threshold
        with self._lock:
            m = self.media
            m["audio_frames_total"] += 1
            if all_zero:
                m["audio_frames_zero"] += 1
            if is_speech:
                m["audio_frames_non_silent"] += 1
            if peak > m["audio_peak_max"]:
                m["audio_peak_max"] = peak
            m["audio_rms_last"] = rms
            # rolling window up to 100 frames (~2s)
            self._rms_window.append(rms)
            if len(self._rms_window) > 100:
                self._rms_window.pop(0)
            if self._rms_window:
                m["audio_rms_avg"] = int(sum(self._rms_window) / len(self._rms_window))
        # Capture first 16 samples if not yet stored
        with self._lock:
            if self.media["audio_first_frame_samples"] is None:
                self.media["audio_first_frame_samples"] = list(samples[:16])
        return is_speech

    def media_mark_vl_in_started(self):
        with self._lock:
            if not self.media.get("vl_in_started_at"):
                self.media["vl_in_started_at"] = time.time()

    def media_snapshot(self):
        """Expose a copy of media metrics for the status endpoint without locks."""
        with self._lock:
            return dict(self.media)


app_state = AppState()
