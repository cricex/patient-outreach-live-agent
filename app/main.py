"""FastAPI application entrypoint.

Creates the app, mounts routers, and configures startup logging.
All business logic lives in services/ and routes live in routers/.
"""
from __future__ import annotations

import logging
import ssl
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .logging_config import configure_logging
from .routers import api, calls, diagnostics, media, ws

configure_logging()
logger = logging.getLogger("app.main")

app = FastAPI(title="Patient Outreach Voice Agent", version="2.0.0")

# Mount routers
app.include_router(calls.router)
app.include_router(diagnostics.router)
app.include_router(media.router)
app.include_router(api.router)
app.include_router(ws.router)


# Serve React frontend static files (production build)
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="static-assets")

    @app.get("/")
    async def serve_frontend() -> FileResponse:
        return FileResponse(str(_frontend_dist / "index.html"))

    # Catch-all for client-side routing (must be last)
    @app.get("/{path:path}")
    async def serve_frontend_fallback(path: str) -> FileResponse:
        file_path = _frontend_dist / path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_frontend_dist / "index.html"))


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
