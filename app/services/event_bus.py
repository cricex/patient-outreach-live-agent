"""Async event bus for real-time diagnostic streaming.

Services (SpeechService, CallSession, MediaBridge) publish typed events.
WebSocket handlers subscribe and fan out to connected UI clients.

Uses asyncio.Queue per subscriber — no threading, no external deps.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("app.events")


class EventType(str, Enum):
    """Categories of diagnostic events."""

    # Call lifecycle
    CALL_STARTED = "call.started"
    CALL_ENDED = "call.ended"

    # Voice Live session
    VL_SESSION_STARTED = "vl.session.started"
    VL_SESSION_ENDED = "vl.session.ended"
    VL_SESSION_READY = "vl.session.ready"
    VL_ERROR = "vl.error"

    # Audio metrics
    AUDIO_INBOUND = "audio.inbound"
    AUDIO_OUTBOUND = "audio.outbound"
    AUDIO_RMS = "audio.rms"

    # Conversation
    TRANSCRIPT_USER = "transcript.user"
    TRANSCRIPT_AGENT = "transcript.agent"
    BARGE_IN = "audio.barge_in"

    # Media bridge
    MEDIA_CONNECTED = "media.connected"
    MEDIA_DISCONNECTED = "media.disconnected"

    # Function calling (Phase 6)
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"


@dataclass
class DiagnosticEvent:
    """A single diagnostic event for UI consumption."""

    type: EventType
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON encoding."""
        return {
            "type": self.type.value,
            "timestamp": self.timestamp,
            "data": self.data,
        }


class EventBus:
    """Async pub/sub event bus.

    Thread-safe by design: runs on a single asyncio event loop.
    Each subscriber gets its own asyncio.Queue so slow consumers
    don't block publishers or other subscribers.
    """

    def __init__(self, max_queue_size: int = 200) -> None:
        self._subscribers: dict[int, asyncio.Queue[DiagnosticEvent]] = {}
        self._next_id: int = 0
        self._max_queue_size = max_queue_size
        # Keep recent events for new subscribers joining mid-call
        self._recent: list[DiagnosticEvent] = []
        self._recent_max = 50

    def subscribe(self) -> tuple[int, asyncio.Queue[DiagnosticEvent]]:
        """Register a new subscriber.

        Returns:
            A (subscriber_id, queue) tuple. The caller reads from the
            queue and must call ``unsubscribe`` when done.
        """
        sub_id = self._next_id
        self._next_id += 1
        queue: asyncio.Queue[DiagnosticEvent] = asyncio.Queue(
            maxsize=self._max_queue_size,
        )
        self._subscribers[sub_id] = queue
        logger.debug(
            "Subscriber %d registered (total=%d)", sub_id, len(self._subscribers),
        )
        return sub_id, queue

    def unsubscribe(self, sub_id: int) -> None:
        """Remove a subscriber by id."""
        self._subscribers.pop(sub_id, None)
        logger.debug(
            "Subscriber %d removed (total=%d)", sub_id, len(self._subscribers),
        )

    async def publish(self, event: DiagnosticEvent) -> None:
        """Publish an event to all subscribers.

        Slow consumers that have a full queue get their oldest event
        dropped so the bus never blocks the publisher.
        """
        self._recent.append(event)
        if len(self._recent) > self._recent_max:
            # Trim from the front — keep the newest events
            self._recent = self._recent[-self._recent_max :]

        dead: list[int] = []
        for sub_id, queue in self._subscribers.items():
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest event for this slow subscriber
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:
                    dead.append(sub_id)

        for sub_id in dead:
            self._subscribers.pop(sub_id, None)

    def emit(self, event_type: EventType, **data: Any) -> None:
        """Fire-and-forget helper for sync call-sites inside the loop.

        Creates an ``asyncio.Task`` internally. In pure-async code prefer
        ``await publish()`` directly so back-pressure is visible.
        """
        event = DiagnosticEvent(type=event_type, data=data)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            # No event loop running — skip (happens during import/tests)
            pass

    def get_recent(self) -> list[dict[str, Any]]:
        """Return recent events for new subscribers joining mid-call."""
        return [e.to_dict() for e in self._recent]

    def clear(self) -> None:
        """Clear recent event buffer (call this on call end)."""
        self._recent.clear()


# Module-level singleton
event_bus = EventBus()
