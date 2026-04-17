"""Tests for session isolation — two tokens see independent state."""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from app.auth import create_session_token, get_session_id, DEFAULT_SESSION_ID
from app.models.state import AppState
from app.services.event_bus import EventBus, EventType


# ── Auth token → session_id mapping ──────────────────────────────────


def test_different_tokens_get_different_session_ids():
    """Two logins with the same password produce unique session_ids."""
    import app.auth as auth_mod
    # Temporarily enable auth to test session_id generation
    old_enabled = auth_mod._auth_enabled
    old_passwords = auth_mod._allowed_passwords
    auth_mod._auth_enabled = True
    auth_mod._allowed_passwords = {"test-pass"}
    try:
        token_a = create_session_token("test-pass")
        token_b = create_session_token("test-pass")
        assert token_a != token_b
        sid_a = get_session_id(token_a)
        sid_b = get_session_id(token_b)
        assert sid_a != sid_b
        assert sid_a.startswith("s-")
        assert sid_b.startswith("s-")
    finally:
        auth_mod._auth_enabled = old_enabled
        auth_mod._allowed_passwords = old_passwords


def test_get_session_id_unknown_token_returns_default():
    """An unknown token maps to DEFAULT_SESSION_ID."""
    assert get_session_id("bogus-token") == DEFAULT_SESSION_ID


# ── Per-session AppState ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_appstate_sessions_are_isolated():
    """Calls started under different session_ids don't leak."""
    state = AppState()
    await state.begin_call("session-A", "call-1", "prompt A")
    await state.begin_call("session-B", "call-2", "prompt B")

    # Each session sees only its own call
    assert state.get_call("session-A").call_id == "call-1"
    assert state.get_call("session-B").call_id == "call-2"
    assert state.get_call("session-C") is None

    # Snapshots are scoped
    snap_a = state.snapshot("session-A")
    snap_b = state.snapshot("session-B")
    assert snap_a["call"]["current"]["call_id"] == "call-1"
    assert snap_b["call"]["current"]["call_id"] == "call-2"


@pytest.mark.asyncio
async def test_appstate_end_call_only_affects_own_session():
    """Ending session-A's call doesn't touch session-B."""
    state = AppState()
    await state.begin_call("session-A", "call-1", "p")
    await state.begin_call("session-B", "call-2", "p")

    await state.end_call("session-A", "call-1", reason="done")

    assert state.get_call("session-A") is None
    assert state.get_call("session-B").call_id == "call-2"


@pytest.mark.asyncio
async def test_appstate_media_per_session():
    """Each session has independent media metrics."""
    state = AppState()
    media_a = state.get_media("session-A")
    media_b = state.get_media("session-B")
    media_a.record_inbound(10, 6400)
    assert media_a.in_frames == 10
    assert media_b.in_frames == 0


# ── Session-scoped EventBus ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_eventbus_subscriber_only_sees_own_session():
    """A subscriber filtering by session_id misses other sessions' events."""
    bus = EventBus()
    _, queue_a = bus.subscribe(session_id="session-A")
    _, queue_b = bus.subscribe(session_id="session-B")
    _, queue_all = bus.subscribe()  # no filter — sees everything

    await bus.publish(
        __import__("app.services.event_bus", fromlist=["DiagnosticEvent"]).DiagnosticEvent(
            type=EventType.CALL_STARTED, session_id="session-A", data={"x": 1}
        )
    )
    await bus.publish(
        __import__("app.services.event_bus", fromlist=["DiagnosticEvent"]).DiagnosticEvent(
            type=EventType.CALL_STARTED, session_id="session-B", data={"x": 2}
        )
    )

    assert queue_a.qsize() == 1
    assert queue_b.qsize() == 1
    assert queue_all.qsize() == 2

    event_a = queue_a.get_nowait()
    assert event_a.data["x"] == 1
    event_b = queue_b.get_nowait()
    assert event_b.data["x"] == 2


@pytest.mark.asyncio
async def test_eventbus_get_recent_filters_by_session():
    """get_recent(session_id) returns only matching events."""
    bus = EventBus()
    from app.services.event_bus import DiagnosticEvent
    await bus.publish(DiagnosticEvent(type=EventType.CALL_STARTED, session_id="s1"))
    await bus.publish(DiagnosticEvent(type=EventType.CALL_ENDED, session_id="s2"))
    await bus.publish(DiagnosticEvent(type=EventType.VL_SESSION_READY, session_id="s1"))

    recent_s1 = bus.get_recent("s1")
    recent_s2 = bus.get_recent("s2")
    recent_all = bus.get_recent()

    assert len(recent_s1) == 2
    assert len(recent_s2) == 1
    assert len(recent_all) == 3


@pytest.mark.asyncio
async def test_eventbus_clear_by_session():
    """clear(session_id) only removes that session's events."""
    bus = EventBus()
    from app.services.event_bus import DiagnosticEvent
    await bus.publish(DiagnosticEvent(type=EventType.CALL_STARTED, session_id="s1"))
    await bus.publish(DiagnosticEvent(type=EventType.CALL_STARTED, session_id="s2"))

    bus.clear("s1")
    assert len(bus.get_recent()) == 1
    assert bus.get_recent()[0]["session_id"] == "s2"
