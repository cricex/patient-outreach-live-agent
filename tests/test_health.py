"""Tests for /health and /status endpoints."""
from __future__ import annotations


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
