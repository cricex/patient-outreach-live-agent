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
    """Global application state — singleton, async-safe, per-session scoped.

    State is keyed by session_id so each authenticated token sees only its
    own call.  Backward-compatible properties delegate to DEFAULT_SESSION_ID
    for tests and code that hasn't been migrated yet.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.started_at: float = time.time()
        self._calls: dict[str, CallState] = {}
        self._last_calls: dict[str, CallState] = {}
        self._last_events: dict[str, float] = {}
        self._voicelive: dict[str, VoiceLiveState] = {}
        self._media: dict[str, MediaMetrics] = {}

    # ------------------------------------------------------------------
    # Per-session accessors
    # ------------------------------------------------------------------

    def get_media(self, session_id: str) -> MediaMetrics:
        """Get or create MediaMetrics for a session."""
        if session_id not in self._media:
            self._media[session_id] = MediaMetrics()
        return self._media[session_id]

    def get_call(self, session_id: str) -> CallState | None:
        """Get current call for a session."""
        return self._calls.get(session_id)

    def get_last_event(self, session_id: str) -> float | None:
        return self._last_events.get(session_id)

    def update_last_event(self, session_id: str | None = None) -> None:
        """Non-async — single assignment is atomic in CPython."""
        if session_id is None:
            from ..auth import DEFAULT_SESSION_ID
            session_id = DEFAULT_SESSION_ID
        self._last_events[session_id] = time.time()

    # ------------------------------------------------------------------
    # Call lifecycle
    # ------------------------------------------------------------------

    async def begin_call(self, session_id: str, call_id: str | None = None, prompt: str | None = None) -> None:
        # Support old signature: begin_call(call_id, prompt)
        if call_id is not None and prompt is not None:
            pass  # new-style call
        else:
            # Old-style: begin_call(call_id, prompt) — session_id is actually call_id
            from ..auth import DEFAULT_SESSION_ID
            prompt = call_id  # type: ignore[assignment]
            call_id = session_id
            session_id = DEFAULT_SESSION_ID
        async with self._lock:
            self._calls[session_id] = CallState(call_id=call_id, prompt=prompt)  # type: ignore[arg-type]
            self._last_events[session_id] = time.time()
            self._media[session_id] = MediaMetrics()

    async def end_call(self, session_id: str, call_id: str | None = None, reason: str | None = None) -> None:
        # Support old signature: end_call(call_id, reason=...)
        if call_id is None:
            from ..auth import DEFAULT_SESSION_ID
            call_id = session_id
            reason = reason  # noqa: PLW0127
            session_id = DEFAULT_SESSION_ID
        async with self._lock:
            call = self._calls.get(session_id)
            if call and call.call_id == call_id:
                call.ended_at = time.time()
                call.end_reason = reason
                self._last_calls[session_id] = call
                del self._calls[session_id]

    # ------------------------------------------------------------------
    # Voice Live lifecycle
    # ------------------------------------------------------------------

    async def begin_voicelive(self, session_id: str, vl_session_id: str | None = None, voice: str | None = None, model: str | None = None) -> None:
        # Support old signature: begin_voicelive(vl_session_id, voice, model)
        if vl_session_id is not None and voice is not None:
            pass  # new-style call
        else:
            from ..auth import DEFAULT_SESSION_ID
            # Old-style: session_id is actually vl_session_id, vl_session_id is voice, voice is model
            model = voice
            voice = vl_session_id  # type: ignore[assignment]
            vl_session_id = session_id
            session_id = DEFAULT_SESSION_ID
        self._voicelive[session_id] = VoiceLiveState(session_id=vl_session_id, voice=voice, model=model)  # type: ignore[arg-type]

    async def end_voicelive(self, session_id: str | None = None, reason: str | None = None) -> None:
        if session_id is None:
            from ..auth import DEFAULT_SESSION_ID
            session_id = DEFAULT_SESSION_ID
        vl = self._voicelive.get(session_id)
        if vl and vl.active:
            vl.ended_at = time.time()
            vl.end_reason = reason
            vl.active = False

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self, session_id: str | None = None) -> dict[str, Any]:
        """Return a serializable snapshot for a specific session."""
        if session_id is None:
            from ..auth import DEFAULT_SESSION_ID
            session_id = DEFAULT_SESSION_ID
        call = self._calls.get(session_id)
        last = self._last_calls.get(session_id)
        vl = self._voicelive.get(session_id)
        media = self._media.get(session_id, MediaMetrics())
        return {
            "uptime_sec": round(time.time() - self.started_at, 3),
            "call": {
                "current": call.to_dict() if call else None,
                "last": last.to_dict() if last else None,
            },
            "voicelive": vl.to_dict() if vl else {"active": False},
            "media": media.to_dict(),
        }

    # ------------------------------------------------------------------
    # Backward-compat properties for code not yet session-aware
    # ------------------------------------------------------------------

    @property
    def current_call(self) -> CallState | None:
        """Default session call — used by tests and un-migrated code."""
        from ..auth import DEFAULT_SESSION_ID
        return self._calls.get(DEFAULT_SESSION_ID)

    @property
    def last_call(self) -> CallState | None:
        from ..auth import DEFAULT_SESSION_ID
        return self._last_calls.get(DEFAULT_SESSION_ID)

    @property
    def last_event_at(self) -> float | None:
        from ..auth import DEFAULT_SESSION_ID
        return self._last_events.get(DEFAULT_SESSION_ID)

    @property
    def voicelive(self) -> VoiceLiveState | None:
        from ..auth import DEFAULT_SESSION_ID
        return self._voicelive.get(DEFAULT_SESSION_ID)

    @property
    def media(self) -> MediaMetrics:
        from ..auth import DEFAULT_SESSION_ID
        return self.get_media(DEFAULT_SESSION_ID)


app_state = AppState()
