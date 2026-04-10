"""Diagnostic and health check routes."""
from __future__ import annotations

import logging
import socket
import ssl
import time
from urllib.parse import urlparse

from fastapi import APIRouter

from ..config import settings
from ..models.state import app_state

logger = logging.getLogger("app.main")
router = APIRouter(tags=["diagnostics"])


@router.get("/health")
async def health():
    """Simple liveness probe."""
    return "ok"


@router.get("/status")
async def status():
    """Runtime snapshot: call state, Voice Live session, media metrics."""
    return app_state.snapshot()


@router.get("/acs/health")
async def acs_health():
    """ACS endpoint TLS diagnostics."""
    host = _parse_acs_host()
    if not host:
        return {"ok": False, "error": "Could not parse ACS endpoint host"}
    return await _tls_probe(host)


def _parse_acs_host() -> str | None:
    """Extract the hostname from the ACS connection string."""
    for part in settings.acs_connection_string.split(";"):
        if part.lower().startswith("endpoint="):
            ep = part.split("=", 1)[1].strip()
            if not ep.startswith("http"):
                ep = "https://" + ep
            return urlparse(ep).hostname
    return None


async def _tls_probe(host: str, timeout: float = 5.0) -> dict:
    """Perform a TLS handshake probe against an Azure endpoint."""
    result: dict = {"host": host}
    try:
        t0 = time.time()
        addr_info = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        result["dns_records"] = [ai[4][0] for ai in addr_info[:5]]
        sock = socket.create_connection((host, 443), timeout=timeout)
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            result["cipher"] = ssock.cipher()
            result["tls_version"] = ssock.version()
            cert = ssock.getpeercert()
            result["cert_notAfter"] = cert.get("notAfter")
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        result["ok"] = True
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
    return result
