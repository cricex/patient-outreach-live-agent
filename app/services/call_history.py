"""Call history persistence — saves transcripts and metadata per call.

Each call is stored as a JSON file in data/calls/{call_id}.json containing
call metadata, configuration, and a chronological transcript.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("app.history")

CALLS_DIR = Path("data/calls")


class TranscriptTurn(BaseModel):
    """A single turn in the conversation transcript."""

    role: str  # "user" or "agent"
    text: str
    timestamp: float = Field(default_factory=time.time)


class CallRecord(BaseModel):
    """Complete record of a single call."""

    call_id: str
    scenario_name: str = ""
    system_prompt_preview: str = ""  # First 200 chars
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ended_at: str | None = None
    end_reason: str | None = None
    duration_sec: float | None = None
    destination: str = ""
    voice: str | None = None
    model: str | None = None
    simulated: bool = False
    recording_id: str | None = None  # ACS recording ID if recording was enabled
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    events_count: int = 0  # Total diagnostic events during the call


class CallHistoryService:
    """Manages call history persistence.

    Designed to be used as a singleton. Tracks the active call's transcript
    in memory, then flushes to disk when the call ends.
    """

    def __init__(self) -> None:
        self._active_record: CallRecord | None = None
        _ensure_dir()

    def begin_call(
        self,
        call_id: str,
        destination: str = "",
        system_prompt: str = "",
        scenario_name: str = "",
        voice: str | None = None,
        model: str | None = None,
        simulated: bool = False,
    ) -> None:
        """Start tracking a new call."""
        # Flush any prior call that wasn't properly ended
        if self._active_record:
            self.end_call("Superseded")

        self._active_record = CallRecord(
            call_id=call_id,
            scenario_name=scenario_name,
            system_prompt_preview=system_prompt[:200] if system_prompt else "",
            destination=destination,
            voice=voice,
            model=model,
            simulated=simulated,
        )
        logger.info("Tracking call history call_id=%s", call_id)

    def add_transcript_turn(self, role: str, text: str) -> None:
        """Add a transcript turn (user or agent) to the active call."""
        if not self._active_record or not text.strip():
            return
        self._active_record.transcript.append(
            TranscriptTurn(role=role, text=text.strip())
        )

    def set_recording_id(self, recording_id: str) -> None:
        """Store the ACS recording ID for the active call."""
        if self._active_record:
            self._active_record.recording_id = recording_id

    def increment_events(self) -> None:
        """Increment the event counter for the active call."""
        if self._active_record:
            self._active_record.events_count += 1

    def end_call(self, reason: str | None = None) -> CallRecord | None:
        """End the active call and save to disk.

        Returns:
            The saved CallRecord, or None if no active call.
        """
        if not self._active_record:
            return None

        record = self._active_record
        record.ended_at = datetime.now(timezone.utc).isoformat()
        record.end_reason = reason

        # Calculate duration
        try:
            start = datetime.fromisoformat(record.started_at)
            end = datetime.fromisoformat(record.ended_at)
            record.duration_sec = round((end - start).total_seconds(), 1)
        except Exception:
            pass

        # Save to disk
        _save_record(record)
        self._active_record = None
        logger.info(
            "Call history saved call_id=%s turns=%d duration=%.1fs",
            record.call_id,
            len(record.transcript),
            record.duration_sec or 0,
        )
        return record

    @property
    def active_record(self) -> CallRecord | None:
        return self._active_record


# ---- File I/O ----


def _ensure_dir() -> None:
    CALLS_DIR.mkdir(parents=True, exist_ok=True)


def _save_record(record: CallRecord) -> None:
    _ensure_dir()
    path = CALLS_DIR / f"{record.call_id}.json"
    path.write_text(
        json.dumps(record.model_dump(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def list_calls() -> list[dict]:
    """List all saved call records (metadata only, no full transcripts)."""
    _ensure_dir()
    results = []
    for path in CALLS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Return summary without full transcript for listing
            results.append(
                {
                    "call_id": data.get("call_id"),
                    "scenario_name": data.get("scenario_name", ""),
                    "started_at": data.get("started_at"),
                    "ended_at": data.get("ended_at"),
                    "duration_sec": data.get("duration_sec"),
                    "destination": data.get("destination", ""),
                    "simulated": data.get("simulated", False),
                    "transcript_turns": len(data.get("transcript", [])),
                    "has_recording": bool(data.get("recording_id")),
                }
            )
        except Exception as exc:
            logger.warning("Skipping invalid call file %s: %s", path.name, exc)
    results.sort(key=lambda c: c.get("started_at", ""), reverse=True)
    return results


def get_call(call_id: str) -> dict | None:
    """Load a complete call record including transcript."""
    path = CALLS_DIR / f"{call_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load call %s: %s", call_id, exc)
        return None


def delete_call(call_id: str) -> bool:
    """Delete a call record."""
    path = CALLS_DIR / f"{call_id}.json"
    if not path.exists():
        return False
    path.unlink()
    logger.info("Deleted call history call_id=%s", call_id)
    return True


# Module-level singleton
call_history = CallHistoryService()
