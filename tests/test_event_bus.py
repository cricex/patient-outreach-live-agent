"""Tests for the EventBus async pub/sub system."""
from __future__ import annotations

import asyncio

import pytest

from app.services.event_bus import DiagnosticEvent, EventBus, EventType


@pytest.mark.asyncio
async def test_subscribe_and_receive():
    """A subscriber should receive published events."""
    bus = EventBus()
    sub_id, queue = bus.subscribe()

    event = DiagnosticEvent(type=EventType.CALL_STARTED, data={"call_id": "test-1"})
    await bus.publish(event)

    received = queue.get_nowait()
    assert received.type == EventType.CALL_STARTED
    assert received.data["call_id"] == "test-1"

    bus.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_recent_buffer_stores_events():
    """Published events should appear in the recent buffer."""
    bus = EventBus()

    await bus.publish(DiagnosticEvent(type=EventType.CALL_STARTED, data={"n": 1}))
    await bus.publish(DiagnosticEvent(type=EventType.CALL_ENDED, data={"n": 2}))

    recent = bus.get_recent()
    assert len(recent) == 2
    assert recent[0]["type"] == "call.started"
    assert recent[1]["type"] == "call.ended"


@pytest.mark.asyncio
async def test_clear_empties_buffer():
    """clear() should empty the recent event buffer."""
    bus = EventBus()

    await bus.publish(DiagnosticEvent(type=EventType.CALL_STARTED))
    assert len(bus.get_recent()) == 1

    bus.clear()
    assert len(bus.get_recent()) == 0


@pytest.mark.asyncio
async def test_slow_subscriber_does_not_block():
    """A subscriber with a full queue should not block publishing."""
    bus = EventBus(max_queue_size=2)
    sub_id, queue = bus.subscribe()

    # Publish more events than the queue can hold
    for i in range(5):
        await bus.publish(DiagnosticEvent(type=EventType.AUDIO_INBOUND, data={"i": i}))

    # Queue should have exactly max_queue_size items (oldest dropped)
    assert queue.qsize() == 2

    bus.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    """After unsubscribe, no new events should be delivered."""
    bus = EventBus()
    sub_id, queue = bus.subscribe()
    bus.unsubscribe(sub_id)

    await bus.publish(DiagnosticEvent(type=EventType.CALL_STARTED))
    assert queue.empty()


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """Multiple subscribers should each receive a copy of the event."""
    bus = EventBus()
    id1, q1 = bus.subscribe()
    id2, q2 = bus.subscribe()

    await bus.publish(DiagnosticEvent(type=EventType.TRANSCRIPT_USER, data={"text": "hi"}))

    assert not q1.empty()
    assert not q2.empty()
    assert q1.get_nowait().data["text"] == "hi"
    assert q2.get_nowait().data["text"] == "hi"

    bus.unsubscribe(id1)
    bus.unsubscribe(id2)


@pytest.mark.asyncio
async def test_recent_buffer_caps_at_max():
    """Recent buffer should not exceed its max size."""
    bus = EventBus()
    bus._recent_max = 5

    for i in range(10):
        await bus.publish(DiagnosticEvent(type=EventType.AUDIO_INBOUND, data={"i": i}))

    recent = bus.get_recent()
    assert len(recent) == 5
    # Should keep the newest events
    assert recent[0]["data"]["i"] == 5
    assert recent[-1]["data"]["i"] == 9
