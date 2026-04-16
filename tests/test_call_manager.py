"""Unit tests for CallManager multi-session lifecycle."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.auth import DEFAULT_SESSION_ID
from app.services.call_manager import CallManager


@pytest.fixture
def cm():
    """Fresh CallManager for each test (avoids singleton leakage)."""
    return CallManager()


# ── 1. Simulated call creates session ─────────────────────────────────


@pytest.mark.asyncio
async def test_start_simulated_call_creates_session(cm):
    """start_call(simulate=True) should populate _sessions and return sim- call_id."""
    with patch.object(
        cm.__class__,
        "start_call",
        wraps=cm.start_call,
    ):
        # Patch CallSession.start so Voice Live isn't actually contacted
        with patch(
            "app.services.call_manager.CallSession.start", new_callable=AsyncMock
        ):
            call_id, dest, prompt = await cm.start_call(
                "test-session", simulate=True
            )

    assert "test-session" in cm._sessions
    assert call_id.startswith("sim-")

    # Cleanup
    cm._sessions.pop("test-session", None)


# ── 2. get_speech returns None for wrong / absent sessions ───────────


@pytest.mark.asyncio
async def test_get_speech_returns_none_for_wrong_session(cm):
    """get_speech for an unknown session_id should return None."""
    with patch(
        "app.services.call_manager.CallSession.start", new_callable=AsyncMock
    ):
        await cm.start_call("s1", simulate=True)

    # Different session → None
    assert cm.get_speech("s2") is None

    # s1 exists but SpeechService isn't connected so active=False → also None
    assert cm.get_speech("s1") is None

    # Cleanup
    cm._sessions.pop("s1", None)


# ── 3. Media token routing ───────────────────────────────────────────


def test_media_token_routing(cm):
    """get_session_id_for_media_token resolves known tokens and defaults unknown."""
    cm._media_tokens["m-12345"] = "session-A"

    assert cm.get_session_id_for_media_token("m-12345") == "session-A"
    assert cm.get_session_id_for_media_token("m-99999") == DEFAULT_SESSION_ID


def test_get_speech_for_media_token_unknown(cm):
    """get_speech_for_media_token returns None for unknown tokens."""
    assert cm.get_speech_for_media_token("no-such-token") is None


# ── 4. end_call cleans up all mappings ───────────────────────────────


@pytest.mark.asyncio
async def test_end_call_cleans_up_all_mappings(cm):
    """After end_call, sessions, call-to-session, and media tokens are purged."""
    with patch(
        "app.services.call_manager.CallSession.start", new_callable=AsyncMock
    ):
        call_id, _, _ = await cm.start_call("s1", simulate=True)

    # Manually register a media token for this session
    cm._media_tokens["m-test"] = "s1"

    # Verify pre-conditions
    assert "s1" in cm._sessions
    assert call_id in cm._call_to_session
    assert "m-test" in cm._media_tokens

    # end_call tries ACS hangup — patch _acs_client to avoid real SDK calls
    with patch.object(cm, "_acs_client"):
        await cm.end_call("s1", call_id=call_id, reason="Timeout")

    assert "s1" not in cm._sessions
    assert call_id not in cm._call_to_session
    assert "m-test" not in cm._media_tokens


# ── 5. Concurrent sessions stay independent ──────────────────────────


@pytest.mark.asyncio
async def test_concurrent_sessions_independent(cm):
    """Two simulated sessions coexist; ending one leaves the other intact."""
    with patch(
        "app.services.call_manager.CallSession.start", new_callable=AsyncMock
    ):
        cid1, _, _ = await cm.start_call("s1", simulate=True)
        cid2, _, _ = await cm.start_call("s2", simulate=True)

    assert "s1" in cm._sessions
    assert "s2" in cm._sessions
    assert cid1.startswith("sim-")
    assert cid2.startswith("sim-")

    with patch.object(cm, "_acs_client"):
        await cm.end_call("s1", call_id=cid1, reason="Timeout")

    assert "s1" not in cm._sessions
    assert "s2" in cm._sessions

    # Cleanup remaining session
    cm._sessions.pop("s2", None)
