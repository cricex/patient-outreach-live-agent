"""Pydantic request and response models for the call API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class StartCallRequest(BaseModel):
    """POST /call/start request body."""
    target_phone_number: str | None = Field(
        None, description="E.164 phone number overriding TARGET_PHONE_NUMBER"
    )
    system_prompt: str | None = Field(
        None, description="Per-call system prompt override"
    )
    call_brief: str | None = Field(
        None, description="Patient-specific CALL_BRIEF context"
    )
    simulate: bool = Field(
        False, description="Skip ACS and simulate call locally (no PSTN)"
    )


class StartCallResponse(BaseModel):
    """POST /call/start response body."""
    call_id: str
    to: str
    prompt_used: str


class HangupResponse(BaseModel):
    """POST /call/hangup response body."""
    ok: bool
    call_id: str


class CallEventsResponse(BaseModel):
    """POST /call/events response body."""
    ok: bool
    processed: int
    ended: list[str] = Field(default_factory=list)
