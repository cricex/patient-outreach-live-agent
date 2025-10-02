"""Central logging configuration for the /app service.

Behavior:
 - Purges existing files in ``logs/`` so only current-run logs remain.
 - Creates ``logs/app.log`` with rotation at ~200KB keeping several backups.
 - Honors ``LOG_LEVEL`` (default INFO). When DEBUG, enables azure.* debug visibility.
 - Idempotent: subsequent calls won't duplicate handlers.
"""
from __future__ import annotations

import logging
import os
import pathlib
from logging.handlers import RotatingFileHandler


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()

    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return

    log_dir = pathlib.Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    try:
        for path in log_dir.glob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover
        print(f"WARN: failed purging logs dir: {exc}")

    file_handler = RotatingFileHandler(log_dir / "app.log", maxBytes=204800, backupCount=10, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname).1s %(name)s %(message)s")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    for noisy in ["urllib3", "aiohttp.access"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if level == logging.DEBUG:
        logging.getLogger("azure").setLevel(logging.DEBUG)

    root.debug("Logging configured level=%s file=%s", level_name, log_dir / "app.log")
