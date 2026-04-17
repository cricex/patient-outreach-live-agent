"""Integration tests for multi-session concurrent calls via the API.

Verifies that each auth token maps to a unique session_id and that
concurrent simulated calls have fully isolated state.
"""
from __future__ import annotations

import pytest
import httpx
from httpx._transports.asgi import ASGITransport

import app.auth as auth_mod
from app.main import app
from app.services.call_manager import call_manager


BASE = "http://testserver"


def _enable_auth():
    """Enable auth with a test password, returning prior state for restore."""
    old_enabled = auth_mod._auth_enabled
    old_passwords = auth_mod._allowed_passwords
    auth_mod._auth_enabled = True
    auth_mod._allowed_passwords = {"test-pass"}
    return old_enabled, old_passwords


def _restore_auth(old_enabled, old_passwords):
    auth_mod._auth_enabled = old_enabled
    auth_mod._allowed_passwords = old_passwords


async def _get_token(ac: httpx.AsyncClient) -> str:
    """POST /auth/validate and return the session token."""
    resp = await ac.post(f"{BASE}/auth/validate", json={"password": "test-pass"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    return data["token"]


@pytest.mark.asyncio
async def test_two_sessions_start_concurrent_simulated_calls():
    """Two tokens start independent simulated calls with isolated /status."""
    old_enabled, old_passwords = _enable_auth()
    session_ids: list[str] = []
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app)) as ac:
            # Create two tokens
            token_a = await _get_token(ac)
            token_b = await _get_token(ac)
            assert token_a != token_b

            # Resolve session_ids for cleanup later
            sid_a = auth_mod.get_session_id(token_a)
            sid_b = auth_mod.get_session_id(token_b)
            session_ids.extend([sid_a, sid_b])

            # Start simulated calls
            resp_a = await ac.post(
                f"{BASE}/call/start",
                json={"simulate": True},
                headers={"X-Auth-Token": token_a},
            )
            assert resp_a.status_code == 200
            call_id_a = resp_a.json()["call_id"]

            resp_b = await ac.post(
                f"{BASE}/call/start",
                json={"simulate": True},
                headers={"X-Auth-Token": token_b},
            )
            assert resp_b.status_code == 200
            call_id_b = resp_b.json()["call_id"]

            # Call IDs must be different
            assert call_id_a != call_id_b

            # /status scoped per token
            status_a = (
                await ac.get(f"{BASE}/status", headers={"X-Auth-Token": token_a})
            ).json()
            status_b = (
                await ac.get(f"{BASE}/status", headers={"X-Auth-Token": token_b})
            ).json()

            assert status_a["call"]["current"]["call_id"] == call_id_a
            assert status_b["call"]["current"]["call_id"] == call_id_b

            # Hangup both
            await ac.post(f"{BASE}/call/hangup", headers={"X-Auth-Token": token_a})
            await ac.post(f"{BASE}/call/hangup", headers={"X-Auth-Token": token_b})
    finally:
        # Clean up any leftover sessions
        for sid in session_ids:
            if call_manager.get_session(sid):
                await call_manager.end_call(sid, reason="TestCleanup")
        _restore_auth(old_enabled, old_passwords)


@pytest.mark.asyncio
async def test_session_hangup_does_not_affect_other_session():
    """Hanging up session A leaves session B's call active."""
    old_enabled, old_passwords = _enable_auth()
    session_ids: list[str] = []
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app)) as ac:
            token_a = await _get_token(ac)
            token_b = await _get_token(ac)

            sid_a = auth_mod.get_session_id(token_a)
            sid_b = auth_mod.get_session_id(token_b)
            session_ids.extend([sid_a, sid_b])

            # Start both calls
            await ac.post(
                f"{BASE}/call/start",
                json={"simulate": True},
                headers={"X-Auth-Token": token_a},
            )
            await ac.post(
                f"{BASE}/call/start",
                json={"simulate": True},
                headers={"X-Auth-Token": token_b},
            )

            # Hangup A only
            await ac.post(f"{BASE}/call/hangup", headers={"X-Auth-Token": token_a})

            # B's call should still be active
            status_b = (
                await ac.get(f"{BASE}/status", headers={"X-Auth-Token": token_b})
            ).json()
            assert status_b["call"]["current"] is not None

            # A should have no call
            status_a = (
                await ac.get(f"{BASE}/status", headers={"X-Auth-Token": token_a})
            ).json()
            assert status_a["call"]["current"] is None

            # Cleanup B
            await ac.post(f"{BASE}/call/hangup", headers={"X-Auth-Token": token_b})
    finally:
        for sid in session_ids:
            if call_manager.get_session(sid):
                await call_manager.end_call(sid, reason="TestCleanup")
        _restore_auth(old_enabled, old_passwords)


@pytest.mark.asyncio
async def test_unauthenticated_call_uses_default_session():
    """With auth disabled, calls work without any auth header."""
    # Auth is already disabled by conftest (DEMO_PASSWORDS popped)
    assert not auth_mod._auth_enabled

    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app)) as ac:
            resp = await ac.post(f"{BASE}/call/start", json={"simulate": True})
            assert resp.status_code == 200
            data = resp.json()
            assert "call_id" in data
            call_id = data["call_id"]
            assert call_id.startswith("sim-")

            # /status should show the call
            status = (await ac.get(f"{BASE}/status")).json()
            assert status["call"]["current"] is not None
            assert status["call"]["current"]["call_id"] == call_id

            # Cleanup
            await ac.post(f"{BASE}/call/hangup")
    finally:
        # Clean up default session if still active
        if call_manager.get_session(auth_mod.DEFAULT_SESSION_ID):
            await call_manager.end_call(
                auth_mod.DEFAULT_SESSION_ID, reason="TestCleanup"
            )
