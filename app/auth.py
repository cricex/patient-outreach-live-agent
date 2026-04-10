"""Simple shared-password authentication gate.

Loads allowed passwords from Azure Key Vault (preferred) or DEMO_PASSWORDS env var (fallback).
Generates opaque session tokens so raw passwords never travel in headers or WS URLs.
"""
from __future__ import annotations

import logging
import os
import secrets

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("app.auth")

# Paths that never require authentication
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/auth/validate", "/auth/status"}
# Prefixes that never require authentication
PUBLIC_PREFIXES = ("/assets/", "/call/events")

_allowed_passwords: set[str] = set()
_auth_enabled: bool = False
_active_tokens: set[str] = set()


def _is_public(path: str) -> bool:
    """Return True if *path* should bypass auth."""
    if path in PUBLIC_PATHS:
        return True
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return True
    # Root and static files needed by the SPA frontend
    if path == "/" or path.endswith(
        (".js", ".css", ".svg", ".png", ".ico", ".html", ".json", ".woff", ".woff2")
    ):
        return True
    return False


def load_passwords() -> None:
    """Load allowed passwords from Key Vault or env var.

    Auth is **disabled** when neither AZURE_KEYVAULT_NAME nor DEMO_PASSWORDS
    is present (backward-compat for local dev with no config).
    """
    global _allowed_passwords, _auth_enabled

    kv_name = os.getenv("AZURE_KEYVAULT_NAME")

    # Try Key Vault first
    if kv_name:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            credential = DefaultAzureCredential()
            client = SecretClient(
                vault_url=f"https://{kv_name}.vault.azure.net",
                credential=credential,
            )
            secret = client.get_secret("demo-passwords")
            if secret.value:
                passwords = [p.strip() for p in secret.value.split(",") if p.strip()]
                _allowed_passwords = set(passwords)
            _auth_enabled = True
            logger.info(
                "Loaded %d passwords from Key Vault '%s'",
                len(_allowed_passwords),
                kv_name,
            )
            return
        except Exception as exc:
            logger.warning(
                "Key Vault password load failed (falling back to env): %s", exc
            )

    # Env var: presence with non-empty value means auth is enabled
    env_val = os.getenv("DEMO_PASSWORDS")
    if env_val is not None and env_val.strip():
        _auth_enabled = True
        passwords = [p.strip() for p in env_val.split(",") if p.strip()]
        _allowed_passwords = set(passwords)
        logger.info("Loaded %d passwords from env", len(_allowed_passwords))
    else:
        _auth_enabled = False
        logger.info(
            "No auth configured (set DEMO_PASSWORDS or AZURE_KEYVAULT_NAME to enable)"
        )


def is_valid_password(password: str) -> bool:
    """Check if a password is in the allowed set (used by /auth/validate only)."""
    if not _auth_enabled:
        return True
    return password in _allowed_passwords


def create_session_token(password: str) -> str | None:
    """Validate *password* and return an opaque session token, or None."""
    if not is_valid_password(password):
        return None
    token = secrets.token_urlsafe(32)
    _active_tokens.add(token)
    return token


def is_valid_token(token: str) -> bool:
    """Check an opaque session token issued by create_session_token."""
    if not _auth_enabled:
        return True
    return token in _active_tokens


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that checks X-Auth-Token header on HTTP requests.

    WebSocket connections are NOT covered by BaseHTTPMiddleware — each WS
    handler must check auth independently before calling accept().
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if _is_public(request.url.path):
            return await call_next(request)

        if not _auth_enabled:
            return await call_next(request)

        token = request.headers.get("x-auth-token", "")
        if not is_valid_token(token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing authentication"},
            )

        return await call_next(request)
