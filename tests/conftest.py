"""Shared fixtures for pytest."""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

# Set required env vars BEFORE importing the app (config.py reads them at import)
os.environ.setdefault("APP_BASE_URL", "http://localhost:8000")
os.environ.setdefault("ACS_CONNECTION_STRING", "endpoint=https://test.communication.azure.com/;accesskey=dGVzdA==")
os.environ.setdefault("ACS_OUTBOUND_CALLER_ID", "+10000000000")
os.environ.setdefault("AZURE_VOICELIVE_ENDPOINT", "https://test.cognitiveservices.azure.com/")
os.environ.setdefault("VOICELIVE_MODEL", "gpt-realtime")
os.environ.setdefault("VOICELIVE_VOICE", "alloy")
os.environ.setdefault("AZURE_VOICELIVE_API_KEY", "test-key")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def tmp_prompts_dir(monkeypatch):
    """Temporary prompts directory for isolated CRUD tests."""
    tmpdir = tempfile.mkdtemp()
    from pathlib import Path
    monkeypatch.setattr("app.services.prompt_store.PROMPTS_DIR", Path(tmpdir))
    yield Path(tmpdir)
    shutil.rmtree(tmpdir, ignore_errors=True)
