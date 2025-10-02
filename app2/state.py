"""Minimal runtime state & metrics for /app2."""
from __future__ import annotations
import time, threading
from typing import Optional, Dict, Any

class AppState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.started_at = time.time()
        self.current_call: dict | None = None
        self.last_call: dict | None = None
        self.last_event_at: float | None = None
        self.voicelive: dict | None = None
        self.media: dict = {
            "ws_connected_at": None,
            "inFrames": 0,
            "outFrames": 0,
            "audio_bytes_in": 0,
            "audio_bytes_out": 0,
            "first_in_ts": None,
            "last_in_ts": None,
            "first_out_ts": None,
            "last_out_ts": None,
        }

    # ---- Call ----
    def begin_call(self, call_id: str, prompt: str):
        with self._lock:
            now = time.time()
            self.current_call = {"call_id": call_id, "prompt": prompt, "started_at": now}
            self.last_event_at = now

    def end_call(self, call_id: str, reason: str | None = None):
        with self._lock:
            if self.current_call and self.current_call.get("call_id") == call_id:
                self.current_call["ended_at"] = time.time()
                if reason:
                    self.current_call["end_reason"] = reason
                self.last_call = self.current_call
                self.current_call = None

    def update_last_event(self):
        with self._lock:
            self.last_event_at = time.time()

    # ---- Voice Live ----
    def begin_voicelive(self, session_id: str, voice: str):
        with self._lock:
            self.voicelive = {
                "session_id": session_id,
                "voice": voice,
                "started_at": time.time(),
                "active": True,
            }

    def end_voicelive(self, reason: str | None = None):
        with self._lock:
            if self.voicelive and self.voicelive.get("active"):
                self.voicelive["ended_at"] = time.time()
                if reason: self.voicelive["end_reason"] = reason
                self.voicelive["active"] = False

    # ---- Media metrics ----
    def media_ws_open(self):
        with self._lock:
            if not self.media["ws_connected_at"]:
                self.media["ws_connected_at"] = time.time()

    def media_in_audio(self, frames: int, bytes_len: int):
        if frames <= 0 and bytes_len <= 0:
            return
        with self._lock:
            now = time.time()
            if frames > 0:
                if not self.media["first_in_ts"]: self.media["first_in_ts"] = now
                self.media["last_in_ts"] = now
                self.media["inFrames"] += frames
            if bytes_len > 0:
                self.media["audio_bytes_in"] += bytes_len

    def media_out_audio(self, frames: int, bytes_len: int):
        if frames <= 0 and bytes_len <= 0:
            return
        with self._lock:
            now = time.time()
            if frames > 0:
                if not self.media["first_out_ts"]: self.media["first_out_ts"] = now
                self.media["last_out_ts"] = now
                self.media["outFrames"] += frames
            if bytes_len > 0:
                self.media["audio_bytes_out"] += bytes_len

    # ---- Snapshot ----
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            def _dur(item: dict | None):
                if not item: return None
                st = item.get("started_at")
                en = item.get("ended_at")
                if st:
                    item["duration_sec"] = round((en or time.time()) - st, 3)
                return item
            return {
                "uptime_sec": round(time.time() - self.started_at, 3),
                "call": {"current": _dur(dict(self.current_call) if self.current_call else None), "last": _dur(dict(self.last_call) if self.last_call else None)},
                "voicelive": dict(self.voicelive) if self.voicelive else {"active": False},
                "media": dict(self.media),
            }

app_state = AppState()
