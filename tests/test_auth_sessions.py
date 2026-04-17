"""Tests for auth session lifecycle: token→session_id mapping."""
from __future__ import annotations

import pytest

import app.auth as auth_mod
from app.auth import (
    create_session_token,
    get_session_id,
    revoke_token,
    is_valid_token,
    DEFAULT_SESSION_ID,
)


@pytest.fixture()
def enable_auth():
    """Temporarily enable auth with a known password for testing."""
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


# ── Test 1: revoke_token removes session mapping ────────────────────


def test_revoke_token_removes_session(enable_auth):
    """Revoking a token invalidates it and drops the session mapping."""
    token = create_session_token("test-pass")
    assert token is not None
    assert is_valid_token(token) is True

    sid = get_session_id(token)
    assert sid.startswith("s-")

    revoke_token(token)

    assert is_valid_token(token) is False
    assert get_session_id(token) == DEFAULT_SESSION_ID


# ── Test 2: auth disabled returns default session ───────────────────


def test_auth_disabled_returns_default_session():
    """When auth is disabled, any token maps to DEFAULT_SESSION_ID."""
    assert get_session_id("any-random-string") == DEFAULT_SESSION_ID
    assert get_session_id("") == DEFAULT_SESSION_ID


# ── Test 3: multiple tokens same password → different sessions ──────


def test_multiple_tokens_same_password_different_sessions(enable_auth):
    """Five tokens from the same password each get a unique session_id."""
    tokens = [create_session_token("test-pass") for _ in range(5)]
    assert all(t is not None for t in tokens)
    assert all(is_valid_token(t) for t in tokens)

    session_ids = [get_session_id(t) for t in tokens]
    assert len(set(session_ids)) == 5, "All session_ids must be unique"


# ── Test 4: session mapping is stable across calls ──────────────────


def test_token_session_mapping_persists(enable_auth):
    """get_session_id returns the same value on repeated calls."""
    token = create_session_token("test-pass")
    sid_first = get_session_id(token)
    sid_second = get_session_id(token)
    assert sid_first == sid_second
