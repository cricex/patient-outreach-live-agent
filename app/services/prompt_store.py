"""JSON file-based prompt set storage.

Stores named prompt configurations (system prompt + call brief + voice/model)
as individual JSON files in data/prompts/ for reuse across demo sessions.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("app.prompts")

PROMPTS_DIR = Path("data/prompts")


class PromptSet(BaseModel):
    """A saved prompt configuration for demo calls."""

    id: str
    name: str
    description: str = ""
    system_prompt: str = ""
    call_brief: str = ""
    voice: str | None = None
    model: str | None = None
    target_phone_number: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _slugify(name: str) -> str:
    """Convert a display name to a filesystem-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or f"prompt-{int(time.time())}"


def _ensure_dir() -> None:
    """Create the prompts directory if it doesn't exist."""
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)


def list_prompts() -> list[PromptSet]:
    """Return all saved prompt sets, sorted by updated_at descending."""
    _ensure_dir()
    results: list[PromptSet] = []
    for path in PROMPTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append(PromptSet(**data))
        except Exception as exc:
            logger.warning("Skipping invalid prompt file %s: %s", path.name, exc)
    results.sort(key=lambda p: p.updated_at, reverse=True)
    return results


def get_prompt(prompt_id: str) -> PromptSet | None:
    """Load a single prompt set by ID.

    Args:
        prompt_id: Slug identifier matching the JSON filename.

    Returns:
        The parsed PromptSet, or None if not found or corrupt.
    """
    path = PROMPTS_DIR / f"{prompt_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PromptSet(**data)
    except Exception as exc:
        logger.warning("Failed to load prompt %s: %s", prompt_id, exc)
        return None


def save_prompt(prompt: PromptSet) -> PromptSet:
    """Save a prompt set to disk.

    Generates an ID from the name if the id field is empty.
    On updates, preserves the original created_at timestamp.

    Args:
        prompt: The prompt set to persist.

    Returns:
        The saved PromptSet (with id and timestamps populated).
    """
    _ensure_dir()
    if not prompt.id:
        prompt.id = _slugify(prompt.name)
    prompt.updated_at = datetime.now(timezone.utc).isoformat()

    path = PROMPTS_DIR / f"{prompt.id}.json"
    # Preserve original creation timestamp on updates
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            prompt.created_at = existing.get("created_at", prompt.created_at)
        except Exception:
            pass

    path.write_text(
        json.dumps(prompt.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved prompt set id=%s name=%s", prompt.id, prompt.name)
    return prompt


def delete_prompt(prompt_id: str) -> bool:
    """Delete a prompt set by ID.

    Args:
        prompt_id: Slug identifier matching the JSON filename.

    Returns:
        True if the file was deleted, False if it did not exist.
    """
    path = PROMPTS_DIR / f"{prompt_id}.json"
    if not path.exists():
        return False
    path.unlink()
    logger.info("Deleted prompt set id=%s", prompt_id)
    return True
