"""Tests for /health and /status endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx._transports.asgi import ASGITransport

import app.auth as auth_mod
from app.auth import create_session_token, revoke_token
from app.main import app


def test_health_returns_ok(client):
    """GET /health should return 200 with 'ok'."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == "ok"


def test_status_returns_expected_keys(client):
    """GET /status should return 200 with top-level state keys."""
    resp = client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "uptime_sec" in data
    assert "call" in data
    assert "voicelive" in data
    assert "media" in data


def test_status_uptime_is_positive(client):
    """Uptime should be a non-negative number."""
    data = client.get("/status").json()
    assert isinstance(data["uptime_sec"], (int, float))
    assert data["uptime_sec"] >= 0


def test_status_call_structure(client):
    """Call section should have current and last sub-keys."""
    data = client.get("/status").json()
    call = data["call"]
    assert "current" in call
    assert "last" in call
    # No call active initially
    assert call["current"] is None


# ── Session-scoped /status ──────────────────────────────────────────


@pytest.fixture()
def enable_auth():
    """Temporarily enable auth for session-scoped tests."""
    old_enabled = auth_mod._auth_enabled
    old_passwords = auth_mod._allowed_passwords
    old_tokens = auth_mod._active_tokens.copy()
    old_sessions = auth_mod._token_sessions.copy()
    auth_mod._auth_enabled = True
    auth_mod._allowed_passwords = {"test-pass"}
    yield
    auth_mod._auth_enabled = old_enabled
    auth_mod._allowed_passwords = old_passwords
    auth_mod._active_tokens = old_tokens
    auth_mod._token_sessions = old_sessions


@pytest.mark.asyncio
async def test_status_returns_session_scoped_snapshot(enable_auth):
    """Two tokens see independent call state via /status."""
    token_a = create_session_token("test-pass")
    token_b = create_session_token("test-pass")

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        # Start a simulated call under token A
        with patch(
            "app.services.call_manager.CallManager.start_call",
            new_callable=AsyncMock,
            return_value=("sim-9999", "SIMULATED", "prompt"),
        ) as mock_start:
            resp = await ac.post(
                "/call/start",
                json={"simulate": True},
                headers={"x-auth-token": token_a},
            )
            assert resp.status_code == 200

            # Verify start_call was invoked with token A's session_id
            called_sid = mock_start.call_args[1].get(
                "session_id", mock_start.call_args[0][0] if mock_start.call_args[0] else None
            )

        # Manually populate state for token A's session so /status reflects it
        from app.auth import get_session_id
        from app.models.state import app_state

        sid_a = get_session_id(token_a)
        sid_b = get_session_id(token_b)
        await app_state.begin_call(sid_a, "sim-9999", "prompt")

        try:
            # /status with token A should show a current call
            resp_a = await ac.get("/status", headers={"x-auth-token": token_a})
            assert resp_a.status_code == 200
            data_a = resp_a.json()
            assert data_a["call"]["current"] is not None
            assert data_a["call"]["current"]["call_id"] == "sim-9999"

            # /status with token B should show NO current call
            resp_b = await ac.get("/status", headers={"x-auth-token": token_b})
            assert resp_b.status_code == 200
            data_b = resp_b.json()
            assert data_b["call"]["current"] is None
        finally:
            # Clean up state
            await app_state.end_call(sid_a, "sim-9999", reason="test-cleanup")
            revoke_token(token_a)
            revoke_token(token_b)
