"""FastAPI application entrypoint.

Creates the app, mounts routers, and configures startup logging.
All business logic lives in services/ and routes live in routers/.
"""
from __future__ import annotations

import logging
import ssl

from fastapi import FastAPI

from .config import settings
from .logging_config import configure_logging
from .routers import calls, diagnostics, media

configure_logging()
logger = logging.getLogger("app.main")

app = FastAPI(title="Patient Outreach Voice Agent", version="2.0.0")

# Mount routers
app.include_router(calls.router)
app.include_router(diagnostics.router)
app.include_router(media.router)


@app.on_event("startup")
async def _startup() -> None:
    """Log configuration and SDK versions on startup."""
    versions = _get_sdk_versions()
    logger.info(
        "startup model=%s voice=%s endpoint=%s az-core=%s callauto=%s voicelive=%s openssl=%s",
        settings.voicelive_model,
        settings.voicelive_voice,
        settings.voicelive_endpoint,
        versions.get("azure-core", "?"),
        versions.get("azure-communication-callautomation", "?"),
        versions.get("azure-ai-voicelive", "?"),
        ssl.OPENSSL_VERSION,
    )


def _get_sdk_versions() -> dict[str, str]:
    """Collect installed Azure SDK versions for diagnostics."""
    try:
        from importlib import metadata
    except ImportError:
        import importlib_metadata as metadata  # type: ignore

    packages = ["azure-core", "azure-communication-callautomation", "azure-ai-voicelive"]
    versions = {}
    for pkg in packages:
        try:
            versions[pkg] = metadata.version(pkg)
        except Exception:
            versions[pkg] = "missing"
    return versions
