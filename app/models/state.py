"""Runtime state and metrics for the v2 voice call service.

Uses asyncio.Lock instead of threading.RLock — the app runs on a single
event loop so thread-safety primitives are unnecessary overhead.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallState:
    """Per-call state snapshot. Created by CallSession, not shared across calls."""
    call_id: str
    prompt: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    end_reason: str | None = None

    @property
    def duration_sec(self) -> float:
        end = self.ended_at or time.time()
        return round(end - self.started_at, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "prompt": self.prompt[:100] + "..." if len(self.prompt) > 100 else self.prompt,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "end_reason": self.end_reason,
            "duration_sec": self.duration_sec,
        }


@dataclass
class VoiceLiveState:
    """Voice Live session metadata."""
    session_id: str
    voice: str
    model: str | None = None
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    end_reason: str | None = None
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = {
            "session_id": self.session_id,
            "voice": self.voice,
            "model": self.model,
            "started_at": self.started_at,
            "active": self.active,
        }
        if self.ended_at:
            d["ended_at"] = self.ended_at
            d["end_reason"] = self.end_reason
            d["duration_sec"] = round(self.ended_at - self.started_at, 3)
        elif self.active:
            d["duration_sec"] = round(time.time() - self.started_at, 3)
        return d


@dataclass
class MediaMetrics:
    """Counters for the media bridge."""
    ws_connected_at: float | None = None
    started: bool = False
    in_frames: int = 0
    out_frames: int = 0
    out_frames_dropped: int = 0
    audio_bytes_in: int = 0
    audio_bytes_out: int = 0
    first_in_ts: float | None = None
    last_in_ts: float | None = None
    first_out_ts: float | None = None
    last_out_ts: float | None = None

    def record_inbound(self, frames: int, byte_count: int) -> None:
        now = time.time()
        if frames > 0:
            if not self.first_in_ts:
                self.first_in_ts = now
            self.last_in_ts = now
            self.in_frames += frames
        if byte_count > 0:
            self.audio_bytes_in += byte_count

    def record_outbound(self, frames: int, byte_count: int) -> None:
        now = time.time()
        if frames > 0:
            if not self.first_out_ts:
                self.first_out_ts = now
            self.last_out_ts = now
            self.out_frames += frames
        if byte_count > 0:
            self.audio_bytes_out += byte_count

    def record_dropped(self, frames: int) -> None:
        self.out_frames_dropped += frames

    def reset(self) -> None:
        """Reset all counters for a new call."""
        self.__init__()  # type: ignore[misc]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ws_connected_at": self.ws_connected_at,
            "started": self.started,
            "inFrames": self.in_frames,
            "outFrames": self.out_frames,
            "outFramesDropped": self.out_frames_dropped,
            "audio_bytes_in": self.audio_bytes_in,
            "audio_bytes_out": self.audio_bytes_out,
            "first_in_ts": self.first_in_ts,
            "last_in_ts": self.last_in_ts,
            "first_out_ts": self.first_out_ts,
            "last_out_ts": self.last_out_ts,
        }


class AppState:
    """Global application state — singleton, async-safe.

    Replaces v1's RLock-based state with plain attribute access.
    Since FastAPI runs on a single event loop, concurrent coroutines
    don't preempt each other mid-statement, so simple attribute
    assignment is safe. An asyncio.Lock is used only around multi-step
    mutations that yield (await) between reads and writes.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.started_at: float = time.time()
        self.current_call: CallState | None = None
        self.last_call: CallState | None = None
        self.last_event_at: float | None = None
        self.voicelive: VoiceLiveState | None = None
        self.media: MediaMetrics = MediaMetrics()

    async def begin_call(self, call_id: str, prompt: str) -> None:
        async with self._lock:
            self.current_call = CallState(call_id=call_id, prompt=prompt)
            self.last_event_at = time.time()
            self.media.reset()

    async def end_call(self, call_id: str, reason: str | None = None) -> None:
        async with self._lock:
            if self.current_call and self.current_call.call_id == call_id:
                self.current_call.ended_at = time.time()
                self.current_call.end_reason = reason
                self.last_call = self.current_call
                self.current_call = None

    def update_last_event(self) -> None:
        """Non-async — single assignment is atomic in CPython."""
        self.last_event_at = time.time()

    async def begin_voicelive(self, session_id: str, voice: str, model: str | None) -> None:
        self.voicelive = VoiceLiveState(session_id=session_id, voice=voice, model=model)

    async def end_voicelive(self, reason: str | None = None) -> None:
        if self.voicelive and self.voicelive.active:
            self.voicelive.ended_at = time.time()
            self.voicelive.end_reason = reason
            self.voicelive.active = False

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable snapshot for the /status endpoint."""
        return {
            "uptime_sec": round(time.time() - self.started_at, 3),
            "call": {
                "current": self.current_call.to_dict() if self.current_call else None,
                "last": self.last_call.to_dict() if self.last_call else None,
            },
            "voicelive": self.voicelive.to_dict() if self.voicelive else {"active": False},
            "media": self.media.to_dict(),
        }


app_state = AppState()
