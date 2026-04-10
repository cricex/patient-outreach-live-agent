"""Tests for POST /call/start with simulate=true."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch


def test_simulate_call_returns_200(client):
    """POST /call/start with simulate=true should return 200."""
    with patch(
        "app.services.call_manager.CallManager.start_call",
        new_callable=AsyncMock,
        return_value=("sim-123456", "SIMULATED", "You are a helpful voice agent."),
    ):
        resp = client.post("/call/start", json={"simulate": True})
    assert resp.status_code == 200


def test_simulate_call_has_sim_prefix(client):
    """Simulated call_id should start with 'sim-'."""
    with patch(
        "app.services.call_manager.CallManager.start_call",
        new_callable=AsyncMock,
        return_value=("sim-999", "SIMULATED", "Test prompt"),
    ):
        resp = client.post("/call/start", json={"simulate": True})
    data = resp.json()
    assert data["call_id"].startswith("sim-")


def test_simulate_call_contains_prompt_used(client):
    """Response should include prompt_used field."""
    with patch(
        "app.services.call_manager.CallManager.start_call",
        new_callable=AsyncMock,
        return_value=("sim-42", "SIMULATED", "My system prompt"),
    ):
        resp = client.post("/call/start", json={"simulate": True})
    data = resp.json()
    assert "prompt_used" in data
    assert data["prompt_used"] == "My system prompt"


def test_simulate_call_destination_is_simulated(client):
    """Response 'to' field should be SIMULATED."""
    with patch(
        "app.services.call_manager.CallManager.start_call",
        new_callable=AsyncMock,
        return_value=("sim-77", "SIMULATED", "prompt"),
    ):
        resp = client.post("/call/start", json={"simulate": True})
    data = resp.json()
    assert data["to"] == "SIMULATED"
